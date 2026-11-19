from dataclasses import dataclass
from datetime import timedelta
import time
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from . import services, bot, backup
from .config import ADMIN_TG_IDS, DEFAULT_SETTINGS
from .db import get_db, SessionLocal
from .deps import current_user
from .models import User, Plan, Payment, Coupon, GiftCode, Order, Agent, DiscountGroup, Offer, ContentItem, Txn, now
from .panel import get_panel

r = APIRouter(prefix="/admin")

@dataclass
class Staff:
    user: User
    agent: Agent | None
    @property
    def master(self): return self.agent is None

def staff(u: User = Depends(current_user), db: Session = Depends(get_db)) -> Staff:
    if u.tg_id in ADMIN_TG_IDS: return Staff(u, None)
    ag = db.scalar(select(Agent).where(Agent.user_id == u.id, Agent.active == True))  # noqa: E712
    if ag: return Staff(u, ag)
    raise HTTPException(403, "دسترسی مدیر یا نماینده لازم است")

def master(s: Staff = Depends(staff)) -> Staff:
    if not s.master: raise HTTPException(403, "فقط مدیر کل")
    return s

def own_user(db: Session, s: Staff, uid: int) -> User:
    u = db.get(User, uid)
    if not u or (not s.master and u.agent_id != s.agent.id): raise HTTPException(404, "کاربر یافت نشد")
    return u

class PlanIn(BaseModel):
    name: str; price_month: int = Field(ge=0); traffic_gb: int = Field(0, ge=0); devices: int = Field(2, ge=1); active: bool = True
class UserPatch(BaseModel):
    discount_group_id: int | None = None; disabled: bool | None = None; add_days: int | None = Field(None, ge=0, le=3650); reset_usage: bool = False
class CreateUserIn(BaseModel):
    name: str = Field(min_length=1, max_length=80); plan_id: int; days: int = 30; traffic_gb: int | None = Field(None, ge=0)
class CouponIn(BaseModel):
    code: str; percent: int = Field(ge=1, le=100); max_uses: int = 0
class GiftIn(BaseModel):
    code: str; amount: int = Field(gt=0)
class AgentIn(BaseModel):
    tg_id: int; name: str; bot_token: str | None = None; support_username: str | None = None
    discount_percent: int = Field(0, ge=0, le=100); commission_percent: int = Field(0, ge=0, le=100); balance: int = Field(0, ge=0)
class AgentPatch(BaseModel):
    active: bool | None = None; discount_percent: int | None = Field(None, ge=0, le=100)
    commission_percent: int | None = Field(None, ge=0, le=100); add_balance: int | None = None

@r.get("/me")
def me(s: Staff = Depends(staff)):
    return {"role": "master" if s.master else "agent", "name": s.agent.name if s.agent else "مدیر کل",
            "balance": 0 if s.master else s.user.balance, "discount_percent": 0 if s.master else s.agent.discount_percent}

@r.get("/stats")
def stats(s: Staff = Depends(staff), db: Session = Depends(get_db)):
    c = lambda q: db.scalar(q) or 0  # noqa: E731
    sc = (lambda q: q) if s.master else (lambda q: q.where(User.agent_id == s.agent.id))
    return {"users": c(sc(select(func.count()).select_from(User).where(User.tg_id != None))),  # noqa: E711
            "active": c(sc(select(func.count()).select_from(User).where(User.expires_at > now(), User.disabled == False))),  # noqa: E712
            "sales_today": c(sc(select(func.sum(Order.amount)).join(User, User.id == Order.user_id).where(Order.created_at >= now().replace(hour=0, minute=0, second=0)))),
            "pending_payments": c(sc(select(func.count()).select_from(Payment).join(User, User.id == Payment.user_id).where(Payment.status == "pending")))}

