from datetime import datetime, timezone
from sqlalchemy import String, Integer, Float, BigInteger, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

def now(): return datetime.now(timezone.utc).replace(tzinfo=None)

class Base(DeclarativeBase): pass

class Plan(Base):
    __tablename__ = "plans"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(60))
    price_month: Mapped[int] = mapped_column(Integer)          # تومان
    traffic_gb: Mapped[int] = mapped_column(Integer, default=0)  # 0 = نامحدود
    devices: Mapped[int] = mapped_column(Integer, default=2)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")

class DiscountGroup(Base):
    __tablename__ = "discount_groups"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(60))
    percent: Mapped[int] = mapped_column(Integer)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

class Offer(Base):
    """پیشنهاد ویژه‌ی زمان‌دار؛ audience: all | expired | new"""
    __tablename__ = "offers"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(120))
    plan_id: Mapped[int | None] = mapped_column(ForeignKey("plans.id"), nullable=True)
    percent: Mapped[int] = mapped_column(Integer)
    audience: Mapped[str] = mapped_column(String(10), default="all")
    starts_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    ends_at: Mapped[datetime] = mapped_column(DateTime)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

class ContentItem(Base):
    """kind: faq | rules | privacy | welcome | news"""
    __tablename__ = "content"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(10), index=True)
    title: Mapped[str] = mapped_column(String(120))
    body: Mapped[str] = mapped_column(Text, default="")
    sort: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

class Agent(Base):
    __tablename__ = "agents"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    name: Mapped[str] = mapped_column(String(80))
    bot_token: Mapped[str | None] = mapped_column(String(120), nullable=True)
    bot_username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    support_username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    discount_percent: Mapped[int] = mapped_column(Integer, default=0)    # تخفیف عمده‌فروشی برای ساخت/تمدید دستی
    commission_percent: Mapped[int] = mapped_column(Integer, default=0)  # کمیسیون خرید مشتریان ربات نماینده
    active: Mapped[bool] = mapped_column(Boolean, default=True)

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    tg_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    full_name: Mapped[str] = mapped_column(String(120), default="")
    balance: Mapped[int] = mapped_column(Integer, default=0)
    ref_code: Mapped[str] = mapped_column(String(16), unique=True)
    referred_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reward_mode: Mapped[str] = mapped_column(String(8), default="money")  # money | days
    panel_username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sub_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    plan_id: Mapped[int | None] = mapped_column(ForeignKey("plans.id"), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    traffic_gb: Mapped[int] = mapped_column(Integer, default=0)
    device_limit: Mapped[int] = mapped_column(Integer, default=1)
    trial_used: Mapped[bool] = mapped_column(Boolean, default=False)
    disabled: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_renew: Mapped[bool] = mapped_column(Boolean, default=False)
    agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id", use_alter=True, name="fk_users_agent_id"), nullable=True, index=True)  # use_alter: وابستگی حلقوی users↔agents
    discount_group_id: Mapped[int | None] = mapped_column(ForeignKey("discount_groups.id"), nullable=True)
    last_used_gb: Mapped[float | None] = mapped_column(Float, nullable=True)
    warned_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    grace_used: Mapped[bool] = mapped_column(Boolean, default=False)
    notified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

class Order(Base):
    __tablename__ = "orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("plans.id"))
    months: Mapped[int] = mapped_column(Integer)
    amount: Mapped[int] = mapped_column(Integer)
    coupon: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

class Txn(Base):
    __tablename__ = "transactions"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    amount: Mapped[int] = mapped_column(Integer)  # مثبت = ورودی، منفی = خروجی
    kind: Mapped[str] = mapped_column(String(20))  # topup | purchase | referral | gift
    note: Mapped[str] = mapped_column(String(120), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

class Payment(Base):
    __tablename__ = "payments"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    amount: Mapped[int] = mapped_column(Integer)
    method: Mapped[str] = mapped_column(String(20), default="card")
    status: Mapped[str] = mapped_column(String(10), default="pending")  # pending | ok | rejected
    receipt: Mapped[str] = mapped_column(String(200), default="")
    authority: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

class Coupon(Base):
    __tablename__ = "coupons"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    percent: Mapped[int] = mapped_column(Integer)
    max_uses: Mapped[int] = mapped_column(Integer, default=0)  # 0 = بی‌نهایت
    used: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

class GiftCode(Base):
    __tablename__ = "gift_codes"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    amount: Mapped[int] = mapped_column(Integer)
    used_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
