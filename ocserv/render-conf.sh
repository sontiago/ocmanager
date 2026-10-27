#!/bin/sh
# Собирает /etc/ocserv/ocserv.conf: шаблон + строки `no-route` из файла панели.
# Вызывается из entrypoint при старте и панелью (docker exec) после смены маршрутов; затем
# `occtl reload` применяет конфиг к новым подключениям. Основной конфиг, а не default-user-config:
# последний на практике не отдавался клиентам AnyConnect.
set -eu

STATE_DIR=/var/lib/ocmanager
ROUTES="$STATE_DIR/default-user.conf"
CONF=/etc/ocserv/ocserv.conf

export OCSERV_MAX_BAN_SCORE="${OCSERV_MAX_BAN_SCORE:-100}"
export OCSERV_PROXY_PROTOCOL="${OCSERV_PROXY_PROTOCOL:-false}"

# Явный список: иначе envsubst съест любой другой $ в конфиге.
envsubst '${OCSERV_SERVER_CERT} ${OCSERV_SERVER_KEY} ${OCSERV_IPV4_NETWORK} ${OCSERV_CAMOUFLAGE_SECRET} ${OCSERV_MAX_BAN_SCORE} ${OCSERV_PROXY_PROTOCOL}' \
    </etc/ocserv/ocserv.conf.tmpl >"$CONF.new"

# Из файла берём только строгие `no-route = IPv4[/маска]`: ничего другого в конфиг не попадёт.
if [ -r "$ROUTES" ]; then
    {
        echo
        echo "# --- Адреса мимо VPN (из админки) ---"
        grep -E '^no-route = ([0-9]{1,3}\.){3}[0-9]{1,3}(/[0-9]{1,2})?$' "$ROUTES" || true
    } >>"$CONF.new"
fi

# Подставлять свой конфиг на ходу опасно: проверяем перед заменой.
ocserv --test-config --config "$CONF.new" >/dev/null
mv "$CONF.new" "$CONF"
