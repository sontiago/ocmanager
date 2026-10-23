# Команды бэкенда. Запускать из каталога backend/.
COMPOSE_DEV := docker compose -f ../deploy/docker-compose.dev.yml

.PHONY: admin-types admin-types-check dev-up dev-down api-public api-admin bot ocserv-up ocserv-down test-ocserv lint fmt typecheck test test-unit check migrate revision boundaries

dev-up:     ## Postgres и Redis для разработки и тестов
	$(COMPOSE_DEV) up -d --wait
dev-down:   ## остановить dev-инфраструктуру (данные сохраняются)
	$(COMPOSE_DEV) down
api-public: ## публичный API на 0.0.0.0:8000: его вызывает disconnect.sh из контейнера ноды
	uv run uvicorn ocmanager.apps.public_api:create_app --factory --host 0.0.0.0 --port 8000
api-admin:  ## админ-API на 127.0.0.1:8080 (наружу — только через SSH-туннель)
	uv run uvicorn ocmanager.apps.admin_api:create_app --factory --host 127.0.0.1 --port 8080
lint:       ## ruff: линтер и формат
	uv run ruff check . && uv run ruff format --check .
fmt:        ## автоисправление и форматирование
	uv run ruff check --fix . && uv run ruff format .
typecheck:  ## mypy --strict
	uv run mypy
test:       ## все тесты, кроме живого ocserv (нужен make dev-up)
	uv run pytest
test-unit:  ## тесты без Postgres и Redis
	uv run pytest -m "not db and not ocserv"
check: lint typecheck boundaries test ## всё, что гоняет CI
migrate:    ## применить миграции к dev-базе
	uv run alembic upgrade head
revision:   ## новая миграция: make revision id=0004 m=clients
	uv run alembic revision --autogenerate --rev-id $(id) -m $(m)
boundaries: ## доменные модули не импортируют друг друга
	uv run python scripts/check_boundaries.py
bot:        ## бот: long polling, нужен OCM_BOT_TOKEN
	uv run python -m ocmanager.apps.bot
ocserv-up:  ## нода ocserv (профиль ocserv); нужен ocmanager pki init
	$(COMPOSE_DEV) --profile ocserv up -d --build --wait ocserv
ocserv-down: ## остановить ноду
	$(COMPOSE_DEV) --profile ocserv stop ocserv
test-ocserv: ## интеграционные тесты с живым ocserv (нужен make ocserv-up)
	uv run pytest tests/integration -m ocserv -v
ADMIN_TYPES := ../frontend/admin/src/api/generated.d.ts
OPENAPI_TS  := npx --yes openapi-typescript@7.13.0
admin-types: ## перегенерировать типы админки из кода (без запущенного сервера)
	uv run python scripts/dump_openapi.py admin > /tmp/ocm-admin-openapi.json
	$(OPENAPI_TS) /tmp/ocm-admin-openapi.json -o $(ADMIN_TYPES)
admin-types-check: ## типы админки в репозитории совпадают с кодом бэкенда (CI)
	uv run python scripts/dump_openapi.py admin > /tmp/ocm-admin-openapi.json
	$(OPENAPI_TS) /tmp/ocm-admin-openapi.json -o /tmp/ocm-admin-types.d.ts
	@diff -u $(ADMIN_TYPES) /tmp/ocm-admin-types.d.ts > /tmp/ocm-admin-types.diff \
	  && echo "типы админки актуальны" \
	  || { head -40 /tmp/ocm-admin-types.diff; echo "типы админки устарели: make admin-types"; exit 1; }
