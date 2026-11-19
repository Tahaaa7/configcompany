import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from . import config
from .db import engine, SessionLocal
from .models import Base
from .routers_user import r as user_router
from .routers_admin import r as admin_router
from .routers_pay import r as pay_router
from . import bot, jobs, ratelimit
from .seed import seed_plans, seed_content

@asynccontextmanager
async def lifespan(app):
    if not config.USE_ALEMBIC: Base.metadata.create_all(engine)   # با Alembic: alembic upgrade head
    with SessionLocal() as db: seed_plans(db); seed_content(db)
    bot.start_all()
    tasks = [asyncio.create_task(jobs.loop()), asyncio.create_task(jobs.health_loop())]
    yield
    for t in tasks: t.cancel()
    bot.stop_all()

app = FastAPI(title="ConfigCompany API", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=config.CORS, allow_methods=["*"], allow_headers=["*"])
@app.middleware("http")
async def rate_limit(request: Request, call_next):
    path = request.url.path
    if path.startswith(("/miniapp", "/admin-ui", "/health", "/docs", "/openapi")): return await call_next(request)
    ip = (request.headers.get("x-forwarded-for", "").split(",")[0].strip() if config.TRUST_PROXY else "") or (request.client.host if request.client else "?")
    if not ratelimit.allow(ip, "auth" if path.startswith(("/auth", "/pay")) else "default"):
        return JSONResponse({"detail": "تعداد درخواست‌ها زیاد است؛ کمی بعد دوباره تلاش کنید"}, status_code=429, headers={"Retry-After": "60"})
    return await call_next(request)

app.include_router(user_router)
app.include_router(admin_router)
app.include_router(pay_router)

@app.get("/health")
def health(): return {"ok": True}

@app.get("/public/config")
def public_config(): return {"bot": config.BOT_USERNAME, "support": config.SUPPORT_USERNAME, "pay_online": bool(config.ZARINPAL_MERCHANT and config.PUBLIC_URL)}

_web = Path(__file__).resolve().parent.parent / "web"
if _web.exists():
    app.mount("/miniapp", StaticFiles(directory=_web / "miniapp", html=True))
    app.mount("/admin-ui", StaticFiles(directory=_web / "admin", html=True))
    app.mount("/", StaticFiles(directory=_web / "landing", html=True))   # باید آخرین mount باشد
