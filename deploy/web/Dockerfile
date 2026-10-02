# syntax=docker/dockerfile:1
# Mini App: сборка статики и раздача её Caddy. Контекст — корень репозитория:
#   docker build -f deploy/web/Dockerfile .

FROM node:22-alpine AS build
WORKDIR /tma
COPY frontend/tma/package.json frontend/tma/package-lock.json ./
RUN npm ci
COPY frontend/tma ./
# Адрес поддержки — на установку (переопределяет .env.production).
ARG VITE_SUPPORT_HANDLE=@ocmanager_help
ENV VITE_SUPPORT_HANDLE=$VITE_SUPPORT_HANDLE
# Сборка падает, если в бандл попал мок (Review Focus №4).
RUN npm run build && npm test -- src/build.test.ts

FROM caddy:2.8-alpine
COPY --from=build /tma/dist /srv/tma
# Caddyfile монтируется из deploy/caddy/ (Задача 7.5): правка конфига не требует пересборки.
