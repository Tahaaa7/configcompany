from conftest import login, fund, balance, db_user, expire

PRO = 2  # «حرفه‌ای» ۱۸۹٬۰۰۰ تومان/ماه

def test_quote_applies_duration_discount(client):
    h = login(client, 1)
    q = client.post("/shop/quote", json={"plan_id": PRO, "months": 3}, headers=h).json()
    assert q["amount"] == 522000          # 189000×3×0.92 → گرد به هزار
    assert client.post("/shop/quote", json={"plan_id": PRO, "months": 1}, headers=h).json()["amount"] == 189000
    assert client.post("/shop/quote", json={"plan_id": PRO, "months": 2}, headers=h).status_code == 400

def test_coupon_flow(client):
    admin = login(client, 999)
    assert client.post("/admin/coupons", json={"code": "test10", "percent": 10, "max_uses": 1}, headers=admin).status_code == 200
    h = login(client, 2); fund(2, 500000)
    q = client.post("/shop/quote", json={"plan_id": PRO, "months": 1, "coupon": "TEST10"}, headers=h).json()
    assert q["amount"] == 170000
    assert client.post("/shop/buy", json={"plan_id": PRO, "months": 1, "coupon": "TEST10"}, headers=h).status_code == 200
    h2 = login(client, 3)
    assert client.post("/shop/quote", json={"plan_id": PRO, "months": 1, "coupon": "TEST10"}, headers=h2).status_code == 400  # ظرفیت تمام شد
    assert client.post("/shop/quote", json={"plan_id": PRO, "months": 1, "coupon": "NOPE"}, headers=h2).status_code == 400

def test_buy_success_and_state(client):
    h = login(client, 4); fund(4, 200000)
    r = client.post("/shop/buy", json={"plan_id": PRO, "months": 1}, headers=h)
    assert r.status_code == 200 and r.json()["paid"] == 189000
    me = client.get("/me", headers=h).json()
    assert me["balance"] == 11000 and me["subscription"]["active"] and me["subscription"]["days_left"] >= 29
    assert me["subscription"]["sub_url"].startswith("https://sub.example.com/")

def test_buy_with_insufficient_balance(client):
    h = login(client, 5); fund(5, 1000)
    assert client.post("/shop/buy", json={"plan_id": PRO, "months": 1}, headers=h).status_code == 402
    assert balance(client, h) == 1000

def test_panel_failure_does_not_charge(client, monkeypatch):
    from app import services
    class Boom:
        def upsert(self, *a, **k): raise RuntimeError("panel down")
    monkeypatch.setattr(services, "get_panel", lambda: Boom())
    h = login(client, 6); fund(6, 200000)
    assert client.post("/shop/buy", json={"plan_id": PRO, "months": 1}, headers=h).status_code == 502
    assert balance(client, h) == 200000

def test_trial_only_once(client):
    h = login(client, 7)
    assert client.post("/me/trial", headers=h).status_code == 200
    assert client.post("/me/trial", headers=h).status_code == 400

def test_gift_code_single_use(client):
    admin = login(client, 999)
    client.post("/admin/gift-codes", json={"code": "g1", "amount": 50000}, headers=admin)
    a, b = login(client, 8), login(client, 9)
    assert client.post("/wallet/gift", json={"code": "G1"}, headers=a).status_code == 200
    assert balance(client, a) == 50000
    assert client.post("/wallet/gift", json={"code": "G1"}, headers=b).status_code == 400

def test_grace_access(client):
    h = login(client, 10); fund(10, 200000)
    client.post("/shop/buy", json={"plan_id": PRO, "months": 1}, headers=h)
    expire(10)
    me = client.get("/me", headers=h).json()
    assert not me["subscription"]["active"] and me["grace_available"]
    assert client.post("/me/grace", headers=h).status_code == 200
    assert client.get("/me", headers=h).json()["subscription"]["active"]
    assert client.post("/me/grace", headers=h).status_code == 400   # فقط یک بار

def test_grace_can_be_disabled_by_admin(client):
    admin = login(client, 999)
    assert client.put("/admin/settings", json={"grace_enabled": "0"}, headers=admin).status_code == 200
    h = login(client, 11); fund(11, 200000)
    client.post("/shop/buy", json={"plan_id": PRO, "months": 1}, headers=h); expire(11)
    assert client.post("/me/grace", headers=h).status_code == 400

def test_settings_reject_non_numeric(client):
    assert client.put("/admin/settings", json={"grace_days": "abc"}, headers=login(client, 999)).status_code == 400
