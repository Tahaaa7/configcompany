from conftest import login, fund, balance

PRO = 2

def _code(client, h): return client.get("/referral", headers=h).json()["code"]

def test_level1_commission(client):
    a = login(client, 1001); b = login(client, 1002, start=f"ref_{_code(client, a)}")
    fund(1002, 200000)
    client.post("/shop/buy", json={"plan_id": PRO, "months": 1}, headers=b)
    assert balance(client, a) == 15120                         # ۸٪ از ۱۸۹٬۰۰۰

def test_three_level_chain(client):
    a = login(client, 1101)
    b = login(client, 1102, start=f"ref_{_code(client, a)}")
    c = login(client, 1103, start=f"ref_{_code(client, b)}")
    fund(1102, 200000); fund(1103, 200000)
    client.post("/shop/buy", json={"plan_id": PRO, "months": 1}, headers=b)
    client.post("/shop/buy", json={"plan_id": PRO, "months": 1}, headers=c)
    assert balance(client, b) == 11000 + 15120                 # خرید خودش + کمیسیون سطح ۱ از C
    assert balance(client, a) == 15120 + 5670                  # سطح ۱ از B + سطح ۲ (۳٪) از C
    net = client.get("/referral/network", headers=a).json()
    assert net["counts"][:2] == [1, 1]

def test_self_referral_ignored(client):
    a = login(client, 1201)
    assert client.get("/referral", headers=a).json()["invited"] == 0

def test_unknown_ref_code_is_harmless(client):
    b = login(client, 1301, start="ref_doesnotexist")
    assert client.get("/me", headers=b).status_code == 200
