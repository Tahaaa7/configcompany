#!/usr/bin/env bash
# ConfigCompany installer
#   bash <(curl -Ls https://raw.githubusercontent.com/YOUR_USER/configcompany/main/install.sh)
# غیرتعاملی: CC_YES=1 CC_DOMAIN=... CC_BOT_TOKEN=... CC_ADMIN_ID=... bash install.sh
set -euo pipefail
APP_DIR=/opt/configcompany
REPO="${CC_REPO:-https://github.com/YOUR_USER/configcompany}"
BRANCH="${CC_BRANCH:-main}"
R='\033[31m'; G='\033[32m'; Y='\033[33m'; N='\033[0m'
info(){ echo -e "${G}[+]${N} $*"; }; warn(){ echo -e "${Y}[!]${N} $*"; }; die(){ echo -e "${R}[x]${N} $*" >&2; exit 1; }
[ "$(id -u)" = 0 ] || die "با کاربر root اجرا کنید (sudo -i)"

ask(){ # ask VAR "متن" [پیش‌فرض] [secret]
  local var="$1" prompt="$2" def="${3:-}" mode="${4:-}" cur="${!1:-}" ans=""
  [ -n "$cur" ] && return 0
  if [ "${CC_YES:-0}" = 1 ]; then printf -v "$var" '%s' "$def"; return 0; fi
  if [ "$mode" = secret ]; then read -rsp "$prompt: " ans </dev/tty; echo; else read -rp "$prompt${def:+ [$def]}: " ans </dev/tty; fi
  printf -v "$var" '%s' "${ans:-$def}"
}
pkg(){ command -v apt-get >/dev/null && { apt-get update -qq && apt-get install -y -qq "$@"; return; }
       command -v dnf >/dev/null && { dnf install -y -q "$@"; return; }
       command -v yum >/dev/null && { yum install -y -q "$@"; return; }; die "مدیر بسته پشتیبانی‌نشده؛ $* را دستی نصب کنید"; }

