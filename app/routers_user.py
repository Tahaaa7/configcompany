from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from . import config, services, gateways, bot
from .db import get_db
from .deps import current_user, open_shop
from .models import User, Plan, Txn, Payment, GiftCode, Agent, Order, ContentItem, now
from .panel import get_panel
from .security import verify_init_data, make_token

r = APIRouter()

class LoginIn(BaseModel): init_data: str
class BuyIn(BaseModel):
    plan_id: int
    months: int = 1
    coupon: str | None = None
class GiftIn(BaseModel): code: str
class TopupIn(BaseModel):
    amount: int = Field(ge=10000, le=50_000_000)
    method: str = "card"
    receipt: str = ""
class SettingsIn(BaseModel):
    reward_mode: str | None = Field(None, pattern="^(money|days)$")
    auto_renew: bool | None = None

@r.post("/auth/telegram")
def login(body: LoginIn, db: Session = Depends(get_db)):
    tokens = [(None, config.BOT_TOKEN)] + [(a.id, a.bot_token) for a in db.scalars(select(Agent).where(Agent.active == True, Agent.bot_token != None))]  # noqa: E712,E711
    d = verify_init_data(body.init_data, tokens)
    u = services.get_or_create_user(db, d["user"], d.get("start_param"), d.get("agent_id"))
    if getattr(u, "_new", False): bot.notify_admins("new_user", f"👤 کاربر جدید: {u.full_name or u.tg_id}")
    return {"token": make_token(u.id)}

def _state(u: User):
    active = bool(u.expires_at and u.expires_at > now()) and not u.disabled
    used = 0.0
    if u.panel_username:
        try:
            pu = get_panel().get(u.panel_username); used = pu.used_gb if pu else 0
        except Exception: pass
    return {"active": active, "expires_at": u.expires_at, "days_left": max(0, (u.expires_at - now()).days) if u.expires_at else 0,
            "traffic_gb": u.traffic_gb, "used_gb": round(used, 2), "device_limit": u.device_limit, "sub_url": u.sub_url}

@r.get("/me")
def me(u: User = Depends(current_user), db: Session = Depends(get_db)):
    plan = db.get(Plan, u.plan_id) if u.plan_id else None
    ag = db.get(Agent, u.agent_id) if u.agent_id else None
    return {"id": u.id, "name": u.full_name, "balance": u.balance, "plan": plan.name if plan else None,
            "bot": ag.bot_username if ag else config.BOT_USERNAME, "support": (ag.support_username if ag and ag.support_username else config.SUPPORT_USERNAME),
            "grace_available": services.grace_available(db, u), "grace_days": int(services.get_setting(db, "grace_days")),
            "maintenance": services.maintenance_active(db), "trial_used": u.trial_used, "auto_renew": u.auto_renew, "reward_mode": u.reward_mode, "subscription": _state(u)}

@r.patch("/me/settings")
def settings(body: SettingsIn, u: User = Depends(current_user), db: Session = Depends(get_db)):
    if body.reward_mode: u.reward_mode = body.reward_mode
    if body.auto_renew is not None: u.auto_renew = body.auto_renew
    db.commit(); return {"ok": True}

@r.post("/me/trial", dependencies=[Depends(open_shop)])
def trial(u: User = Depends(current_user), db: Session = Depends(get_db)):
    if u.trial_used or u.expires_at: raise HTTPException(400, "اکانت تست قبلاً استفاده شده است")
    services.provision(db, u, config.TRIAL_GB, 1, config.TRIAL_DAYS, None)
    u.trial_used = True; db.commit(); return _state(u)

@r.post("/me/grace", dependencies=[Depends(open_shop)])
def grace(u: User = Depends(current_user), db: Session = Depends(get_db)):
    if not services.grace_available(db, u): raise HTTPException(400, "دسترسی موقت در دسترس نیست")
    try: services.provision(db, u, u.traffic_gb, u.device_limit, int(services.get_setting(db, "grace_days")), None)
    except Exception as e:
        db.rollback(); raise HTTPException(502, f"خطا در ارتباط با پنل: {e}")
    u.grace_used = True; db.commit(); return _state(u)

@r.get("/plans")
def plans(db: Session = Depends(get_db)):
    return [{"id": p.id, "name": p.name, "price_month": p.price_month, "traffic_gb": p.traffic_gb, "devices": p.devices}
            for p in db.scalars(select(Plan).where(Plan.active == True).order_by(Plan.price_month))]  # noqa: E712

