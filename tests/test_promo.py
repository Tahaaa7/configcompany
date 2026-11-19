from datetime import timedelta
from conftest import login, fund, db_user
from app.db import SessionLocal
from app.models import Offer, now

PRO = 2
def quote(client, h): return client.post("/shop/quote", json={"plan_id": PRO, "months": 1}, headers=h).json()

def test_discount_group_applies(client):
    admin, h = login(client, 999), login(client, 41)
    gid = client.post("/admin/discount-groups", json={"name": "vip", "percent": 10}, headers=admin).json()["id"]
    client.patch(f"/admin/users/{db_user(41).id}", json={"discount_group_id": gid}, headers=admin)
    q = quote(client, h)
    assert q["amount"] == 170000 and q["info"]["percent"] == 10      # ۱۸۹٬۰۰۰×۰٫۹ → ۱۷۰٬۰۰۰

def test_offer_beats_smaller_group_and_expires(client):
    admin, h = login(client, 999), login(client, 42)
    client.post("/admin/offers", json={"title": "bf", "percent": 20, "days": 3}, headers=admin)
    q = quote(client, h)
    assert q["amount"] == 151000 and q["info"]["offer"] == "bf"
    assert [o["title"] for o in client.get("/offers", headers=h).json()] == ["bf"]
    with SessionLocal() as db:
        for o in db.query(Offer): o.ends_at = now() - timedelta(days=1)
        db.commit()
    assert quote(client, h)["amount"] == 189000

def test_offer_audience_expired_only(client):
    admin, h = login(client, 999), login(client, 43)
    client.post("/admin/offers", json={"title": "winback", "percent": 50, "audience": "expired"}, headers=admin)
    assert quote(client, h)["amount"] == 189000                       # کاربر جدید مشمول نیست

def test_agent_cannot_assign_groups_or_manage_offers(client):
    admin = login(client, 999)
    client.post("/admin/agents", json={"tg_id": 500, "name": "A"}, headers=admin)
    ag = login(client, 500)
    assert client.post("/admin/offers", json={"title": "x", "percent": 5}, headers=ag).status_code == 403
    assert client.patch(f"/admin/users/{db_user(500).id}", json={"discount_group_id": 1}, headers=ag).status_code == 403

def test_content_public_read_admin_write(client):
    admin, h = login(client, 999), login(client, 44)
    assert client.post("/admin/content", json={"kind": "news", "title": "t", "body": "b"}, headers=admin).status_code == 200
    assert [c["title"] for c in client.get("/content").json()] == ["t"]
    assert client.post("/admin/content", json={"kind": "news", "title": "x"}, headers=h).status_code == 403
    assert client.post("/admin/content", json={"kind": "bad", "title": "x"}, headers=admin).status_code == 422

def test_analytics_totals_and_scope(client):
    admin, h = login(client, 999), login(client, 45); fund(45, 200000)
    client.post("/shop/buy", json={"plan_id": PRO, "months": 1}, headers=h)
    a = client.get("/admin/analytics?days=7", headers=admin).json()
    assert a["orders"] == 1 and a["revenue"] == 189000 and len(a["daily"]) == 8 and a["top_plans"][0]["orders"] == 1
    client.post("/admin/agents", json={"tg_id": 500, "name": "A"}, headers=admin)
    assert client.get("/admin/analytics?days=7", headers=login(client, 500)).json()["orders"] == 0