banner(){ echo -e "${G}
  ╔══════════════════════════════════════╗
  ║          C o n f i g C o m p a n y   ║
  ║   ربات فروش VPN · مینی‌اپ · پنل مدیریت  ║
  ╚══════════════════════════════════════╝${N}\n"; }
if [ "${CC_YES:-0}" != 1 ] && [ "${1:-}" != install ]; then
  banner
  if [ -f "$APP_DIR/.env" ] && [ -x /usr/local/bin/configcompany ]; then
    info "ConfigCompany از قبل نصب است؛ منوی مدیریت:"; exec /usr/local/bin/configcompany menu </dev/tty
  fi
  echo " 1) نصب ConfigCompany"; echo " 0) خروج"; read -rp "انتخاب: " ch </dev/tty; [ "$ch" = 1 ] || exit 0
fi

for c in curl openssl tar; do command -v $c >/dev/null || pkg $c; done
if ! command -v docker >/dev/null; then info "نصب Docker…"; curl -fsSL https://get.docker.com | sh; fi
systemctl enable --now docker >/dev/null 2>&1 || true
docker compose version >/dev/null 2>&1 || die "Docker Compose v2 پیدا نشد (docker compose)"

# ── دریافت سورس ──
fetch_source(){
  local here; here="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || true)"
  mkdir -p "$APP_DIR"
  if [ -f "$here/docker-compose.yml" ] && [ -d "$here/app" ]; then
    info "نصب از پوشه‌ی محلی: $here"
    [ "$here" = "$APP_DIR" ] || (cd "$here" && tar cf - --exclude=.env --exclude=backups --exclude=.git .) | (cd "$APP_DIR" && tar xf -)
  else
    [[ "$REPO" == *YOUR_USER* ]] && die "آدرس مخزن تنظیم نشده. پروژه را در GitHub خودتان آپلود کنید و با CC_REPO=https://github.com/<شما>/configcompany اجرا کنید، یا install.sh را از داخل پوشه‌ی استخراج‌شده‌ی پروژه اجرا کنید."
    command -v git >/dev/null || pkg git
    local tmp; tmp="$(mktemp -d)"; info "دریافت $REPO ($BRANCH)…"
    git clone -q --depth 1 -b "$BRANCH" "$REPO" "$tmp/src" || die "دریافت مخزن ناموفق بود"
    (cd "$tmp/src" && tar cf - --exclude=.git .) | (cd "$APP_DIR" && tar xf -); rm -rf "$tmp"
  fi
}
fetch_source

# ── تنظیمات ──
if [ -f "$APP_DIR/.env" ]; then
  warn ".env از قبل وجود دارد؛ تنظیمات و دیتابیس فعلی حفظ می‌شود."
else
  DOMAIN="${CC_DOMAIN:-}"; BOT_TOKEN="${CC_BOT_TOKEN:-}"; ADMIN_ID="${CC_ADMIN_ID:-}"; SUPPORT="${CC_SUPPORT:-}"
  echo -e "\n${G}── نصب ConfigCompany ──${N}"
  ask DOMAIN "دامنه (باید به IP این سرور اشاره کند، مثل vpn.example.com)"
  [ -n "$DOMAIN" ] || die "دامنه لازم است (مینی‌اپ تلگرام فقط با HTTPS کار می‌کند)"
  SIP="$(curl -4fs --max-time 8 https://api.ipify.org || true)"; DIP="$(getent ahostsv4 "$DOMAIN" 2>/dev/null | awk '{print $1; exit}' || true)"
  if [ -n "$SIP" ] && [ "$SIP" != "$DIP" ]; then
    warn "دامنه به $DIP اشاره می‌کند ولی IP سرور $SIP است؛ بدون اصلاح DNS گواهی HTTPS صادر نمی‌شود."
    [ "${CC_YES:-0}" = 1 ] || { read -rp "ادامه بدهم؟ [y/N] " a </dev/tty; [[ "$a" =~ ^[yY]$ ]] || exit 1; }
  fi
  ask BOT_TOKEN "توکن ربات (از @BotFather)"
  me="$(curl -fs --max-time 10 "https://api.telegram.org/bot${BOT_TOKEN}/getMe" || true)"
  echo "$me" | grep -q '"ok":true' || die "توکن ربات نامعتبر است"
  BOT_USERNAME="$(echo "$me" | sed -n 's/.*"username":"\([^"]*\)".*/\1/p')"; info "ربات: @$BOT_USERNAME"
  ask ADMIN_ID "شناسه‌ی عددی تلگرام شما (از @userinfobot)"
  [[ "$ADMIN_ID" =~ ^[0-9]+$ ]] || die "شناسه‌ی ادمین باید عدد باشد"
  ask SUPPORT "یوزرنیم پشتیبانی بدون @ (اختیاری)" ""
  PANEL="${CC_PANEL:-}"; PANEL_URL="${CC_PANEL_URL:-}"; PANEL_TOKEN="${CC_PANEL_TOKEN:-}"; PANEL_USER="${CC_PANEL_USER:-}"; PANEL_PASS="${CC_PANEL_PASS:-}"
  ask PANEL "نوع پنل VPN: mock (آزمایشی) / remnawave / marzban" "mock"
  case "$PANEL" in
    remnawave) ask PANEL_URL "آدرس پنل (https://panel.example.com)"; ask PANEL_TOKEN "API Token ریم‌ناوه" "" secret;;
    marzban)   ask PANEL_URL "آدرس پنل"; ask PANEL_USER "نام کاربری ادمین پنل"; ask PANEL_PASS "رمز ادمین پنل" "" secret;;
    mock)      warn "حالت mock: اشتراک‌ها واقعی ساخته نمی‌شوند؛ بعداً با «configcompany settings» پنل را تنظیم کنید.";;
    *) die "نوع پنل نامعتبر";;
  esac
  ask ZP "مرچنت زرین‌پال (اختیاری)" "${CC_ZARINPAL:-}"
  DBPASS="$(openssl rand -hex 16)"; JWT="$(openssl rand -hex 32)"
  umask 077
  cat > "$APP_DIR/.env" <<ENV
