#!/bin/sh
# Запуск ноды: проверить PKI, дождаться CRL, собрать конфиг, включить NAT,
# передать управление ocserv. Под tini (PID 1), поэтому exec в конце.
set -eu

STATE_DIR=/var/lib/ocmanager
RUNTIME_DIR=/etc/ocmanager/runtime

die() {
    echo "entrypoint: $*" >&2
    exit 1
}

: "${OCSERV_SERVER_CERT:?}" "${OCSERV_SERVER_KEY:?}" "${OCSERV_IPV4_NETWORK:?}"
: "${OCSERV_CAMOUFLAGE_SECRET:?}" "${OCM_INTERNAL_TOKEN:?}" "${OCM_SESSION_END_URL:?}"
export OCSERV_MAX_BAN_SCORE="${OCSERV_MAX_BAN_SCORE:-100}"

for f in "$STATE_DIR/ca.crt" "$OCSERV_SERVER_CERT" "$OCSERV_SERVER_KEY"; do
    [ -r "$f" ] || die "нет $f — выполните: uv run ocmanager pki init && uv run ocmanager pki dev-server-cert --host ocserv --host localhost"
done

# Без CRL ocserv не стартует; его пишет `ocmanager pki init`.
waited=0
until [ -r "$STATE_DIR/crl.pem" ]; do
    [ "$waited" -ge 60 ] && die "нет $STATE_DIR/crl.pem — выполните: uv run ocmanager pki init"
    [ "$waited" -eq 0 ] && echo "entrypoint: жду $STATE_DIR/crl.pem…" >&2
    sleep 1
    waited=$((waited + 1))
done

# Пустой allowed.list = всем отказ: безопасный дефолт.
[ -e "$STATE_DIR/allowed.list" ] || : >"$STATE_DIR/allowed.list"

# Секреты для хуков — в файлах (решение №12): окружение контейнера
# до скриптов ocserv не доходит.
mkdir -p "$RUNTIME_DIR"
(
    umask 077
    printf '%s' "$OCM_INTERNAL_TOKEN" >"$RUNTIME_DIR/internal_token"
)
cat >/etc/ocmanager/hooks.env <<ENV
ALLOWLIST='$STATE_DIR/allowed.list'
SESSION_END_URL='$OCM_SESSION_END_URL'
INTERNAL_TOKEN_FILE='$RUNTIME_DIR/internal_token'
ENV

# Явный список: иначе envsubst съест любой другой $ в конфиге.
envsubst '${OCSERV_SERVER_CERT} ${OCSERV_SERVER_KEY} ${OCSERV_IPV4_NETWORK} ${OCSERV_CAMOUFLAGE_SECRET} ${OCSERV_MAX_BAN_SCORE}' \
    </etc/ocserv/ocserv.conf.tmpl >/etc/ocserv/ocserv.conf

# NAT для всей подсети клиентов; -C делает правило идемпотентным.
iptables -t nat -C POSTROUTING -s "$OCSERV_IPV4_NETWORK" -j MASQUERADE 2>/dev/null ||
    iptables -t nat -A POSTROUTING -s "$OCSERV_IPV4_NETWORK" -j MASQUERADE

echo "entrypoint: запускаю $(ocserv --version 2>&1 | head -n 1)" >&2
exec ocserv --foreground --config /etc/ocserv/ocserv.conf
