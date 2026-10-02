#!/usr/bin/env bash
# Диагностика боевого стенда. На сервере из любого каталога: scripts/doctor.sh
# Каждая строка — одна проверка; код выхода = число проваленных.
set -uo pipefail
cd "$(dirname "$0")/../deploy"
set -a
# shellcheck disable=SC1091
. ./.env
set +a

fails=0
ok()  { printf '  \033[32mOK\033[0m   %s\n' "$1"; }
bad() { printf '  \033[31mFAIL\033[0m %s\n' "$1"; fails=$((fails + 1)); }
check() { local name=$1; shift; if "$@" >/dev/null 2>&1; then ok "$name"; else bad "$name"; fi; }

compose() { docker compose "$@"; }

# --- контейнеры ----------------------------------------------------------------------------------
no_dead_services() {
    ! compose ps --status exited --format '{{.Service}}' | grep -vE '^(migrate|volume-init)$' | grep -q .
}
check "все сервисы запущены (кроме разовых migrate и volume-init)" no_dead_services

# --- порты ---------------------------------------------------------------------------------------
listening_tcp() { ss -H -ltn "sport = :$1" | grep -q .; }
listening_udp() { ss -H -lun "sport = :$1" | grep -q .; }
check "80/tcp слушается" listening_tcp 80
check "443/tcp слушается" listening_tcp 443
check "443/udp слушается (DTLS)" listening_udp 443
admin_only_on_loopback() {
    local addrs
    addrs=$(ss -H -ltn 'sport = :8080' | awk '{print $4}')
    [ -n "$addrs" ] && ! echo "$addrs" | grep -qvE '^(127\.0\.0\.1|\[::1\]):8080$'
}
check "админка 8080 слушается только на loopback" admin_only_on_loopback
db_not_published() { ! { listening_tcp 5432 || listening_tcp 6379; }; }
check "Postgres и Redis не опубликованы" db_not_published

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
    check "сертификат $domain действителен (цепочка и имя)" cert_valid "$domain"
    check "сертификат $domain не истекает в ближайшие 14 дней" cert_days "$domain" 14
done

# --- публичный API --------------------------------------------------------------------------------
app_get()  { curl -s --max-time 5 --resolve "$DOMAIN_APP:443:127.0.0.1" "$@"; }
api_health() { app_get -f "https://$DOMAIN_APP/api/health" | grep -q '"ok"'; }
check "api-public отвечает через Caddy" api_health
internal_blocked() {
    local get post
    get=$(app_get -o /dev/null -w '%{http_code}' "https://$DOMAIN_APP/internal/session-end")
    post=$(app_get -o /dev/null -w '%{http_code}' -X POST "https://$DOMAIN_APP/internal/session-end")
    [ "$get" = 404 ] && [ "$post" = 404 ]
}
check "/internal снаружи недоступен (404 на GET и POST)" internal_blocked
mini_app() { app_get -f "https://$DOMAIN_APP/" | grep -qi '<div id="root"'; }
check "Mini App отдаёт страницу" mini_app
vpn_answers() { curl -ks -o /dev/null --max-time 5 --resolve "$DOMAIN_VPN:443:127.0.0.1" "https://$DOMAIN_VPN/"; }
check "VPN-домен отвечает по TLS через nginx и ocserv" vpn_answers

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
check "CRL не истекает в ближайшие 3 дня" crl_fresh
reconcile_ok() {
    compose exec -T postgres psql -U ocm -d ocmanager -tA -c \
        "select count(*) from nodes where last_reconcile_at > now() - interval '15 minutes' and coalesce(last_reconcile_report->>'error', '') = ''" \
        | grep -qx 1
}
check "последняя сверка ноды (reconcile) — меньше 15 минут назад, без ошибки" reconcile_ok
docker_proxy_restricts() { ! compose exec -T worker docker ps; }
check "worker не может выполнить docker ps (прокси ограничивает)" docker_proxy_restricts
proxy_protocol_enforced() { ! docker exec ocm-ocserv curl -ks --max-time 3 -o /dev/null https://localhost:443/; }
check "ocserv требует PROXY-заголовок на TCP (адрес клиента не теряется)" proxy_protocol_enforced

echo
if [ "$fails" -eq 0 ]; then
    printf '\033[32mвсё в порядке\033[0m\n'
else
    printf '\033[31mпроваленных проверок: %d\033[0m\n' "$fails"
fi
exit "$fails"