DOMAIN=$DOMAIN
PUBLIC_URL=https://$DOMAIN
DB_PASSWORD=$DBPASS
DATABASE_URL=postgresql+psycopg://configcompany:$DBPASS@db:5432/configcompany
BOT_TOKEN=$BOT_TOKEN
BOT_USERNAME=$BOT_USERNAME
SUPPORT_USERNAME=$SUPPORT
JWT_SECRET=$JWT
ADMIN_TG_IDS=$ADMIN_ID
PANEL=$PANEL
PANEL_URL=$PANEL_URL
PANEL_TOKEN=$PANEL_TOKEN
PANEL_USERNAME=$PANEL_USER
PANEL_PASSWORD=$PANEL_PASS
REMNAWAVE_SQUAD_UUIDS=${CC_SQUADS:-}
ZARINPAL_MERCHANT=$ZP
CORS_ORIGINS=https://$DOMAIN
TRUST_PROXY=1
USE_ALEMBIC=0
DEV_ALLOW_UNSIGNED=0
CC_REPO=$REPO
CC_BRANCH=$BRANCH
ENV
  umask 022
fi

# ── فایروال ──
if command -v ufw >/dev/null && ufw status 2>/dev/null | grep -q "Status: active"; then ufw allow 80/tcp >/dev/null; ufw allow 443/tcp >/dev/null; info "پورت‌های 80/443 در ufw باز شد"; fi
if ss -ltn 2>/dev/null | grep -qE ':(80|443)\s' && ! docker compose -f "$APP_DIR/docker-compose.yml" ps -q caddy 2>/dev/null | grep -q .; then
  warn "پورت 80 یا 443 اشغال است (nginx/apache؟). آن را متوقف کنید وگرنه Caddy بالا نمی‌آید."
fi

# ── اجرا ──
cd "$APP_DIR"; chmod +x configcompany.sh install.sh 2>/dev/null || true
install -m 755 configcompany.sh /usr/local/bin/configcompany
[ -f /etc/cron.d/configcompany-backup ] || echo '30 3 * * * root /usr/local/bin/configcompany backup >/dev/null 2>&1' > /etc/cron.d/configcompany-backup
info "ساخت و اجرای سرویس‌ها (بار اول چند دقیقه طول می‌کشد)…"
docker compose up -d --build
for i in $(seq 1 60); do
  [ "$(docker inspect --format '{{.State.Health.Status}}' "$(docker compose ps -q api)" 2>/dev/null)" = healthy ] && break; sleep 3
done
docker compose ps -q api | grep -q . || die "سرویس بالا نیامد؛ لاگ: configcompany log"

D="$(grep ^DOMAIN= .env | cut -d= -f2)"; A="$(grep ^ADMIN_TG_IDS= .env | cut -d= -f2 | cut -d, -f1)"
TOKEN="$(docker compose exec -T api python -m app.cli token "$A" 2>/dev/null | tail -1 || true)"
echo -e "\n${G}✅ نصب کامل شد${N}
  صفحه‌ی اصلی : https://$D/
  مینی‌اپ     : https://$D/miniapp/   ← در BotFather: /mybots ← Bot Settings ← Menu Button ← این آدرس
  پنل مدیریت  : https://$D/admin-ui/
  توکن ورود پنل (۷ روز): ${TOKEN:-نامشخص؛ بعداً: configcompany token}
  مدیریت      : فقط بنویسید  configcompany  (منوی کامل) — یا دوباره همین دستور نصب را بزنید
"
