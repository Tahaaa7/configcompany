import httpx
from ..config import PANEL_URL, PANEL_USERNAME, PANEL_PASSWORD
from .base import Panel, PanelUser

GB = 1024 ** 3

class Marzban(Panel):
    """سازگار با Marzban / PasarGuard (مسیرها را با نسخه خودتان تطبیق دهید)."""
    def __init__(self):
        self.c = httpx.Client(base_url=PANEL_URL, timeout=20)
        t = self.c.post("/api/admin/token", data={"username": PANEL_USERNAME, "password": PANEL_PASSWORD})
        t.raise_for_status()
        self.c.headers["Authorization"] = f"Bearer {t.json()['access_token']}"

    def _parse(self, d):
        return PanelUser(d["username"], d.get("subscription_url", ""), (d.get("used_traffic") or 0) / GB)

    def get(self, username):
        r = self.c.get(f"/api/user/{username}")
        return self._parse(r.json()) if r.status_code == 200 else None

    def upsert(self, username, traffic_gb, expire_at, devices=1, disabled=False):
        body = {"status": "disabled" if disabled else "active", "data_limit": traffic_gb * GB,
                "expire": int(expire_at.timestamp()), "data_limit_reset_strategy": "no_reset"}
        if self.get(username):
            r = self.c.put(f"/api/user/{username}", json=body)
        else:
            r = self.c.post("/api/user", json={"username": username, "proxies": {"vless": {}}, "inbounds": {}, **body})
        r.raise_for_status()
        return self._parse(r.json())

    def reset_usage(self, username):
        self.c.post(f"/api/user/{username}/reset").raise_for_status()

    def delete(self, username):
        self.c.delete(f"/api/user/{username}")

    def ping(self):
        try: return self.c.get("/api/system").status_code < 500
        except Exception: return False

    def list_usage(self):
        out, off = {}, 0
        while True:
            r = self.c.get("/api/users", params={"offset": off, "limit": 500}); r.raise_for_status()
            d = r.json(); us = d.get("users", [])
            for u in us: out[u["username"]] = (u.get("used_traffic") or 0) / GB
            off += len(us)
            if not us or off >= d.get("total", 0): return out
