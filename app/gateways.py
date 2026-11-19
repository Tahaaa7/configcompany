import httpx
from .config import ZARINPAL_MERCHANT

ZP = "https://payment.zarinpal.com/pg/v4/payment"

def zp_request(amount_toman: int, desc: str, callback: str) -> str:
    r = httpx.post(f"{ZP}/request.json", timeout=20, json={"merchant_id": ZARINPAL_MERCHANT, "amount": amount_toman,
                   "currency": "IRT", "description": desc, "callback_url": callback})
    d = r.json().get("data") or {}
    if d.get("code") != 100: raise RuntimeError(f"zarinpal code={d.get('code')}")
    return d["authority"]

def zp_start_url(authority: str) -> str: return f"https://payment.zarinpal.com/pg/StartPay/{authority}"

def zp_verify(authority: str, amount_toman: int) -> bool:
    """خطای شبکه = استثنا (پرداخت pending می‌ماند)؛ کد ۱۰۰/۱۰۱ = موفق."""
    r = httpx.post(f"{ZP}/verify.json", timeout=20, json={"merchant_id": ZARINPAL_MERCHANT, "amount": amount_toman,
                   "currency": "IRT", "authority": authority})
    return (r.json().get("data") or {}).get("code") in (100, 101)
