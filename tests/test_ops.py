from conftest import login, fund, balance

PRO = 2

def test_settings_expose_ops_keys(client):
    cfg = client.get("/admin/settings", headers=login(client, 999)).json()
    for k in ("maintenance", "notify_payment", "anomaly_gb", "backup_enabled", "backup_hour"): assert k in cfg

def test_manual_maintenance_blocks_purchases_but_not_quotes(client):
    admin = login(client, 999); h = login(client, 31); fund(31, 200000)
    client.put("/admin/settings", json={"maintenance": "1"}, headers=admin)
    assert client.get("/me", headers=h).json()["maintenance"] is True
    assert client.post("/shop/buy", json={"plan_id": PRO, "months": 1}, headers=h).status_code == 503
    assert client.post("/wallet/topup", json={"amount": 50000}, headers=h).status_code == 503
    assert client.post("/me/trial", headers=h).status_code == 503
    assert client.post("/shop/quote", json={"plan_id": PRO, "months": 1}, headers=h).status_code == 200
    assert balance(client, h) == 200000
    client.put("/admin/settings", json={"maintenance": "0"}, headers=admin)
    assert client.post("/shop/buy", json={"plan_id": PRO, "months": 1}, headers=h).status_code == 200

def test_panel_down_triggers_automatic_maintenance(client, monkeypatch):
    from app import state
    monkeypatch.setattr(state, "panel_down", True)
    h = login(client, 32); fund(32, 200000)
    assert client.post("/shop/buy", json={"plan_id": PRO, "months": 1}, headers=h).status_code == 503

def test_health_tick_needs_two_failures_then_recovers(client, monkeypatch):
    from app import jobs, state
    class P:
        ok = False
        def ping(self): return self.ok
    p = P()
    monkeypatch.setattr(jobs, "get_panel", lambda: p)
    monkeypatch.setattr(state, "panel_down", False); monkeypatch.setattr(state, "fails", 0)
    jobs.health_tick(); assert state.panel_down is False       # یک شکست کافی نیست
    jobs.health_tick(); assert state.panel_down is True
    p.ok = True; jobs.health_tick(); assert state.panel_down is False

def test_detect_anomalies():
    from app.jobs import detect_anomalies
    prev = {"a": 10.0, "b": 5.0, "c": 1.0}
    cur = {"a": 45.0, "b": 6.0, "c": 0.5, "new": 999.0}
    assert detect_anomalies(prev, cur, 20) == [("a", 35.0)]     # کاربر جدید baseline ندارد؛ ریست مصرف (کاهش) نادیده

def test_sqlite_backup_is_valid_file(client):
    from app import backup
    name, data = backup.make_backup()
    assert name.endswith(".sqlite") and data[:15] == b"SQLite format 3"

def test_manual_backup_needs_master_and_bot(client):
    assert client.post("/admin/backup", headers=login(client, 33)).status_code == 403
    assert client.post("/admin/backup", headers=login(client, 999)).status_code == 502    # در تست ربات اصلی فعال نیست

def test_notify_admins_without_bot_is_noop(client):
    from app import bot
    bot.notify_admins("payment", "x"); bot.alert_admins("x")
