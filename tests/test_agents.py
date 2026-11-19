from sqlalchemy import select
from conftest import login, fund, db_user
from app.db import SessionLocal
from app.models import User, Agent

PRO = 2

def make_agent(client, tg=500, balance=300000, discount=20, commission=10):
    admin = login(client, 999)
    r = client.post("/admin/agents", json={"tg_id": tg, "name": "A1", "discount_percent": discount, "commission_percent": commission, "balance": balance}, headers=admin)
    assert r.status_code == 200, r.text
    return admin, login(client, tg)

def test_agent_role_and_balance(client):
    _, ag = make_agent(client)
    me = client.get("/admin/me", headers=ag).json()
    assert me["role"] == "agent" and me["balance"] == 300000

def test_agent_manual_user_uses_wholesale_price(client):
    _, ag = make_agent(client)
    r = client.post("/admin/users", json={"name": "cust", "plan_id": PRO, "days": 30}, headers=ag)
    assert r.status_code == 200 and r.json()["sub_url"]
    assert client.get("/admin/me", headers=ag).json()["balance"] == 300000 - 151000   # ۱۸۹٬۰۰۰×۰٫۸ → ۱۵۱٬۰۰۰

def test_agent_cannot_overspend(client):
    _, ag = make_agent(client, balance=1000)
    assert client.post("/admin/users", json={"name": "x", "plan_id": PRO, "days": 30}, headers=ag).status_code == 402

def test_agent_sees_only_own_users(client):
    admin, ag = make_agent(client)
    login(client, 600)                                      # کاربر مدیر کل
    client.post("/admin/users", json={"name": "cust", "plan_id": PRO, "days": 30}, headers=ag)
    mine = client.get("/admin/users", headers=ag).json()
    assert [u["name"] for u in mine] == ["cust"]
    assert len(client.get("/admin/users", headers=admin).json()) >= 3
    other = db_user(600)
    assert client.patch(f"/admin/users/{other.id}", json={"disabled": True}, headers=ag).status_code == 404
    assert client.delete(f"/admin/users/{other.id}", headers=ag).status_code == 404

def test_agent_cannot_use_master_endpoints(client):
    _, ag = make_agent(client)
    assert client.post("/admin/plans", json={"name": "x", "price_month": 1}, headers=ag).status_code == 403
    assert client.get("/admin/agents", headers=ag).status_code == 403
    assert client.put("/admin/settings", json={"grace_days": "5"}, headers=ag).status_code == 403

def test_commission_on_agent_customer_purchase(client):
    _, ag = make_agent(client)
    cust = login(client, 700)
    with SessionLocal() as db:
        a = db.scalar(select(Agent)); u = db.scalar(select(User).where(User.tg_id == 700)); u.agent_id = a.id; db.commit()
    fund(700, 200000)
    assert client.post("/shop/buy", json={"plan_id": PRO, "months": 1}, headers=cust).status_code == 200
    assert client.get("/admin/me", headers=ag).json()["balance"] == 300000 + 18900          # ۱۰٪ از ۱۸۹٬۰۰۰

def test_agent_approves_only_own_customers_payments(client):
    admin, ag = make_agent(client)
    mine, other = login(client, 800), login(client, 801)
    with SessionLocal() as db:
        a = db.scalar(select(Agent)); u = db.scalar(select(User).where(User.tg_id == 800)); u.agent_id = a.id; db.commit()
    client.post("/wallet/topup", json={"amount": 50000, "receipt": "r1"}, headers=mine)
    client.post("/wallet/topup", json={"amount": 60000, "receipt": "r2"}, headers=other)
    pend = client.get("/admin/payments", headers=ag).json()
    assert len(pend) == 1 and pend[0]["amount"] == 50000
    assert client.post(f"/admin/payments/{pend[0]['id']}/approve", headers=ag).status_code == 200
    assert client.get("/wallet", headers=mine).json()["balance"] == 50000
    other_p = [p for p in client.get("/admin/payments", headers=admin).json() if p["amount"] == 60000][0]
    assert client.post(f"/admin/payments/{other_p['id']}/approve", headers=ag).status_code == 404

def test_master_manual_user_and_delete(client):
    admin = login(client, 999)
    r = client.post("/admin/users", json={"name": "free", "plan_id": PRO, "days": 45, "traffic_gb": 10}, headers=admin)
    assert r.status_code == 200
    uid = r.json()["id"]
    assert client.delete(f"/admin/users/{uid}", headers=admin).status_code == 200
    row = [u for u in client.get("/admin/users", headers=admin).json() if u["id"] == uid][0]
    assert row["disabled"] and row["sub_url"] is None

def test_card_topup_flow(client):
    admin = login(client, 999); h = login(client, 900)
    assert client.post("/wallet/topup", json={"amount": 50000, "receipt": "123"}, headers=h).json()["status"] == "pending"
    assert client.post("/admin/payments/1/approve", headers=h).status_code == 403     # کاربر عادی نمی‌تواند تأیید کند
    assert client.post("/admin/payments/1/approve", headers=admin).status_code == 200
    assert client.post("/admin/payments/1/approve", headers=admin).status_code in (400, 404)  # تأیید دوباره ممکن نیست
    assert client.get("/wallet", headers=h).json()["balance"] == 50000
