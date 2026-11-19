import hashlib, hmac, json, time
from urllib.parse import urlencode, parse_qsl

def sign(token, fields, auth_date=None):
    d = dict(fields); d["auth_date"] = str(auth_date or int(time.time()))
    check = "\n".join(f"{k}={v}" for k, v in sorted(d.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    d["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(d)

USER = {"user": json.dumps({"id": 7, "first_name": "a"})}

def test_valid_signature_accepted(client):
    assert client.post("/auth/telegram", json={"init_data": sign("TESTTOKEN:abc", USER)}).status_code == 200

def test_tampered_payload_rejected(client):
    d = dict(parse_qsl(sign("TESTTOKEN:abc", USER))); d["user"] = json.dumps({"id": 8, "first_name": "evil"})
    assert client.post("/auth/telegram", json={"init_data": urlencode(d)}).status_code == 401

def test_wrong_bot_token_rejected(client):
    assert client.post("/auth/telegram", json={"init_data": sign("OTHER:token", USER)}).status_code == 401

def test_expired_init_data_rejected(client):
    old = int(time.time()) - 3 * 86400
    assert client.post("/auth/telegram", json={"init_data": sign("TESTTOKEN:abc", USER, old)}).status_code == 401

def test_admin_endpoints_need_auth_and_role(client):
    from conftest import login
    assert client.get("/admin/stats").status_code == 401
    assert client.get("/admin/stats", headers=login(client, 111)).status_code == 403
    assert client.get("/admin/stats", headers=login(client, 999)).status_code == 200

def test_rate_limit_on_auth(client):
    from app import ratelimit
    old = ratelimit.LIMITS["auth"]; ratelimit.LIMITS["auth"] = (3, 60)
    try:
        codes = [client.post("/auth/telegram", json={"init_data": "user=%7B%22id%22%3A5%7D"}).status_code for _ in range(5)]
    finally: ratelimit.LIMITS["auth"] = old
    assert codes[-1] == 429
