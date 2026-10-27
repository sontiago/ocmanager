#!/usr/bin/env bash
# Диагностика боевого стенда. На сервере из любого каталога: scripts/doctor.sh
# Каждая строка — одна проверка; код выхода = число проваленных.
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
cd "$here/../deploy" || exit 1
# Язык: OCM_LANG (его задаёт ocm), иначе выбранный при установке, иначе английский.
lang="${OCM_LANG:-$(sed -n 's/.*"lang": "\([a-z]*\)".*/\1/p' .install-state 2>/dev/null | head -n 1)}"
t() { if [ "${lang:-en}" = ru ]; then printf '%s' "$1"; else printf '%s' "$2"; fi; }

set -a
# shellcheck disable=SC1091
. ./.env
set +a

fails=0
ok()  { printf '  \033[32mOK\033[0m   %s\n' "$1"; }
bad() { printf '  \033[31mFAIL\033[0m %s\n' "$1"; fails=$((fails + 1)); }
check() { local name=$1; shift; if "$@" >/dev/null 2>&1; then ok "$name"; else bad "$name"; fi; }

compose() { docker compose "$@"; }
# shellcheck disable=SC1091
. "$here/lib-backup-age.sh"

# --- контейнеры ----------------------------------------------------------------------------------
no_dead_services() {
    ! compose ps --status exited --format '{{.Service}}' | grep -vE '^(migrate|volume-init)$' | grep -q .
}
check "$(t "все сервисы запущены (кроме разовых migrate и volume-init)" "all services are running (except the one-shot migrate and volume-init)")" no_dead_services

# --- порты ---------------------------------------------------------------------------------------
listening_tcp() { ss -H -ltn "sport = :$1" | grep -q .; }
listening_udp() { ss -H -lun "sport = :$1" | grep -q .; }
check "$(t "80/tcp слушается" "80/tcp is listening")" listening_tcp 80
check "$(t "443/tcp слушается" "443/tcp is listening")" listening_tcp 443
check "$(t "443/udp слушается (DTLS)" "443/udp is listening (DTLS)")" listening_udp 443
admin_only_on_loopback() {
    local addrs
    addrs=$(ss -H -ltn 'sport = :8080' | awk '{print $4}')
    [ -n "$addrs" ] && ! echo "$addrs" | grep -qvE '^(127\.0\.0\.1|\[::1\]):8080$'
}
check "$(t "админка 8080 слушается только на loopback" "admin panel 8080 listens on loopback only")" admin_only_on_loopback
db_not_published() { ! { listening_tcp 5432 || listening_tcp 6379; }; }
check "$(t "Postgres и Redis не опубликованы" "Postgres and Redis are not published")" db_not_published

# --- сертификаты обоих доменов ---------------------------------------------------------------------
cert_valid() {
    echo | openssl s_client -connect 127.0.0.1:443 -servername "$1" -verify_hostname "$1" 2>/dev/null \
        | grep -q 'Verify return code: 0 (ok)'
}
cert_days() {
    echo | openssl s_client -connect 127.0.0.1:443 -servername "$1" 2>/dev/null \
        | openssl x509 -noout -checkend $(($2 * 86400))
}
for domain in "$DOMAIN_APP" "$DOMAIN_VPN"; do
    check "$(t "сертификат $domain действителен (цепочка и имя)" "certificate for $domain is valid (chain and name)")" cert_valid "$domain"
    check "$(t "сертификат $domain не истекает в ближайшие 14 дней" "certificate for $domain does not expire within 14 days")" cert_days "$domain" 14
done

# --- публичный API --------------------------------------------------------------------------------
app_get()  { curl -s --max-time 5 --resolve "$DOMAIN_APP:443:127.0.0.1" "$@"; }
api_health() { app_get -f "https://$DOMAIN_APP/api/health" | grep -q '"ok"'; }
check "$(t "api-public отвечает через Caddy" "api-public answers through Caddy")" api_health
internal_blocked() {
    local get post
    get=$(app_get -o /dev/null -w '%{http_code}' "https://$DOMAIN_APP/internal/session-end")
    post=$(app_get -o /dev/null -w '%{http_code}' -X POST "https://$DOMAIN_APP/internal/session-end")
    [ "$get" = 404 ] && [ "$post" = 404 ]
}
check "$(t "/internal снаружи недоступен (404 на GET и POST)" "/internal is unreachable from outside (404 on GET and POST)")" internal_blocked
mini_app() { app_get -f "https://$DOMAIN_APP/" | grep -qi '<div id="root"'; }
check "$(t "Mini App отдаёт страницу" "the Mini App serves its page")" mini_app
vpn_answers() { curl -ks -o /dev/null --max-time 5 --resolve "$DOMAIN_VPN:443:127.0.0.1" "https://$DOMAIN_VPN/"; }
check "$(t "VPN-домен отвечает по TLS через nginx и ocserv" "the VPN domain answers over TLS through nginx and ocserv")" vpn_answers

# --- нода ------------------------------------------------------------------------------------------------
ocserv_healthy() { [ "$(docker inspect -f '{{.State.Health.Status}}' ocm-ocserv)" = healthy ]; }
check "ocserv healthy" ocserv_healthy
crl_fresh() {
    compose exec -T worker python - <<'PY'
import sys
from datetime import UTC, datetime, timedelta

from cryptography import x509

crl = x509.load_pem_x509_crl(open("/var/lib/ocmanager/crl.pem", "rb").read())
sys.exit(0 if crl.next_update_utc - datetime.now(UTC) > timedelta(days=3) else 1)
PY
}
check "$(t "CRL не истекает в ближайшие 3 дня" "the CRL does not expire within 3 days")" crl_fresh
reconcile_ok() {
    compose exec -T postgres psql -U ocm -d ocmanager -tA -c \
        "select count(*) from nodes where last_reconcile_at > now() - interval '15 minutes' and coalesce(last_reconcile_report->>'error', '') = ''" \
        | grep -qx 1
}
check "$(t "последняя сверка ноды (reconcile) — меньше 15 минут назад, без ошибки" "last node reconcile was less than 15 minutes ago, without errors")" reconcile_ok
docker_proxy_restricts() { ! compose exec -T worker docker ps; }
check "$(t "worker не может выполнить docker ps (прокси ограничивает)" "worker cannot run docker ps (the proxy restricts it)")" docker_proxy_restricts
proxy_protocol_enforced() { ! docker exec ocm-ocserv curl -ks --max-time 3 -o /dev/null https://localhost:443/; }
check "$(t "ocserv требует PROXY-заголовок на TCP (адрес клиента не теряется)" "ocserv requires the PROXY header on TCP (the client address is preserved)")" proxy_protocol_enforced

# --- резервные копии ---------------------------------------------------------------------------------
backup_fresh() { backup_is_fresh /var/backups/ocmanager/last-ok "$(date +%s)"; }
if [ -f /etc/systemd/system/ocm-backup.timer ]; then
    check "$(t "последняя успешная резервная копия не старше 36 часов (если FAIL: ocm backup)" "last successful backup is not older than 36 hours (if FAIL: ocm backup)")" backup_fresh
else
    printf '  \033[33mSKIP\033[0m %s\n' "$(t 'резервные копии не включены (ocm backup-enable)' 'backups are not enabled (ocm backup-enable)')"
fi

echo
if [ "$fails" -eq 0 ]; then
    printf '\033[32m%s\033[0m\n' "$(t 'всё в порядке' 'all good')"
else
    printf '\033[31m%s: %d\033[0m\n' "$(t 'проваленных проверок' 'failed checks')" "$fails"
fi
exit "$fails"
