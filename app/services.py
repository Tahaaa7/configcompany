import secrets, time
from datetime import timedelta
from fastapi import HTTPException
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from . import config
from . import state
from .models import User, Plan, Order, Txn, Coupon, Agent, Payment, Setting, DiscountGroup, Offer, ContentItem, now
from .panel import get_panel

def round_k(x: float) -> int: return int(round(x / 1000) * 1000)

def offer_applies(o: Offer, user: User, t, plan_id: int | None = None) -> bool:
    if not o.active or not (o.starts_at <= t <= o.ends_at): return False
    if o.plan_id and plan_id and o.plan_id != plan_id: return False
    expired = bool(user.plan_id and user.expires_at and user.expires_at < t)
    if o.audience == "expired" and not expired: return False
    if o.audience == "new" and user.plan_id: return False
    return True

def active_offers(db: Session, user: User, plan_id: int | None = None) -> list[Offer]:
    t = now()
    return [o for o in db.scalars(select(Offer).where(Offer.active == True)) if offer_applies(o, user, t, plan_id)]  # noqa: E712

def quote(db: Session, plan: Plan, months: int, coupon_code: str | None, user: User | None = None):
    """قیمت = پایه × تخفیف دوره × max(تخفیف گروه، پیشنهاد ویژه) × کوپن. خروجی: (مبلغ، کوپن، توضیح تخفیف)"""
    if months not in config.DISCOUNTS: raise HTTPException(400, "مدت نامعتبر است")
    if not plan.active: raise HTTPException(400, "این پلن فعال نیست")
    amount = plan.price_month * months * (1 - config.DISCOUNTS[months])
    pct, offer_title = 0, None
    if user:
        g = db.get(DiscountGroup, user.discount_group_id) if user.discount_group_id else None
        if g and g.active: pct = g.percent
        offers = active_offers(db, user, plan.id)
        if offers:
            best = max(offers, key=lambda o: o.percent)
            if best.percent > pct: pct, offer_title = best.percent, best.title
    amount *= 1 - pct / 100
    coupon = None
    if coupon_code:
        coupon = db.scalar(select(Coupon).where(Coupon.code == coupon_code.strip().upper(), Coupon.active == True))  # noqa: E712
        if not coupon or (coupon.max_uses and coupon.used >= coupon.max_uses):
            raise HTTPException(400, "کد تخفیف معتبر نیست")
        amount *= 1 - coupon.percent / 100
    return round_k(amount), coupon, {"percent": pct, "offer": offer_title}

def add_txn(db, user, amount, kind, note=""):
    user.balance += amount
    db.add(Txn(user_id=user.id, amount=amount, kind=kind, note=note))

def provision(db, user: User, plan_traffic_gb: int, devices: int, days: int, plan_id: int | None):
    """امتداد اشتراک روی پنل و ذخیره وضعیت در دیتابیس."""
    base = max(now(), user.expires_at or now())
    expires = base + timedelta(days=days)
    uname = user.panel_username or f"{'m' if user.tg_id < 0 else 'u'}{abs(user.tg_id)}"
    pu = get_panel().upsert(uname, plan_traffic_gb, expires, devices, user.disabled)
    user.panel_username, user.sub_url = pu.username, pu.sub_url
    user.expires_at, user.traffic_gb, user.device_limit = expires, plan_traffic_gb, devices
    if plan_id: user.plan_id = plan_id

def get_setting(db: Session, key: str) -> str:
    row = db.get(Setting, key)
    return row.value if row else config.DEFAULT_SETTINGS[key]

def set_setting(db: Session, key: str, value: str):
    row = db.get(Setting, key)
    if row: row.value = value
    else: db.add(Setting(key=key, value=value))

def referral_percent(db, referrer: User) -> int:
    n = db.scalar(select(func.count()).select_from(User).where(User.referred_by == referrer.id)) or 0
    return next(p for lim, p in config.REF_TIERS if n <= lim)

def referral_levels(db, u: User) -> list[int]:
    return [referral_percent(db, u), int(get_setting(db, "ref_l2")), int(get_setting(db, "ref_l3"))]

