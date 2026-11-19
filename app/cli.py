"""python -m app.cli token <tg_id>  → توکن ورود ادمین برای پنل وب (tg_id باید در ADMIN_TG_IDS باشد)"""
import sys
from sqlalchemy import select
from .config import ADMIN_TG_IDS
from .db import SessionLocal, engine
from .models import Base, User
from .security import make_token
from . import services

if len(sys.argv) == 3 and sys.argv[1] == "token":
    tg = int(sys.argv[2])
    if tg not in ADMIN_TG_IDS: sys.exit("این tg_id در ADMIN_TG_IDS نیست")
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        u = db.scalar(select(User).where(User.tg_id == tg))
        if not u:
            u = User(tg_id=tg, full_name="admin", ref_code=services.new_ref_code()); db.add(u); db.commit()
        print(make_token(u.id))
else:
    sys.exit(__doc__)
