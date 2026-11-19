import httpx
from ..config import PANEL_URL, PANEL_TOKEN, SQUADS
from .base import Panel, PanelUser

GB = 1024 ** 3

class Remnawave(Panel):
    """مسیرها و فیلدها بر اساس API ریم‌ناوه؛ قبل از استفاده با نسخه پنل خودتان (/api/docs) تطبیق دهید."""
    def __init__(self):
        self.c = httpx.Client(base_url=PANEL_URL, headers={"Authorization": f"Bearer {PANEL_TOKEN}"}, timeout=20)

    def _parse(self, d) -> PanelUser:
        return PanelUser(d["username"], d.get("subscriptionUrl", ""), (d.get("usedTrafficBytes") or 0) / GB)

    def get(self, username):
        r = self.c.get(f"/api/users/by-username/{username}")
        return self._parse(r.json()["response"]) if r.status_code == 200 else None

    def upsert(self, username, traffic_gb, expire_at, devices=1, disabled=False):
        body = {"status": "DISABLED" if disabled else "ACTIVE",
                "trafficLimitBytes": traffic_gb * GB, "trafficLimitStrategy": "NO_RESET",
                "expireAt": expire_at.strftime("%Y-%m-%dT%H:%M:%S.000Z"), "hwidDeviceLimit": devices}
        if SQUADS: body["activeInternalSquads"] = SQUADS
        r = self.c.get(f"/api/users/by-username/{username}")
        if r.status_code == 200:
            r = self.c.patch("/api/users", json={"uuid": r.json()["response"]["uuid"], **body})
        else:
            r = self.c.post("/api/users", json={"username": username, **body})
        r.raise_for_status()
        return self._parse(r.json()["response"])

    def reset_usage(self, username):
        r = self.c.get(f"/api/users/by-username/{username}")
        if r.status_code == 200:
            self.c.post(f"/api/users/{r.json()['response']['uuid']}/actions/reset-traffic").raise_for_status()

    def delete(self, username):
        r = self.c.get(f"/api/users/by-username/{username}")
        if r.status_code == 200: self.c.delete(f"/api/users/{r.json()['response']['uuid']}").raise_for_status()

    def ping(self):
        try: return self.c.get("/api/users/by-username/__ping__").status_code < 500
        except Exception: return False

    def list_usage(self):
        out, start = {}, 0
        while True:
            r = self.c.get("/api/users", params={"size": 500, "start": start}); r.raise_for_status()
            resp = r.json()["response"]; users = resp.get("users", [])
            for u in users: out[u["username"]] = (u.get("usedTrafficBytes") or 0) / GB
            start += len(users)
            if not users or start >= resp.get("total", 0): return out