def _reward(db, ref: User, pct: int, plan: Plan, amount: int, level: int):
    reward = int(amount * pct / 100)
    if reward <= 0: return
    if ref.reward_mode == "days" and ref.panel_username:
        days = max(1, reward // max(1, plan.price_month // 30))
        provision(db, ref, ref.traffic_gb, ref.device_limit, days, None)
        db.add(Txn(user_id=ref.id, amount=0, kind="referral", note=f"+{days} روز اشتراک (سطح {level})"))
    else:
        add_txn(db, ref, reward, "referral", f"پاداش رفرال سطح {level}")

def pay_referrer(db, buyer: User, plan: Plan, amount: int):
    """رفرال سه‌سطحی: سطح ۱ پلکانی، سطح ۲ و ۳ درصد ثابت از تنظیمات."""
    cur, seen = buyer, {buyer.id}
    for level in (1, 2, 3):
        if not cur.referred_by or cur.referred_by in seen: break
        ref = db.get(User, cur.referred_by)
        if not ref: break
        seen.add(ref.id)
        _reward(db, ref, referral_levels(db, ref)[level - 1] if level == 1 else int(get_setting(db, f"ref_l{level}")), plan, amount, level)
        cur = ref

def grace_available(db, u: User) -> bool:
    return (get_setting(db, "grace_enabled") == "1" and bool(u.plan_id) and bool(u.expires_at) and u.expires_at < now()
            and not u.grace_used and not u.disabled)

def buy(db: Session, user: User, plan: Plan, months: int, coupon_code: str | None):
    amount, coupon, _ = quote(db, plan, months, coupon_code, user)
    if user.balance < amount: raise HTTPException(402, "موجودی کیف پول کافی نیست")
    try:
        provision(db, user, plan.traffic_gb, plan.devices, 30 * months, plan.id)  # اول پنل؛ خطا = بدون کسر پول
    except Exception as e:
        db.rollback(); raise HTTPException(502, f"خطا در ارتباط با پنل: {e}")
    user.grace_used = False
    add_txn(db, user, -amount, "purchase", f"{plan.name} · {months} ماه")
    if coupon: coupon.used += 1
    db.add(Order(user_id=user.id, plan_id=plan.id, months=months, amount=amount, coupon=coupon.code if coupon else None))
    pay_referrer(db, user, plan, amount)
    pay_agent(db, user, amount)
    db.commit()
    return amount

def new_ref_code() -> str: return secrets.token_urlsafe(6).replace("-", "x").replace("_", "y")[:8]

def get_or_create_user(db: Session, tg: dict, start_param: str | None = None, agent_id: int | None = None) -> User:
    u = db.scalar(select(User).where(User.tg_id == tg["id"]))
    if u: return u
    u = User(tg_id=tg["id"], username=tg.get("username"), full_name=tg.get("first_name", ""), ref_code=new_ref_code(), agent_id=agent_id)
    if start_param and start_param.startswith("ref_"):
        ref = db.scalar(select(User).where(User.ref_code == start_param[4:]))
        if ref and ref.agent_id == agent_id: u.referred_by = ref.id   # رفرال فقط داخل همان نماینده
    db.add(u); db.commit()
    u._new = True   # برای اعلان «کاربر جدید» به ادمین
    return u

def pay_agent(db: Session, buyer: User, amount: int):
    if not buyer.agent_id: return
    ag = db.get(Agent, buyer.agent_id)
    reward = int(amount * ag.commission_percent / 100) if ag else 0
    if reward > 0: add_txn(db, db.get(User, ag.user_id), reward, "agent", f"کمیسیون خرید {buyer.full_name or buyer.id}")

def can_decide(db: Session, tg_id: int, p: Payment) -> bool:
    """مدیر کل یا نماینده‌ی صاحب مشتری."""
    if tg_id in config.ADMIN_TG_IDS: return True
    buyer = db.get(User, p.user_id)
    if not buyer or not buyer.agent_id: return False
    ag = db.get(Agent, buyer.agent_id)
    return bool(ag and ag.active and db.get(User, ag.user_id).tg_id == tg_id)

def decide_payment(db: Session, pid: int, action: str):
    p = db.get(Payment, pid)
    if not p or p.status != "pending": raise HTTPException(400, "پرداخت یافت نشد یا قبلاً بررسی شده")
    user = db.get(User, p.user_id)
    if action == "approve":
        add_txn(db, user, p.amount, "topup", f"شارژ #{p.id}"); p.status = "ok"
    elif action == "reject": p.status = "rejected"
    else: raise HTTPException(400, "عملیات نامعتبر")
    db.commit()
    return p, user

def create_manual_user(db: Session, name: str, plan: Plan, days: int, gb: int | None, agent: Agent | None) -> User:
    """ساخت اکانت بدون تلگرام. مدیر کل: رایگان و با حجم/زمان دلخواه؛ نماینده: با قیمت عمده از موجودی خودش."""
    if not 1 <= days <= 3650: raise HTTPException(400, "مدت نامعتبر است")
    price, owner = 0, None
    if agent:
        price = round_k(plan.price_month * days / 30 * (1 - agent.discount_percent / 100))
        owner = db.get(User, agent.user_id)
        if owner.balance < price: raise HTTPException(402, f"موجودی نماینده کافی نیست (نیاز: {price:,} تومان)")
        gb = None
    u = User(tg_id=-(time.time_ns() // 1000), full_name=name, ref_code=new_ref_code(), agent_id=agent.id if agent else None)
    db.add(u); db.flush()
    try: provision(db, u, gb if gb is not None else plan.traffic_gb, plan.devices, days, plan.id)
    except Exception as e:
        db.rollback(); raise HTTPException(502, f"خطا در ارتباط با پنل: {e}")
    if owner: add_txn(db, owner, -price, "agent_sale", f"{plan.name} · {name}")
    db.add(Order(user_id=u.id, plan_id=plan.id, months=max(1, round(days / 30)), amount=price))
    db.commit()
    return u

def maintenance_active(db: Session) -> bool:
    return get_setting(db, "maintenance") == "1" or state.panel_down

def welcome_text(db: Session, name: str) -> str:
    row = db.scalar(select(ContentItem).where(ContentItem.kind == "welcome", ContentItem.active == True).order_by(ContentItem.sort, ContentItem.id))  # noqa: E712
    return (row.body if row else "سلام {name} 👋\nبرای خرید و مدیریت اشتراک، فروشگاه را باز کنید.").replace("{name}", name)
