<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="../assets/logo-dark.svg">
    <img src="../assets/logo.svg" alt="ocmanager" height="40">
  </picture>
</p>

# Развёртывание ocmanager: техническая справка

Обычная установка — одной командой `sudo ./install.sh`, см. [INSTALL.md](INSTALL.md). Ниже — устройство стека
и ручной путь без мастера.

Один сервер, два домена: `DOMAIN_APP` (Mini App, вебхуки) и `DOMAIN_VPN` (шлюз ocserv).

## Что нужно

- Сервер Debian 12+/Ubuntu 22.04+, root или sudo, публичный IPv4. Docker 24+ с Compose v2
  (Ubuntu 24.04: `apt-get install -y docker.io docker-compose-v2`). Памяти от 1 ГБ, но на 1 ГБ сборка образов
  без swap падает по OOM: `fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile`.
  Сборка на таком сервере занимает около 5 минут.
- Две A-записи (`app.…` и `vpn.…`) на IP сервера. Порты **80/tcp, 443/tcp, 443/udp** свободны и открыты.
- Бот из @BotFather. Ключ API Tribute — позже, вебхуки без него просто отвечают 404.

Docker сам публикует порты в обход `ufw`: закрывайте лишнее на уровне облачного firewall провайдера.
Наружу должны смотреть только 80, 443 (tcp и udp) и ваш SSH.

## Первый запуск

```bash
git clone <репозиторий> ocmanager && cd ocmanager/deploy   # приватный репозиторий — нужен deploy key на сервере
cp .env.example .env && chmod 600 .env
# заполните домены, пароли (openssl rand -hex 24), OCM_SECRET_KEY, OCM_INTERNAL_TOKEN,
# OCM_CAMOUFLAGE_SECRET, OCM_BOT_TOKEN; OCM_BOT_USERNAME (без @) — чтобы в Mini App собиралась
# реферальная ссылка t.me/<бот>?start=ref_<код>; пусто — клиент увидит только код
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

Все строки должны быть зелёными. Что значит красная — в тексте самой проверки. Строка про сверку ноды
(reconcile) на только что поднятом стеке красная до первой сверки: воркер делает её раз в 5 минут. Подождите
5–6 минут и запустите проверку снова.

В логах Caddy при первом выпуске может мелькнуть `challenge failed … tls-alpn-01 … Connection reset`: Caddy
стартовал раньше nginx. Он повторяет попытку сам; важна строка `certificate obtained successfully` для обоих доменов.

## После запуска

1. **Mini App.** @BotFather → `/myapps` → ваше приложение → Edit Web App URL → `https://<DOMAIN_APP>`.
2. **Админка** — только через SSH-туннель:
   ```bash
   ssh -L 8080:127.0.0.1:8080 user@сервер
   # затем в браузере: http://localhost:8080/
   ```
   Войдите логином и паролем админа (создаётся `docker compose run --rm cli admin create`). Документация API
   осталась на `http://localhost:8080/admin/docs`: там `POST /admin/auth/login` → `csrf_token` из ответа →
   кнопка **Authorize** → поле `X-CSRF-Token`; cookie сессии браузер подставляет сам.
3. **Алерты админу.** Напишите боту `/whoami`, получите число — добавьте его в настройку `admin_chat_ids`
   (раздел «Настройки» админки или `PATCH /admin/settings`, тело `{"admin_chat_ids": [123456789]}`).
4. **Тарифы.** Скрытый тариф `trial` создаёт миграция, он есть сразу. Платные — `docker compose run --rm cli plan --help` или раздел «Тарифы» админки.
5. **Tribute.** В кабинете автора укажите вебхук `https://<DOMAIN_APP>/webhooks/tribute` и впишите ключ API
   в `OCM_TRIBUTE_API_KEY`; `docker compose up -d` применит.

## Проверка без Telegram

Пока нет бота, вся цепочка проверяется из CLI (`device issue` по умолчанию — только для dev, поэтому
`-e OCM_ENV=dev`; `.p12` и пароль — тестовые, после проверки удалите):

```bash
docker compose run --rm cli plan create --code m1 --name-ru Месяц --name-en Month --days 30 --devices 2 --price 19900
docker compose run --rm cli client add --telegram-id 1001 --first-name Tester
docker compose run --rm cli client grant 1001 m1
mkdir -p /root/certs && chmod 777 /root/certs
docker compose run --rm -e OCM_ENV=dev -v /root/certs:/out cli device issue 1001 --name laptop --platform linux --out /out/c.p12
# подключение: openconnect --certificate c.p12 "https://<DOMAIN_VPN>/?<OCM_CAMOUFLAGE_SECRET>"
docker exec ocm-ocserv occtl show users   # в колонке ip — адрес клиента, не 172.29.10.x
rm -rf /root/certs
```

Второе одновременное подключение тем же устройством отклоняется (`405 Method Not Allowed` на CONNECT) —
это нормально: один сертификат — одна сессия.

## Обновление

```bash
git pull
docker compose build
docker compose up -d      # миграции накатываются сами (сервис migrate)
../scripts/doctor.sh
```

## Резервные копии

Автоматические шифрованные копии и восстановление — `ocm backup` / `ocm restore`, см. [INSTALL.md](INSTALL.md).
Формат: один файл с `pg_dump`, томом `pki` и `.env`, `openssl enc -aes-256-cbc -pbkdf2`.

## Если что-то не так

| Симптом | Куда смотреть |
|---|---|
| ocserv перезапускается | `docker compose logs ocserv` — нет CA/CRL (шаг 2) или сертификата (Caddy ещё выпускает) |
| Сертификат не выпускается | A-записи, порт 80 снаружи, `docker compose logs caddy` (лимиты Let's Encrypt — 5 неудач в час) |
| Клиенты не подключаются через месяцы работы | `docker compose logs worker \| grep server_cert` — продление сертификата подхватывается воркером раз в 6 часов |
| Mini App — белый экран | Edit Web App URL в @BotFather; `curl -I https://<DOMAIN_APP>` не должен содержать `X-Frame-Options` |
| Нет уведомлений | `docker compose logs worker \| grep notifications`; `admin_chat_ids` не задан |
