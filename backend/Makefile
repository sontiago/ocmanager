# Команды бэкенда. Запускать из каталога backend/.
COMPOSE_DEV := docker compose -f ../deploy/docker-compose.dev.yml

.PHONY: dev-up dev-down lint fmt typecheck test test-unit check migrate revision

dev-up:     ## Postgres и Redis для разработки и тестов
	$(COMPOSE_DEV) up -d --wait
dev-down:   ## остановить dev-инфраструктуру (данные сохраняются)
	$(COMPOSE_DEV) down
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
check: lint typecheck test ## всё, что гоняет CI
migrate:    ## применить миграции к dev-базе
	uv run alembic upgrade head
revision:   ## новая миграция: make revision id=0004 m=clients
	uv run alembic revision --autogenerate --rev-id $(id) -m $(m)