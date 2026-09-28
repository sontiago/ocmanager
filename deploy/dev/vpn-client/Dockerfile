# Тестовый VPN-клиент для dev-стенда и интеграционных тестов.
# Debian, а не Alpine: openconnect здесь собран с GnuTLS, как ocserv, и
# читает legacy-.p12 (3DES) без провайдера OpenSSL legacy.
FROM debian:trixie-slim
ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
    && apt-get install --yes --no-install-recommends openconnect vpnc-scripts ca-certificates iproute2 iputils-ping curl \
    && rm -rf /var/lib/apt/lists/*
ENTRYPOINT []
