# Образ ноды ocserv. Основа — r4ven-me/openconnect (src/server/v1.3-sid):
# тот же набор пакетов, tini как PID 1, --foreground. Отличия — в плане Фазы 1.
FROM debian:trixie-slim

ARG DEBIAN_FRONTEND=noninteractive

# tini — PID 1: пожинает зомби хуков, пробрасывает сигналы в ocserv.
# gettext-base — envsubst для шаблона конфига.
RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        tini ocserv gnutls-bin iptables iproute2 curl ca-certificates gettext-base \
    && rm -rf /var/lib/apt/lists/*

COPY ocserv.conf.tmpl /etc/ocserv/ocserv.conf.tmpl
COPY --chmod=0755 hooks/connect.sh hooks/disconnect.sh /etc/ocserv/hooks/
COPY --chmod=0755 entrypoint.sh /entrypoint.sh
COPY --chmod=0755 healthcheck.sh /healthcheck.sh

ENTRYPOINT ["/usr/bin/tini", "--", "/entrypoint.sh"]

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s CMD ["/healthcheck.sh"]
