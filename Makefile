# llm-metrics: dev-задачи (без docker; прод — docker compose, см. README в web/)
VENV  := api/.venv
PY    := $(VENV)/bin/python

.PHONY: setup dev-api dev-web mock-vllm test-api alembic

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