@r.get("/users")
def users(q: str = "", status: str = "all", s: Staff = Depends(staff), db: Session = Depends(get_db)):
    st = select(User).order_by(User.id.desc()).limit(200)
    if not s.master: st = st.where(User.agent_id == s.agent.id)
    if q: st = st.where((User.username.ilike(f"%{q}%")) | (User.full_name.ilike(f"%{q}%")))
    if status == "active": st = st.where(User.expires_at > now(), User.disabled == False)  # noqa: E712
    if status == "expired": st = st.where(User.expires_at <= now())
    if status == "disabled": st = st.where(User.disabled == True)  # noqa: E712
    return [{"id": u.id, "tg_id": u.tg_id, "username": u.username, "name": u.full_name, "balance": u.balance, "agent_id": u.agent_id,
             "plan_id": u.plan_id, "discount_group_id": u.discount_group_id, "expires_at": u.expires_at, "traffic_gb": u.traffic_gb, "disabled": u.disabled, "sub_url": u.sub_url} for u in db.scalars(st)]

@r.post("/users")
def create_user(b: CreateUserIn, s: Staff = Depends(staff), db: Session = Depends(get_db)):
    plan = db.get(Plan, b.plan_id)
    if not plan or not plan.active: raise HTTPException(400, "پلن معتبر نیست")
    u = services.create_manual_user(db, b.name.strip(), plan, b.days, b.traffic_gb, s.agent)
    return {"id": u.id, "sub_url": u.sub_url, "expires_at": u.expires_at}

@r.patch("/users/{uid}")
def patch_user(uid: int, body: UserPatch, s: Staff = Depends(staff), db: Session = Depends(get_db)):
    u = own_user(db, s, uid)
    if body.discount_group_id is not None:
        if not s.master: raise HTTPException(403, "فقط مدیر کل")
        u.discount_group_id = body.discount_group_id or None
    if body.disabled is not None: u.disabled = body.disabled
    if u.panel_username:
        days = body.add_days or 0
        if days and not s.master:   # تمدید توسط نماینده با قیمت عمده از موجودی خودش
            plan = db.get(Plan, u.plan_id) if u.plan_id else None
            if not plan: raise HTTPException(400, "کاربر پلن ندارد")
            price = services.round_k(plan.price_month * days / 30 * (1 - s.agent.discount_percent / 100))
            if s.user.balance < price: raise HTTPException(402, f"موجودی کافی نیست (نیاز: {price:,} تومان)")
            services.add_txn(db, s.user, -price, "agent_sale", f"تمدید {u.full_name} · {days} روز")
        exp = max(now(), u.expires_at or now()) + timedelta(days=days) if days else (u.expires_at or now())
        get_panel().upsert(u.panel_username, u.traffic_gb, exp, u.device_limit, u.disabled)
        u.expires_at = exp
        if body.reset_usage: get_panel().reset_usage(u.panel_username)
    db.commit(); return {"ok": True}

@r.delete("/users/{uid}")
def delete_user(uid: int, s: Staff = Depends(staff), db: Session = Depends(get_db)):
    u = own_user(db, s, uid)
    if u.panel_username:
        try: get_panel().delete(u.panel_username)
        except Exception as e: raise HTTPException(502, f"حذف از پنل ناموفق بود: {e}")
    u.disabled, u.expires_at, u.panel_username, u.sub_url = True, None, None, None   # آرشیو (سفارش‌ها و تراکنش‌ها حفظ می‌شوند)
    db.commit(); return {"ok": True}

@r.get("/plans")
def plans(s: Staff = Depends(staff), db: Session = Depends(get_db)):
    d = 0 if s.master else s.agent.discount_percent
    return [{"id": p.id, "name": p.name, "price_month": p.price_month, "agent_price": services.round_k(p.price_month * (1 - d / 100)),
             "traffic_gb": p.traffic_gb, "devices": p.devices, "active": p.active} for p in db.scalars(select(Plan))]

@r.post("/plans", dependencies=[Depends(master)])
def add_plan(b: PlanIn, db: Session = Depends(get_db)):
    p = Plan(**b.model_dump()); db.add(p); db.commit(); return {"id": p.id}

@r.put("/plans/{pid}", dependencies=[Depends(master)])
def edit_plan(pid: int, b: PlanIn, db: Session = Depends(get_db)):
    p = db.get(Plan, pid)
    if not p: raise HTTPException(404, "پلن یافت نشد")
    for k, v in b.model_dump().items(): setattr(p, k, v)
    db.commit(); return {"ok": True}

