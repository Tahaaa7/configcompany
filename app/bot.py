import asyncio, logging
import httpx
from sqlalchemy import select
from . import config, services
from .db import SessionLocal
from .models import Agent, User, Payment

log = logging.getLogger("bot")
BOTS: dict = {}     # agent_id|None → Bot
TASKS: list = []
LOOP = None

class Bot:
    def __init__(self, token: str, agent_id=None, name: str = ""):
        self.token, self.agent_id, self.name = token, agent_id, name
        self.api = f"https://api.telegram.org/bot{token}"
        self.c = httpx.Client(timeout=20)
        self.stop = False

    def call(self, method: str, **p):
        try: return self.c.post(f"{self.api}/{method}", json={k: v for k, v in p.items() if v is not None}).json()
        except Exception as e:
            log.warning("telegram %s failed: %s", method, e); return {}

    def send(self, chat_id: int, text: str, markup=None):
        self.call("sendMessage", chat_id=chat_id, text=text, reply_markup=markup, parse_mode="HTML")

    def handle(self, u: dict):
        if "callback_query" in u:
            q = u["callback_query"]; parts = (q.get("data") or "").split(":"); msg = "دسترسی ندارید"
            if len(parts) == 3 and parts[0] == "pay":
                with SessionLocal() as db:
                    p = db.get(Payment, int(parts[2]))
                    if p and services.can_decide(db, q["from"]["id"], p):
                        try:
                            p, user = services.decide_payment(db, p.id, parts[1])
                            msg = "✅ تأیید شد" if p.status == "ok" else "❌ رد شد"
                            send_to(user, "کیف پول شما شارژ شد ✅" if p.status == "ok" else "درخواست شارژ شما رد شد.")
                        except Exception as e: msg = f"خطا: {getattr(e, 'detail', e)}"
            self.call("answerCallbackQuery", callback_query_id=q["id"], text=msg)
            m = q.get("message") or {}
            if m: self.call("editMessageText", chat_id=m["chat"]["id"], message_id=m["message_id"], text=f"{m.get('text','')}\n\n{msg}")
            return
        m = u.get("message") or {}; text = (m.get("text") or "").strip()
        if not text or "from" not in m: return
        tg, chat = m["from"], m["chat"]["id"]
        with SessionLocal() as db:
            if text.startswith("/start"):
                param = text.split(maxsplit=1)[1] if " " in text else None
                nu = services.get_or_create_user(db, tg, param, self.agent_id)
                if getattr(nu, "_new", False): notify_admins("new_user", f"👤 کاربر جدید: {nu.full_name or nu.tg_id}")
                self.send(chat, services.welcome_text(db, tg.get("first_name", "")), app_button())
            elif text.startswith("/sub"):
                usr = services.get_or_create_user(db, tg, None, self.agent_id)
                self.send(chat, f"لینک اشتراک شما:\n<code>{usr.sub_url}</code>" if usr.sub_url else "هنوز اشتراکی ندارید.", app_button())
            elif text.startswith("/balance"):
                self.send(chat, f"موجودی: {services.get_or_create_user(db, tg, None, self.agent_id).balance:,} تومان", app_button("💼 کیف پول"))

    def send_document(self, chat_id: int, filename: str, data: bytes, caption: str = "") -> bool:
        try:
            r = self.c.post(f"{self.api}/sendDocument", data={"chat_id": chat_id, "caption": caption}, files={"document": (filename, data)}, timeout=120).json()
            return bool(r.get("ok"))
        except Exception as e:
            log.warning("sendDocument failed: %s", e); return False

    async def poll(self):
        if config.PUBLIC_URL:
            self.call("setChatMenuButton", menu_button={"type": "web_app", "text": "فروشگاه", "web_app": {"url": f"{config.PUBLIC_URL}/miniapp/"}})
        off = 0
        async with httpx.AsyncClient(timeout=45) as c:
            while not self.stop:
                try:
                    r = await c.get(f"{self.api}/getUpdates", params={"timeout": 30, "offset": off, "allowed_updates": '["message","callback_query"]'})
                    for u in r.json().get("result", []):
                        off = u["update_id"] + 1
                        try: await asyncio.to_thread(self.handle, u)
                        except Exception: log.exception("handler failed")
                except asyncio.CancelledError: raise
                except Exception:
                    log.exception("polling failed"); await asyncio.sleep(5)

def bot_for(user: User): return BOTS.get(user.agent_id) or BOTS.get(None)

def send_to(user: User, text: str, markup=None):
    b = bot_for(user)
    if b and user.tg_id > 0: b.send(user.tg_id, text, markup)

def app_button(label="🛍 باز کردن فروشگاه"):
    return {"inline_keyboard": [[{"text": label, "web_app": {"url": f"{config.PUBLIC_URL}/miniapp/"}}]]}

def notify_admins_payment(p, user: User):
    with SessionLocal() as db:
        if user.agent_id:
            ag = db.get(Agent, user.agent_id); targets = [db.get(User, ag.user_id).tg_id]
        else:
            if services.get_setting(db, "notify_payment") != "1": return
            targets = list(config.ADMIN_TG_IDS)
    b = bot_for(user)
    if not b: return
    kb = {"inline_keyboard": [[{"text": "✅ تأیید", "callback_data": f"pay:approve:{p.id}"}, {"text": "❌ رد", "callback_data": f"pay:reject:{p.id}"}]]}
    for t in targets:
        b.send(t, f"💳 درخواست شارژ #{p.id}\nکاربر: {user.full_name or user.tg_id}\nمبلغ: {p.amount:,} تومان\nپیگیری: {p.receipt or '—'}", kb)

def notify_admins(category: str, text: str):
    """اعلان به مدیران کل؛ هر دسته از تنظیمات (notify_<category>) قابل خاموش شدن است."""
    b = BOTS.get(None)
    if not b: return
    with SessionLocal() as db:
        if services.get_setting(db, f"notify_{category}") != "1": return
    for a in config.ADMIN_TG_IDS: b.send(a, text)

def alert_admins(text: str):
    """هشدار حیاتی (مثل شکست بکاپ)؛ به تنظیمات وابسته نیست."""
    b = BOTS.get(None)
    if b:
        for a in config.ADMIN_TG_IDS: b.send(a, text)

def verify_token(token: str) -> str:
    r = httpx.get(f"https://api.telegram.org/bot{token}/getMe", timeout=15).json()
    if not r.get("ok"): raise ValueError("getMe failed")
    return r["result"]["username"]

def spawn(b: Bot):
    if LOOP: TASKS.append(asyncio.run_coroutine_threadsafe(b.poll(), LOOP))

def register(agent: Agent):
    unregister(agent.id)
    b = Bot(agent.bot_token, agent.id, agent.name); BOTS[agent.id] = b; spawn(b)

def unregister(agent_id: int):
    b = BOTS.pop(agent_id, None)
    if b: b.stop = True

def start_all():
    global LOOP
    LOOP = asyncio.get_running_loop()
    if config.BOT_TOKEN and not config.BOT_TOKEN.startswith("123456"):
        m = Bot(config.BOT_TOKEN); BOTS[None] = m; spawn(m)
    else: log.warning("BOT_TOKEN تنظیم نشده؛ ربات اصلی غیرفعال است")
    with SessionLocal() as db:
        for a in db.scalars(select(Agent).where(Agent.active == True, Agent.bot_token != None)):  # noqa: E712,E711
            register(a)

def stop_all():
    for b in BOTS.values(): b.stop = True
    for f in TASKS: f.cancel()
