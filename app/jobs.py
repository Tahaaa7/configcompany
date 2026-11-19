import asyncio, logging
from datetime import timedelta
from fastapi import HTTPException
from sqlalchemy import select
from . import services, bot, state, backup
from .db import SessionLocal
from .models import User, Plan, Order, Setting, now
from .panel import get_panel

log = logging.getLogger("jobs")

def _notify_once(db, u: User, text: str):
    if u.notified_at and now() - u.notified_at < timedelta(hours=24): return
    bot.send_to(u, text, bot.app_button()); u.notified_at = now(); db.commit()

def tick():
    with SessionLocal() as db:
        q = select(User).where(User.expires_at != None, User.plan_id != None, User.disabled == False,  # noqa: E711,E712
                               User.expires_at <= now() + timedelta(days=3), User.expires_at >= now() - timedelta(days=1))
        for u in db.scalars(q).all():
            left = u.expires_at - now()
            if u.auto_renew and left <= timedelta(hours=24):
                plan = db.get(Plan, u.plan_id)
                months = db.scalar(select(Order.months).where(Order.user_id == u.id).order_by(Order.id.desc()).limit(1)) or 1
                try:
                    paid = services.buy(db, u, plan, months, None)
                    bot.send_to(u, f"✅ اشتراک شما به‌صورت خودکار تمدید شد ({paid:,} تومان از کیف پول)."); continue
                except HTTPException as e:
                    db.rollback()
                    _notify_once(db, u, "⚠️ تمدید خودکار انجام نشد: " + ("موجودی کیف پول کافی نیست." if e.status_code == 402 else str(e.detail)))
                    continue
            if left > timedelta(0): _notify_once(db, u, f"⏰ اشتراک شما {max(1, left.days)} روز دیگر منقضی می‌شود.")
            else: _notify_once(db, u, "اشتراک شما منقضی شد. برای تمدید فروشگاه را باز کنید.")
        _trial(db)
        _monitor(db)
        _backup(db)

def _trial(db):
    """تبدیل خودکار تست به خرید (اگر ادمین فعال کرده و موجودی کافی است) و در غیر این صورت یادآوری."""
    cid = int(services.get_setting(db, "trial_convert_plan_id")); months = int(services.get_setting(db, "trial_convert_months"))
    q = select(User).where(User.plan_id == None, User.trial_used == True, User.disabled == False,  # noqa: E711,E712
                           User.expires_at < now(), User.expires_at >= now() - timedelta(days=1))
    for u in db.scalars(q).all():
        plan = db.get(Plan, cid) if cid else None
        if plan:
            try:
                paid = services.buy(db, u, plan, months, None)
                bot.send_to(u, f"✅ اکانت تست شما به اشتراک «{plan.name}» تبدیل شد ({paid:,} تومان از کیف پول)."); continue
            except HTTPException as e:
                db.rollback()
                _notify_once(db, u, "اکانت تست شما تمام شد. " + ("برای ادامه کیف پول را شارژ کنید." if e.status_code == 402 else "برای ادامه فروشگاه را باز کنید."))
                continue
        _notify_once(db, u, "اکانت تست شما تمام شد. برای ادامه یک پلن انتخاب کنید.")

def detect_anomalies(prev: dict, cur: dict, threshold_gb: float) -> list:
    """کاربرانی که از آخرین اندازه‌گیری بیش از آستانه مصرف کرده‌اند؛ کاربر بدون baseline نادیده گرفته می‌شود."""
    out = [(n, round(used - prev[n], 1)) for n, used in cur.items() if n in prev and used - prev[n] >= threshold_gb]
    return sorted(out, key=lambda x: -x[1])

def _monitor(db):
    try: cur = get_panel().list_usage()
    except Exception as e:
        log.warning("list_usage failed: %s", e); return
    if not cur: return
    users = {u.panel_username: u for u in db.scalars(select(User).where(User.panel_username != None))}  # noqa: E711
    prev = {n: u.last_used_gb for n, u in users.items() if u.last_used_gb is not None}
    hits = detect_anomalies(prev, {n: v for n, v in cur.items() if n in users}, float(services.get_setting(db, "anomaly_gb")))
    if hits: bot.notify_admins("anomaly", "⚠️ مصرف غیرعادی (از بررسی قبلی):\n" + "\n".join(f"• {users[n].full_name or n}: +{d} GB" for n, d in hits[:10]))
    for n, u in users.items():
        if n not in cur: continue
        u.last_used_gb = cur[n]
        if u.traffic_gb and cur[n] >= 0.9 * u.traffic_gb and (not u.warned_at or now() - u.warned_at > timedelta(days=1)):
            bot.send_to(u, "⚠️ بیش از ۹۰٪ حجم اشتراک شما مصرف شده است.", bot.app_button()); u.warned_at = now()
    db.commit()

def _backup(db):
    if services.get_setting(db, "backup_enabled") != "1": return
    t = now()
    if t.hour != int(services.get_setting(db, "backup_hour")): return   # ساعت UTC
    row, today = db.get(Setting, "last_backup"), t.strftime("%Y-%m-%d")
    if row and row.value == today: return
    try: backup.do_backup()
    except Exception as e:
        bot.alert_admins(f"❌ بکاپ خودکار ناموفق بود: {e}"); return
    services.set_setting(db, "last_backup", today); db.commit()

def health_tick():
    """تشخیص خودکار از دسترس خارج شدن پنل: دو شکست پیاپی = حالت تعمیر خودکار."""
    try: ok = get_panel().ping()
    except Exception: ok = False
    if not ok:
        state.fails += 1
        if state.fails >= 2 and not state.panel_down:
            state.panel_down = True; bot.notify_admins("panel", "🔴 پنل در دسترس نیست؛ حالت تعمیر خودکار فعال شد.")
    else:
        state.fails = 0
        if state.panel_down:
            state.panel_down = False; bot.notify_admins("panel", "🟢 پنل دوباره در دسترس است؛ حالت تعمیر خودکار برداشته شد.")

async def health_loop(every: int = 120):
    while True:
        try: await asyncio.to_thread(health_tick)
        except Exception: log.exception("health failed")
        await asyncio.sleep(every)

async def loop(every: int = 1800):
    while True:
        try: await asyncio.to_thread(tick)
        except Exception: log.exception("tick failed")
        await asyncio.sleep(every)