@r.get("/payments")
def payments(status: str = "pending", s: Staff = Depends(staff), db: Session = Depends(get_db)):
    st = select(Payment).join(User, User.id == Payment.user_id).where(Payment.status == status).order_by(Payment.id.desc()).limit(100)
    if not s.master: st = st.where(User.agent_id == s.agent.id)
    return [{"id": p.id, "user_id": p.user_id, "amount": p.amount, "method": p.method, "receipt": p.receipt, "status": p.status, "at": p.created_at} for p in db.scalars(st)]

@r.post("/payments/{pid}/{action}")
def decide(pid: int, action: str, s: Staff = Depends(staff), db: Session = Depends(get_db)):
    p0 = db.get(Payment, pid)
    if not p0 or not services.can_decide(db, s.user.tg_id, p0): raise HTTPException(404, "پرداخت یافت نشد")
    p, user = services.decide_payment(db, pid, action)
    bot.send_to(user, "کیف پول شما شارژ شد ✅" if p.status == "ok" else "درخواست شارژ شما رد شد.")
    return {"status": p.status}

@r.post("/coupons", dependencies=[Depends(master)])
def add_coupon(b: CouponIn, db: Session = Depends(get_db)):
    db.add(Coupon(code=b.code.upper(), percent=b.percent, max_uses=b.max_uses)); db.commit(); return {"ok": True}

@r.post("/gift-codes", dependencies=[Depends(master)])
def add_gift(b: GiftIn, db: Session = Depends(get_db)):
    db.add(GiftCode(code=b.code.upper(), amount=b.amount)); db.commit(); return {"ok": True}

@r.get("/settings", dependencies=[Depends(master)])
def get_settings(db: Session = Depends(get_db)):
    return {k: services.get_setting(db, k) for k in DEFAULT_SETTINGS}

@r.put("/settings", dependencies=[Depends(master)])
def put_settings(body: dict[str, str], db: Session = Depends(get_db)):
    for k, v in body.items():
        if k not in DEFAULT_SETTINGS: continue
        if not v.isdigit(): raise HTTPException(400, f"مقدار {k} باید عدد باشد")
        services.set_setting(db, k, v)
    db.commit(); return {"ok": True}

@r.post("/backup", dependencies=[Depends(master)])
def backup_now():
    try: n = backup.do_backup()
    except Exception as e: raise HTTPException(502, f"بکاپ ناموفق بود: {e}")
    return {"ok": True, "size": n}

@r.get("/agents", dependencies=[Depends(master)])
def agents(db: Session = Depends(get_db)):
    out = []
    for a in db.scalars(select(Agent).order_by(Agent.id)):
        owner = db.get(User, a.user_id)
        out.append({"id": a.id, "name": a.name, "tg_id": owner.tg_id, "bot_username": a.bot_username, "support_username": a.support_username,
                    "discount_percent": a.discount_percent, "commission_percent": a.commission_percent, "balance": owner.balance, "active": a.active,
                    "users": db.scalar(select(func.count()).select_from(User).where(User.agent_id == a.id)) or 0})
    return out

@r.post("/agents", dependencies=[Depends(master)])
def add_agent(b: AgentIn, db: Session = Depends(get_db)):
    username = None
    if b.bot_token:
        try: username = bot.verify_token(b.bot_token.strip())
        except Exception: raise HTTPException(400, "توکن ربات نامعتبر است")
    user = services.get_or_create_user(db, {"id": b.tg_id, "first_name": b.name})
    if db.scalar(select(Agent).where(Agent.user_id == user.id)): raise HTTPException(400, "این کاربر قبلاً نماینده است")
    a = Agent(user_id=user.id, name=b.name, bot_token=(b.bot_token or "").strip() or None, bot_username=username,
              support_username=b.support_username, discount_percent=b.discount_percent, commission_percent=b.commission_percent)
    db.add(a); db.commit()
    if b.balance: services.add_txn(db, user, b.balance, "topup", "شارژ اولیه نماینده"); db.commit()
    if a.bot_token: bot.register(a)
    return {"id": a.id, "bot_username": username}

