# Развёртывание ocmanager

Один сервер, два домена: `DOMAIN_APP` (Mini App, вебхуки) и `DOMAIN_VPN` (шлюз ocserv).

## Что нужно

- Сервер Debian 12+/Ubuntu 22.04+, root или sudo, публичный IPv4. Docker 24+ с Compose v2.
- Две A-записи (`app.…` и `vpn.…`) на IP сервера. Порты **80/tcp, 443/tcp, 443/udp** свободны и открыты.
- Бот из @BotFather. Ключ API Tribute — позже, вебхуки без него просто отвечают 404.

Docker сам публикует порты в обход `ufw`: закрывайте лишнее на уровне облачного firewall провайдера.
Наружу должны смотреть только 80, 443 (tcp и udp) и ваш SSH.

## Первый запуск

```bash
git clone <репозиторий> ocmanager && cd ocmanager/deploy
cp .env.example .env && chmod 600 .env
# заполните домены, пароли (openssl rand -hex 24), OCM_SECRET_KEY, OCM_INTERNAL_TOKEN,
# OCM_CAMOUFLAGE_SECRET, OCM_BOT_TOKEN
docker compose build
```

Порядок важен: ocserv не стартует без CA и CRL, а панель — без миграций.

```bash
# 1. Базы, миграции и права на тома
docker compose up -d postgres redis volume-init
# 2. CA (создаётся один раз; повторный запуск откажется перезаписывать)
docker compose run --rm cli pki init
# 3. Первый администратор (пароль ≥ 12 символов)
docker compose run --rm cli admin create owner
# 4. Всё остальное. Caddy выпустит оба сертификата (1–3 минуты); ocserv дождётся своего
docker compose up -d
docker compose logs -f caddy      # ждём «certificate obtained successfully» для обоих доменов
```

Проверка:

```bash
../scripts/doctor.sh
```

Все строки должны быть зелёными. Что значит красная — в тексте самой проверки.

## После запуска

1. **Mini App.** @BotFather → `/myapps` → ваше приложение → Edit Web App URL → `https://<DOMAIN_APP>`.
2. **Админка** — только через SSH-туннель:
   ```bash
   ssh -L 8080:127.0.0.1:8080 user@сервер
   # затем в браузере: http://localhost:8080/admin/docs
   ```
3. **Алерты админу.** Напишите боту `/whoami`, получите число — добавьте его в настройку `admin_chat_ids`
   (`PATCH /admin/settings` в документации админки).
4. **Тарифы** — `docker compose run --rm cli plan --help` или раздел «Тарифы» админки.
5. **Tribute.** В кабинете автора укажите вебхук `https://<DOMAIN_APP>/webhooks/tribute` и впишите ключ API
   в `OCM_TRIBUTE_API_KEY`; `docker compose up -d` применит.

## Обновление

```bash
git pull
docker compose build
docker compose up -d      # миграции накатываются сами (сервис migrate)
../scripts/doctor.sh
```

## Резервные копии (пока вручную)

Автоматических бэкапов нет. **Потеря тома `pki` — это потеря CA: все выданные клиентам ключи придётся
выпускать заново.** Делайте копию после `pki init` и по расписанию:

```bash
docker compose exec -T postgres pg_dump -U ocm ocmanager | gzip > ocmanager-$(date +%F).sql.gz
docker run --rm -v ocmanager_pki:/pki:ro -v "$PWD":/out alpine tar czf /out/pki-$(date +%F).tgz -C /pki .
```

Храните копии вне сервера. Файл с `pki` содержит приватный ключ CA — шифруйте его.

## Если что-то не так

| Симптом | Куда смотреть |
|---|---|
| ocserv перезапускается | `docker compose logs ocserv` — нет CA/CRL (шаг 2) или сертификата (Caddy ещё выпускает) |
| Сертификат не выпускается | A-записи, порт 80 снаружи, `docker compose logs caddy` (лимиты Let's Encrypt — 5 неудач в час) |
| Клиенты не подключаются через месяцы работы | `docker compose logs worker \| grep server_cert` — продление сертификата подхватывается воркером раз в 6 часов |
| Mini App — белый экран | Edit Web App URL в @BotFather; `curl -I https://<DOMAIN_APP>` не должен содержать `X-Frame-Options` |
| Нет уведомлений | `docker compose logs worker \| grep notifications`; `admin_chat_ids` не задан |
