import os, json, pathlib
from datetime import timedelta
from urllib.parse import urlencode

DB = "./test_configcompany.db"
os.environ.update(DATABASE_URL=f"sqlite:///{DB}", BOT_TOKEN="TESTTOKEN:abc", DEV_ALLOW_UNSIGNED="1",
                  ADMIN_TG_IDS="999", PANEL="mock", JWT_SECRET="test-secret", PUBLIC_URL="", ZARINPAL_MERCHANT="")
pathlib.Path(DB).unlink(missing_ok=True)

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from app.main import app
from app.db import engine, SessionLocal
from app.models import Base, User, now
from app import services, ratelimit
from app.seed import seed_plans

@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(engine); Base.metadata.create_all(engine)
    with SessionLocal() as db: seed_plans(db)
    ratelimit.reset()
    yield

@pytest.fixture
def client(): return TestClient(app)   # بدون with: lifespan (ربات و کران‌جاب) اجرا نمی‌شود

def login(client, tg, name="u", start=None):
    data = {"user": json.dumps({"id": tg, "first_name": name})}
    if start: data["start_param"] = start
    r = client.post("/auth/telegram", json={"init_data": urlencode(data)})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}

def fund(tg, amount):
    with SessionLocal() as db:
        u = db.scalar(select(User).where(User.tg_id == tg)); services.add_txn(db, u, amount, "topup", "test"); db.commit()

def db_user(tg):
    with SessionLocal() as db: return db.scalar(select(User).where(User.tg_id == tg))

def balance(client, h): return client.get("/wallet", headers=h).json()["balance"]

def expire(tg, days=1):
    with SessionLocal() as db:
        u = db.scalar(select(User).where(User.tg_id == tg)); u.expires_at = now() - timedelta(days=days); db.commit()
