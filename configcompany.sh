#!/usr/bin/env bash
# ConfigCompany management CLI  (نصب‌شده با نام: configcompany)
APP_DIR=/opt/configcompany
cd "$APP_DIR" 2>/dev/null || { echo "ConfigCompany در $APP_DIR نصب نیست"; exit 1; }
R='\033[31m'; G='\033[32m'; Y='\033[33m'; N='\033[0m'
dc(){ docker compose "$@"; }
envget(){ grep -E "^$1=" .env | head -1 | cut -d= -f2-; }
confirm(){ read -rp "$1 [y/N] " a; [[ "$a" =~ ^[yY]$ ]]; }

cmd_status(){ dc ps; echo; echo "دامنه: https://$(envget DOMAIN)   پنل: https://$(envget DOMAIN)/admin-ui/   مینی‌اپ: https://$(envget DOMAIN)/miniapp/"; }
cmd_log(){ dc logs -f --tail=100 "${1:-api}"; }
cmd_backup(){
  mkdir -p backups; f="backups/cc-$(date +%Y%m%d-%H%M%S).dump"
  if dc exec -T db pg_dump -U configcompany -Fc configcompany > "$f" 2>/dev/null && [ -s "$f" ]; then
    echo -e "${G}بکاپ ساخته شد:${N} $APP_DIR/$f"; ls -1t backups/*.dump | tail -n +15 | xargs -r rm -f
  else rm -f "$f"; echo -e "${R}بکاپ ناموفق بود${N}"; return 1; fi
}
cmd_restore(){
  f="${1:-}"; [ -f "$f" ] || { ls -1t backups/*.dump 2>/dev/null | head; read -rp "مسیر فایل .dump: " f; }
  [ -f "$f" ] || { echo "فایل پیدا نشد"; return 1; }
  confirm "دیتابیس فعلی با این بکاپ جایگزین می‌شود. ادامه؟" || return 0
  cmd_backup || true
  dc stop api && dc exec -T db pg_restore --clean --if-exists -U configcompany -d configcompany < "$f"; dc start api; echo -e "${G}بازیابی انجام شد${N}"
}
cmd_token(){ id="${1:-$(envget ADMIN_TG_IDS | cut -d, -f1)}"; dc exec -T api python -m app.cli token "$id"; }
cmd_settings(){ ${EDITOR:-$(command -v nano || echo vi)} .env && dc up -d --force-recreate api caddy && echo -e "${G}اعمال شد${N}"; }
cmd_domain(){
  read -rp "دامنه‌ی جدید: " d; [ -n "$d" ] || return 1
  sed -i "s|^DOMAIN=.*|DOMAIN=$d|; s|^PUBLIC_URL=.*|PUBLIC_URL=https://$d|; s|^CORS_ORIGINS=.*|CORS_ORIGINS=https://$d|" .env
  dc up -d --force-recreate api caddy; echo "منو و مینی‌اپ را در BotFather روی https://$d/miniapp/ بگذارید."
}
cmd_update(){
  src="${1:-}"; repo="$(envget CC_REPO)"; br="$(envget CC_BRANCH)"; tmp="$(mktemp -d)"
  cmd_backup || confirm "بکاپ ناموفق بود؛ باز هم ادامه بدهم؟" || return 1
  if [ -n "$src" ] && [ -d "$src" ]; then cp -a "$src" "$tmp/src"
  elif [ -n "$repo" ] && [[ "$repo" != *YOUR_USER* ]]; then git clone -q --depth 1 -b "${br:-main}" "$repo" "$tmp/src" || { echo "دریافت ناموفق"; return 1; }
  else echo "منبع آپدیت مشخص نیست: configcompany update /مسیر/پوشه‌ی/جدید"; return 1; fi
  (cd "$tmp/src" && tar cf - --exclude=.env --exclude=backups --exclude=.git .) | tar xf -; rm -rf "$tmp"
  install -m 755 configcompany.sh /usr/local/bin/configcompany 2>/dev/null
  dc up -d --build && docker image prune -f >/dev/null; echo -e "${G}آپدیت شد${N}"
}
cmd_uninstall(){
  echo -e "${R}همه‌ی سرویس‌ها و دیتابیس حذف می‌شود!${N}"; read -rp "برای تأیید DELETE را تایپ کنید: " a; [ "$a" = DELETE ] || return 0
  cmd_backup >/dev/null 2>&1; mkdir -p /root/configcompany-last-backup; cp -f backups/*.dump /root/configcompany-last-backup/ 2>/dev/null
  dc down -v; rm -f /etc/cron.d/configcompany-backup /usr/local/bin/configcompany; cd /; rm -rf "$APP_DIR"
  echo "حذف شد. آخرین بکاپ: /root/configcompany-last-backup/"
}
cmd_export(){  # بکاپ + ارسال به تلگرام مدیر (مثل «خروجی دیتابیس» میرزا)
  cmd_backup || return 1; f="$(ls -1t backups/*.dump | head -1)"; t="$(envget BOT_TOKEN)"; a="$(envget ADMIN_TG_IDS | cut -d, -f1)"
  if curl -fsS -F "chat_id=$a" -F "document=@$f" -F "caption=💾 ConfigCompany backup" "https://api.telegram.org/bot$t/sendDocument" >/dev/null; then echo -e "${G}فایل به تلگرام شما ارسال شد${N}"
  else echo -e "${Y}ارسال به تلگرام ناموفق بود؛ فایل روی سرور است: $APP_DIR/$f${N}"; fi
}
cmd_autobackup(){
  echo " 1) هر ۲۴ ساعت   2) هر ۱۲ ساعت   3) هر ۶ ساعت   4) غیرفعال"; read -rp "انتخاب: " c
  case "$c" in 1) e="30 3 * * *";; 2) e="30 */12 * * *";; 3) e="30 */6 * * *";; 4) rm -f /etc/cron.d/configcompany-backup; echo "بکاپ خودکار غیرفعال شد"; return;; *) return;; esac
  read -rp "فایل بکاپ به تلگرام هم ارسال شود؟ [Y/n] " t; [[ "$t" =~ ^[nN]$ ]] && act=backup || act=export
  echo "$e root /usr/local/bin/configcompany $act >/dev/null 2>&1" > /etc/cron.d/configcompany-backup; echo -e "${G}بکاپ خودکار تنظیم شد ($act)${N}"
}
cmd_ssl(){
  echo "گواهی SSL را Caddy خودکار تمدید می‌کند. اگر مشکل دارید می‌توان صدور مجدد را اجباری کرد."
  confirm "گواهی‌های ذخیره‌شده پاک و دوباره صادر شود؟" || { dc restart caddy; return; }
  dc exec -T caddy sh -c 'rm -rf /data/caddy/certificates' ; dc restart caddy; sleep 5; dc logs --tail=15 caddy
}
cmd_bot(){
  read -rp "توکن جدید ربات: " t; me="$(curl -fs --max-time 10 "https://api.telegram.org/bot$t/getMe")"
  echo "$me" | grep -q '"ok":true' || { echo -e "${R}توکن نامعتبر${N}"; return 1; }
  u="$(echo "$me" | sed -n 's/.*"username":"\([^"]*\)".*/\1/p')"
  sed -i "s|^BOT_TOKEN=.*|BOT_TOKEN=$t|; s|^BOT_USERNAME=.*|BOT_USERNAME=$u|" .env; dc up -d --force-recreate api; echo -e "${G}ربات اصلی: @$u${N}"
  echo "ربات‌های اضافه (نمایندگان) را از پنل ← نمایندگان با توکن جدا بسازید."
}
cmd_admin(){
  read -rp "شناسه‌ی عددی تلگرام ادمین جدید: " i; [[ "$i" =~ ^[0-9]+$ ]] || { echo "عدد نامعتبر"; return 1; }
  sed -i "s|^ADMIN_TG_IDS=\(.*\)|ADMIN_TG_IDS=\1,$i|" .env; dc up -d --force-recreate api; echo -e "${G}ادمین اضافه شد${N}"
}
menu(){
  while true; do
    echo -e "\n${G}══════ ConfigCompany ══════${N}
  1) وضعیت سرویس‌ها            8) تمدید/صدور مجدد SSL
  2) ریستارت                   9) تغییر دامنه
  3) لاگ‌ها                     10) تغییر توکن ربات
  4) آپدیت                     11) افزودن ادمین
  5) خروجی دیتابیس (به تلگرام)  12) ویرایش تنظیمات (.env)
  6) ورود دیتابیس (بازیابی)     13) توکن ورود پنل مدیریت
  7) بکاپ خودکار               14) حذف کامل
  0) خروج"
    read -rp "انتخاب: " c
    case "$c" in 1) cmd_status;; 2) dc restart;; 3) cmd_log;; 4) cmd_update;; 5) cmd_export;; 6) cmd_restore;; 7) cmd_autobackup;; 8) cmd_ssl;;
      9) cmd_domain;; 10) cmd_bot;; 11) cmd_admin;; 12) cmd_settings;; 13) cmd_token;; 14) cmd_uninstall;; 0) exit 0;; *) echo "نامعتبر";; esac
  done
}
case "${1:-menu}" in
  status) cmd_status;; start) dc up -d;; stop) dc stop;; restart) dc restart;; log|logs) cmd_log "${2:-}";;
  update) cmd_update "${2:-}";; backup) cmd_backup;; export) cmd_export;; restore|import) cmd_restore "${2:-}";; autobackup) cmd_autobackup;;
  ssl) cmd_ssl;; bot) cmd_bot;; admin) cmd_admin;; token) cmd_token "${2:-}";; settings) cmd_settings;; domain) cmd_domain;; uninstall) cmd_uninstall;; menu) menu;;
  *) echo "استفاده: configcompany [status|start|stop|restart|log|update|backup|export|restore|autobackup|ssl|bot|admin|token|settings|domain|uninstall]";;
esac
