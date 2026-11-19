from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from . import config, services, gateways, bot
from .db import get_db
from .models import Payment, User

r = APIRouter()

@r.get("/pay/zarinpal/callback", include_in_schema=False)
def zarinpal_callback(Authority: str, Status: str = "", db: Session = Depends(get_db)):
    p = db.scalar(select(Payment).where(Payment.authority == Authority))
    if not p: raise HTTPException(404, "پرداخت یافت نشد")
    if p.status == "pending":
        try: ok = Status == "OK" and gateways.zp_verify(Authority, p.amount)
        except Exception as e: raise HTTPException(502, f"تأیید با درگاه ناموفق بود؛ چند دقیقه بعد دوباره تلاش کنید ({e})")
        user = db.get(User, p.user_id)
        if ok:
            services.add_txn(db, user, p.amount, "topup", f"شارژ آنلاین #{p.id}"); p.status = "ok"; db.commit()
            bot.send_to(user, f"✅ پرداخت موفق بود؛ {p.amount:,} تومان به کیف پول اضافه شد.", bot.app_button())
        else:
            p.status = "rejected"; db.commit()
            bot.send_to(user, "پرداخت انجام نشد یا لغو شد.")
    return RedirectResponse(f"https://t.me/{config.BOT_USERNAME}" if config.BOT_USERNAME else "/miniapp/?paid=1")
