from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session
from .config import ADMIN_TG_IDS
from .db import get_db
from .models import User
from .security import read_token

def current_user(authorization: str = Header(""), db: Session = Depends(get_db)) -> User:
    if not authorization.startswith("Bearer "): raise HTTPException(401, "ورود لازم است")
    u = db.get(User, read_token(authorization[7:]))
    if not u: raise HTTPException(401, "کاربر یافت نشد")
    return u

def admin_user(u: User = Depends(current_user)) -> User:
    if u.tg_id not in ADMIN_TG_IDS: raise HTTPException(403, "دسترسی ادمین لازم است")
    return u

def open_shop(u: User = Depends(current_user), db: Session = Depends(get_db)):
    """در حالت تعمیر (دستی یا خودکار) خرید/شارژ/تست برای کاربران عادی بسته است."""
    from . import services
    if u.tg_id not in ADMIN_TG_IDS and services.maintenance_active(db):
        raise HTTPException(503, "سرویس موقتاً در حال تعمیر است؛ کمی بعد دوباره تلاش کنید")