@r.patch("/agents/{aid}", dependencies=[Depends(master)])
def patch_agent(aid: int, b: AgentPatch, db: Session = Depends(get_db)):
    a = db.get(Agent, aid)
    if not a: raise HTTPException(404, "نماینده یافت نشد")
    if b.discount_percent is not None: a.discount_percent = b.discount_percent
    if b.commission_percent is not None: a.commission_percent = b.commission_percent
    if b.add_balance: services.add_txn(db, db.get(User, a.user_id), b.add_balance, "topup", "شارژ توسط مدیر کل")
    if b.active is not None:
        a.active = b.active
        if a.bot_token: (bot.register(a) if a.active else bot.unregister(a.id))
    db.commit(); return {"ok": True}

class GroupIn(BaseModel):
    name: str = Field(min_length=1, max_length=60); percent: int = Field(ge=1, le=90); active: bool = True
class OfferIn(BaseModel):
    title: str = Field(min_length=1, max_length=120); plan_id: int | None = None; percent: int = Field(ge=1, le=90)
    audience: str = Field("all", pattern="^(all|expired|new)$"); days: int = Field(7, ge=1, le=365)
class OfferPatch(BaseModel): active: bool
class ContentIn(BaseModel):
    kind: str = Field(pattern="^(faq|rules|privacy|welcome|news)$"); title: str = Field(min_length=1, max_length=120)
    body: str = Field("", max_length=4000); sort: int = 0; active: bool = True

@r.get("/discount-groups", dependencies=[Depends(master)])
def groups(db: Session = Depends(get_db)):
    return [{"id": g.id, "name": g.name, "percent": g.percent, "active": g.active, "users": db.scalar(select(func.count()).select_from(User).where(User.discount_group_id == g.id)) or 0} for g in db.scalars(select(DiscountGroup))]

@r.post("/discount-groups", dependencies=[Depends(master)])
def add_group(b: GroupIn, db: Session = Depends(get_db)):
    g = DiscountGroup(**b.model_dump()); db.add(g); db.commit(); return {"id": g.id}

@r.put("/discount-groups/{gid}", dependencies=[Depends(master)])
def edit_group(gid: int, b: GroupIn, db: Session = Depends(get_db)):
    g = db.get(DiscountGroup, gid)
    if not g: raise HTTPException(404, "گروه یافت نشد")
    for k, v in b.model_dump().items(): setattr(g, k, v)
    db.commit(); return {"ok": True}

@r.get("/offers", dependencies=[Depends(master)])
def offers_list(db: Session = Depends(get_db)):
    return [{"id": o.id, "title": o.title, "plan_id": o.plan_id, "percent": o.percent, "audience": o.audience, "ends_at": o.ends_at, "active": o.active} for o in db.scalars(select(Offer).order_by(Offer.id.desc()))]

@r.post("/offers", dependencies=[Depends(master)])
def add_offer(b: OfferIn, db: Session = Depends(get_db)):
    o = Offer(title=b.title, plan_id=b.plan_id, percent=b.percent, audience=b.audience, starts_at=now(), ends_at=now() + timedelta(days=b.days))
    db.add(o); db.commit(); return {"id": o.id}

@r.patch("/offers/{oid}", dependencies=[Depends(master)])
def patch_offer(oid: int, b: OfferPatch, db: Session = Depends(get_db)):
    o = db.get(Offer, oid)
    if not o: raise HTTPException(404, "پیشنهاد یافت نشد")
    o.active = b.active; db.commit(); return {"ok": True}

@r.delete("/offers/{oid}", dependencies=[Depends(master)])
def del_offer(oid: int, db: Session = Depends(get_db)):
    o = db.get(Offer, oid)
    if o: db.delete(o); db.commit()
    return {"ok": True}

