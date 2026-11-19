import hashlib, hmac, json, time
from urllib.parse import parse_qsl
import jwt
from fastapi import HTTPException
from .config import JWT_SECRET, DEV_ALLOW_UNSIGNED

def verify_init_data(init_data: str, tokens: list, max_age: int = 86400) -> dict:
    """tokens: [(agent_id|None, bot_token)]؛ initData با توکن همان رباتی که مینی‌اپ را باز کرده امضا شده است."""
    data = dict(parse_qsl(init_data, keep_blank_values=True))
    got = data.pop("hash", "")
    if DEV_ALLOW_UNSIGNED and not got:
        return {"user": json.loads(data.get("user", '{"id":1,"first_name":"dev"}')), "start_param": data.get("start_param"), "agent_id": None}
    check = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    for agent_id, token in tokens:
        if not token: continue
        secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
        if got and hmac.compare_digest(hmac.new(secret, check.encode(), hashlib.sha256).hexdigest(), got):
            if time.time() - int(data.get("auth_date", 0)) > max_age: raise HTTPException(401, "initData منقضی شده است")
            return {"user": json.loads(data["user"]), "start_param": data.get("start_param"), "agent_id": agent_id}
    raise HTTPException(401, "initData نامعتبر است")

def make_token(user_id: int) -> str:
    return jwt.encode({"sub": str(user_id), "exp": int(time.time()) + 7 * 86400}, JWT_SECRET, "HS256")

def read_token(token: str) -> int:
    try: return int(jwt.decode(token, JWT_SECRET, ["HS256"])["sub"])
    except Exception: raise HTTPException(401, "توکن نامعتبر است")
