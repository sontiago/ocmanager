# Документация ocmanager

С чего начать новому человеку: прочитайте [architecture.md](architecture.md), затем [data-flows.md](data-flows.md),
потом откройте раздел той части, с которой работаете.

| Документ | О чём |
|---|---|
| [architecture.md](architecture.md) | из чего состоит система, как части связаны, границы доверия |
| [data-flows.md](data-flows.md) | сквозные сценарии: покупка, выдача ключа, подключение, трафик, отзыв, сверка |
| [deploy.md](deploy.md) | Docker Compose, сети, нода ocserv, установщик, `ocm`, бэкапы |
| [glossary.md](glossary.md) | термины проекта |
| **Бэкенд** | |
| [backend/architecture.md](backend/architecture.md) | модули, слои, границы импортов, соглашения |
| [backend/data-model.md](backend/data-model.md) | таблицы, связи, состояния подписки |
| [backend/api.md](backend/api.md) | публичный, админский и внутренний API, авторизация |
| [backend/workers-and-events.md](backend/workers-and-events.md) | события, outbox, cron-задачи воркера, уведомления |
| **Веб-админка** | |
| [admin/architecture.md](admin/architecture.md) | стек, структура, слой данных, страницы |
| **Mini App** | |
| [tma/architecture.md](tma/architecture.md) | стек, структура, мок и HTTP, экраны, интеграция с Telegram |

README подпроектов: [backend](../backend/README.md), [admin](../frontend/admin/README.md), [tma](../frontend/tma/README.md).
Инструкция владельца сервера: [deploy/INSTALL.ru.md](../deploy/INSTALL.ru.md) ([English](../deploy/INSTALL.md)).
