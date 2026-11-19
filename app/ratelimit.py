import time
from collections import defaultdict, deque

# bucket → (حداکثر درخواست، بازه به ثانیه). ورود و پرداخت سخت‌گیرانه‌تر است.
LIMITS = {"auth": (20, 60), "default": (240, 60)}
_hits: dict = defaultdict(deque)

def allow(ip: str, bucket: str) -> bool:
    limit, window = LIMITS[bucket]
    now = time.monotonic(); q = _hits[(ip, bucket)]
    while q and now - q[0] > window: q.popleft()
    if len(q) >= limit: return False
    q.append(now)
    if len(_hits) > 20000:   # جلوگیری از رشد حافظه
        for k in [k for k, v in _hits.items() if not v or now - v[-1] > 120]: _hits.pop(k, None)
    return True

def reset(): _hits.clear()
