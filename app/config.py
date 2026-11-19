import os

def _list(v): return [x.strip() for x in v.split(",") if x.strip()]

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./configcompany.db")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret-change-me")
ADMIN_TG_IDS = {int(x) for x in _list(os.getenv("ADMIN_TG_IDS", "")) if x.isdigit()}
PANEL = os.getenv("PANEL", "mock")
PANEL_URL = os.getenv("PANEL_URL", "").rstrip("/")
PANEL_TOKEN = os.getenv("PANEL_TOKEN", "")
PANEL_USERNAME = os.getenv("PANEL_USERNAME", "")
PANEL_PASSWORD = os.getenv("PANEL_PASSWORD", "")
SQUADS = _list(os.getenv("REMNAWAVE_SQUAD_UUIDS", ""))
CORS = _list(os.getenv("CORS_ORIGINS", "*")) or ["*"]
DEV_ALLOW_UNSIGNED = os.getenv("DEV_ALLOW_UNSIGNED", "0") == "1"
DISCOUNTS = {1: 0.0, 3: 0.08, 6: 0.15, 12: 0.25}   # تخفیف دوره
REF_TIERS = [(10, 8), (20, 12), (10**9, 18)]        # (تا این تعداد دعوت، درصد کمیسیون)
TRIAL_GB, TRIAL_DAYS = 2, 1
BOT_USERNAME = os.getenv("BOT_USERNAME", "")
SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "")
PUBLIC_URL = os.getenv("PUBLIC_URL", "").rstrip("/")   # مثل https://vpn.example.com
ZARINPAL_MERCHANT = os.getenv("ZARINPAL_MERCHANT", "")
# تنظیمات قابل ویرایش از پنل (مقدار پیش‌فرض؛ مقدار ذخیره‌شده در دیتابیس اولویت دارد)
DEFAULT_SETTINGS = {"grace_enabled": "1", "grace_days": "3", "trial_convert_plan_id": "0", "trial_convert_months": "1", "ref_l2": "3", "ref_l3": "1",
                    "maintenance": "0", "notify_payment": "1", "notify_new_user": "0", "notify_panel": "1", "notify_anomaly": "1",
                    "anomaly_gb": "20", "backup_enabled": "1", "backup_hour": "3"}
TRUST_PROXY = os.getenv("TRUST_PROXY", "0") == "1"   # فقط پشت reverse proxy مورد اعتماد روشن شود
USE_ALEMBIC = os.getenv("USE_ALEMBIC", "0") == "1"
