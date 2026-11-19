from dataclasses import dataclass
from datetime import datetime

@dataclass
class PanelUser:
    username: str
    sub_url: str
    used_gb: float = 0.0

class Panel:
    """رابط مشترک پنل‌ها؛ برای پنل جدید فقط این دو متد را پیاده کنید."""
    def upsert(self, username: str, traffic_gb: int, expire_at: datetime,
               devices: int = 1, disabled: bool = False) -> PanelUser: raise NotImplementedError
    def get(self, username: str) -> PanelUser | None: raise NotImplementedError
    def reset_usage(self, username: str) -> None: pass
    def delete(self, username: str) -> None: pass
    def ping(self) -> bool: return True
    def list_usage(self) -> dict: return {}   # {username: used_gb}

class MockPanel(Panel):
    """برای توسعه بدون پنل واقعی."""
    _db: dict = {}
    def upsert(self, username, traffic_gb, expire_at, devices=1, disabled=False):
        u = self._db.get(username) or PanelUser(username, f"https://sub.example.com/{username}")
        self._db[username] = u
        return u
    def get(self, username): return self._db.get(username)
    def reset_usage(self, username):
        if username in self._db: self._db[username].used_gb = 0
    def delete(self, username): self._db.pop(username, None)
    def list_usage(self): return {k: v.used_gb for k, v in self._db.items()}