def _send_offer(oid: int, ids: list):
    with SessionLocal() as db:
        o = db.get(Offer, oid)
        for uid in ids:
            u = db.get(User, uid)
            if o and u:
                bot.send_to(u, f"🎁 {o.title}\n{o.percent}٪ تخفیف تا {o.ends_at:%Y-%m-%d}", bot.app_button()); time.sleep(0.05)   # ≈ ۲۰ پیام در ثانیه

@r.post("/offers/{oid}/announce", dependencies=[Depends(master)])
def announce(oid: int, bg: BackgroundTasks, db: Session = Depends(get_db)):
    o = db.get(Offer, oid)
    if not o: raise HTTPException(404, "پیشنهاد یافت نشد")
    t = now()
    ids = [u.id for u in db.scalars(select(User).where(User.tg_id > 0, User.disabled == False, User.agent_id == None)) if services.offer_applies(o, u, t)]  # noqa: E712,E711
    bg.add_task(_send_offer, o.id, ids)
    return {"recipients": len(ids)}

@r.get("/content", dependencies=[Depends(master)])
def content_list(db: Session = Depends(get_db)):
    return [{"id": c.id, "kind": c.kind, "title": c.title, "body": c.body, "sort": c.sort, "active": c.active} for c in db.scalars(select(ContentItem).order_by(ContentItem.kind, ContentItem.sort))]

@r.post("/content", dependencies=[Depends(master)])
def content_add(b: ContentIn, db: Session = Depends(get_db)):
    c = ContentItem(**b.model_dump()); db.add(c); db.commit(); return {"id": c.id}

@r.put("/content/{cid}", dependencies=[Depends(master)])
def content_edit(cid: int, b: ContentIn, db: Session = Depends(get_db)):
    c = db.get(ContentItem, cid)
    if not c: raise HTTPException(404, "مورد یافت نشد")
    for k, v in b.model_dump().items(): setattr(c, k, v)
    db.commit(); return {"ok": True}

@r.delete("/content/{cid}", dependencies=[Depends(master)])
def content_del(cid: int, db: Session = Depends(get_db)):
    c = db.get(ContentItem, cid)
    if c: db.delete(c); db.commit()
    return {"ok": True}

@r.get("/analytics")
def analytics(days: int = 30, s: Staff = Depends(staff), db: Session = Depends(get_db)):
    days = max(1, min(days, 365)); since = now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days)
    sc = (lambda q: q) if s.master else (lambda q: q.where(User.agent_id == s.agent.id))
    j = lambda q: sc(q.join(User, User.id == Order.user_id).where(Order.created_at >= since))  # noqa: E731
    per_day = {str(d): (n, rev or 0) for d, n, rev in db.execute(j(select(func.date(Order.created_at), func.count(), func.sum(Order.amount))).group_by(func.date(Order.created_at)))}
    daily = []
    for i in range(days + 1):
        d = (since + timedelta(days=i)).date().isoformat(); n, rev = per_day.get(d, (0, 0)); daily.append({"date": d, "orders": n, "revenue": rev})
    revenue, orders = sum(x["revenue"] for x in daily), sum(x["orders"] for x in daily)
    paying = db.scalar(j(select(func.count(func.distinct(Order.user_id))))) or 0
    total_users = db.scalar(sc(select(func.count()).select_from(User))) or 0
    top = [{"name": n, "orders": c, "revenue": rv or 0} for n, c, rv in db.execute(j(select(Plan.name, func.count(), func.sum(Order.amount)).join(Plan, Plan.id == Order.plan_id)).group_by(Plan.name).order_by(func.sum(Order.amount).desc()))]
    tx = lambda kind: db.scalar(sc(select(func.coalesce(func.sum(Txn.amount), 0)).join(User, User.id == Txn.user_id).where(Txn.kind == kind, Txn.created_at >= since))) or 0  # noqa: E731
    return {"days": days, "revenue": revenue, "orders": orders, "paying_users": paying, "arpu": int(revenue / paying) if paying else 0,
            "new_users": db.scalar(sc(select(func.count()).select_from(User).where(User.created_at >= since))) or 0,
            "conversion": round(100 * paying / total_users) if total_users else 0, "daily": daily, "top_plans": top,
            "topups": tx("topup"), "referral_paid": tx("referral")}