@r.post("/shop/quote")
def quote(body: BuyIn, db: Session = Depends(get_db), u: User = Depends(current_user)):
    p = db.get(Plan, body.plan_id)
    if not p: raise HTTPException(404, "پلن یافت نشد")
    amount, _, info = services.quote(db, p, body.months, body.coupon, u)
    return {"amount": amount, "enough_balance": u.balance >= amount, "info": info}

@r.post("/shop/buy", dependencies=[Depends(open_shop)])
def buy(body: BuyIn, db: Session = Depends(get_db), u: User = Depends(current_user)):
    p = db.get(Plan, body.plan_id)
    if not p: raise HTTPException(404, "پلن یافت نشد")
    amount = services.buy(db, u, p, body.months, body.coupon)
    return {"paid": amount, "balance": u.balance, "subscription": _state(u)}

@r.get("/wallet")
def wallet(u: User = Depends(current_user), db: Session = Depends(get_db)):
    tx = db.scalars(select(Txn).where(Txn.user_id == u.id).order_by(Txn.id.desc()).limit(50))
    return {"balance": u.balance, "transactions": [{"amount": t.amount, "kind": t.kind, "note": t.note, "at": t.created_at} for t in tx]}

@r.post("/wallet/topup", dependencies=[Depends(open_shop)])
def topup(body: TopupIn, u: User = Depends(current_user), db: Session = Depends(get_db)):
    if body.method == "gateway":
        if not (config.ZARINPAL_MERCHANT and config.PUBLIC_URL): raise HTTPException(400, "درگاه آنلاین فعال نیست")
        p = Payment(user_id=u.id, amount=body.amount, method="gateway"); db.add(p); db.commit()
        try:
            p.authority = gateways.zp_request(p.amount, f"شارژ کیف پول #{p.id}", f"{config.PUBLIC_URL}/pay/zarinpal/callback"); db.commit()
        except Exception as e:
            p.status = "rejected"; db.commit(); raise HTTPException(502, f"اتصال به درگاه ناموفق بود: {e}")
        return {"payment_id": p.id, "status": "pending", "pay_url": gateways.zp_start_url(p.authority)}
    p = Payment(user_id=u.id, amount=body.amount, method="card", receipt=body.receipt); db.add(p); db.commit()
    bot.notify_admins_payment(p, u)
    return {"payment_id": p.id, "status": "pending"}

@r.post("/wallet/gift")
def gift(body: GiftIn, u: User = Depends(current_user), db: Session = Depends(get_db)):
    g = db.scalar(select(GiftCode).where(GiftCode.code == body.code.strip().upper(), GiftCode.used_by == None))  # noqa: E711
    if not g: raise HTTPException(400, "کد هدیه معتبر نیست یا استفاده شده")
    g.used_by = u.id; services.add_txn(db, u, g.amount, "gift", f"کد هدیه {g.code}"); db.commit()
    return {"balance": u.balance}

@r.get("/referral")
def referral(u: User = Depends(current_user), db: Session = Depends(get_db)):
    n = db.scalar(select(func.count()).select_from(User).where(User.referred_by == u.id)) or 0
    earned = db.scalar(select(func.coalesce(func.sum(Txn.amount), 0)).where(Txn.user_id == u.id, Txn.kind == "referral")) or 0
    return {"code": u.ref_code, "link_param": f"ref_{u.ref_code}", "invited": n,
            "percent": services.referral_percent(db, u), "levels": services.referral_levels(db, u), "earned": earned, "reward_mode": u.reward_mode}

@r.get("/referral/network")
def network(u: User = Depends(current_user), db: Session = Depends(get_db)):
    ids, counts, direct = [u.id], [], []
    for lvl in range(3):
        rows = db.scalars(select(User).where(User.referred_by.in_(ids))).all() if ids else []
        counts.append(len(rows))
        if lvl == 0:
            direct = [{"name": (x.full_name or "کاربر")[:14], "spent": db.scalar(select(func.coalesce(func.sum(Order.amount), 0)).where(Order.user_id == x.id)) or 0} for x in rows[:50]]
        ids = [x.id for x in rows]
    return {"counts": counts, "direct": direct}

@r.get("/offers")
def offers(u: User = Depends(current_user), db: Session = Depends(get_db)):
    return sorted([{"id": o.id, "title": o.title, "percent": o.percent, "plan_id": o.plan_id, "ends_at": o.ends_at} for o in services.active_offers(db, u)], key=lambda x: -x["percent"])

@r.get("/content")
def content(db: Session = Depends(get_db)):
    rows = db.scalars(select(ContentItem).where(ContentItem.active == True).order_by(ContentItem.kind, ContentItem.sort, ContentItem.id))  # noqa: E712
    return [{"id": c.id, "kind": c.kind, "title": c.title, "body": c.body} for c in rows]
