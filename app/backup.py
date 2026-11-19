import os, sqlite3, subprocess, tempfile
from datetime import datetime, timezone
from . import config, bot

def make_backup() -> tuple[str, bytes]:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    url = config.DATABASE_URL
    if url.startswith("sqlite"):
        path = url.split("///", 1)[1]
        with tempfile.TemporaryDirectory() as d:
            dst = os.path.join(d, "b.db")
            src, out = sqlite3.connect(path), sqlite3.connect(dst)
            src.backup(out); out.close(); src.close()
            with open(dst, "rb") as f: return f"configcompany-{stamp}.sqlite", f.read()
    p = subprocess.run(["pg_dump", "--no-owner", "-Fc", url.replace("postgresql+psycopg://", "postgresql://", 1)], capture_output=True, timeout=300)
    if p.returncode: raise RuntimeError(p.stderr.decode(errors="replace")[:300])
    return f"configcompany-{stamp}.dump", p.stdout   # بازیابی: pg_restore --clean -d <url> فایل.dump

def do_backup() -> int:
    name, data = make_backup()
    b = bot.BOTS.get(None)
    if not b: raise RuntimeError("ربات اصلی فعال نیست")
    if len(data) > 49 * 1024 * 1024: raise RuntimeError("حجم بکاپ از حد مجاز تلگرام (۵۰MB) بیشتر است")
    sent = False
    for a in config.ADMIN_TG_IDS: sent = b.send_document(a, name, data, f"💾 بکاپ دیتابیس · {len(data) // 1024} KB") or sent
    if not sent: raise RuntimeError("ارسال به تلگرام ناموفق بود")
    return len(data)
