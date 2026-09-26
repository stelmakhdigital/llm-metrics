# llm-metrics: dev-задачи (без docker) + прод (docker compose)
VENV     := api/.venv
PY       := $(VENV)/bin/python
# docker compose (v2) если есть, иначе docker-compose (v1); переопределяется: make COMPOSE=...
COMPOSE  ?= $(shell docker compose version >/dev/null 2>&1 && echo "docker compose" || echo docker-compose)
MOCK_F   := -f docker-compose.yml -f docker-compose.mock.yml

.PHONY: setup dev-api dev-web mock-vllm test-api alembic
.PHONY: start down rebuild logs ps mock-start mock-down

# venv + зависимости API
setup:
	python3 -m venv $(VENV)
	$(VENV)/bin/python -m pip install --upgrade pip
	$(VENV)/bin/pip install -r api/requirements.txt

# API в dev-режиме (uvicorn, 127.0.0.1:8100)
dev-api:
	$(PY) -m uvicorn app.main:app --app-dir api --host 127.0.0.1 --port 8100 --reload

# Фронт в dev-режиме (next dev, :3000; /api/* → 127.0.0.1:8100)
dev-web:
	cd web && npm run dev

# Мок vLLM (127.0.0.1:8000): /metrics + /v1/models
mock-vllm:
	$(PY) api/mock/vllm_mock.py --port 8000

# Тесты API (офлайн, без docker и без реальных источников)
test-api:
	cd api && .venv/bin/python -m pytest -q

# Миграции БД (alembic)
alembic:
	cd api && .venv/bin/alembic upgrade head

# ---- прод (docker compose; пути хоста и модель — из .env, пример: .env.example) ----

# Поднять стек (build + vllm + api + web)
start:
	$(COMPOSE) up -d --build

# Остановить и удалить контейнеры
down:
	$(COMPOSE) down

# Полный рестарт с пересборкой
rebuild: down start

# Логи (usage: make logs S=api|web|vllm)
logs:
	$(COMPOSE) logs -f $(S)

# Статус контейнеров
ps:
	$(COMPOSE) ps

# Стек с мок-вLLM вместо реального (не занимает GPU; usage: make mock-down)
mock-start:
	$(COMPOSE) $(MOCK_F) up -d --build

mock-down:
	$(COMPOSE) $(MOCK_F) down
