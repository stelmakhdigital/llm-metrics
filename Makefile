# llm-metrics: dev-задачи (без docker) + прод (docker compose)
VENV     := api/.venv
PY       := $(VENV)/bin/python
# docker compose (v2) если есть, иначе docker-compose (v1); переопределяется: make COMPOSE=...
COMPOSE  ?= $(shell docker compose version >/dev/null 2>&1 && echo "docker compose" || echo docker-compose)
MOCK_F   := -f docker-compose.yml -f docker-compose.mock.yml

.PHONY: setup dev-api dev-web mock-vllm test-api alembic
.PHONY: start down rebuild logs ps mock-start mock-down stage-vllm build

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

# Впечь conda-env 1Cat-vLLM + исходники в контекст сборки (hard-links, ноль
# доп. дисков; нужен .env с VLLM_ENV_DIR/VLLM_SRC_DIR; после обновления env
# повторить). Запускать до первого `make build`/`make start`.
stage-vllm:
	@set -e; \
	ENV=$$(grep '^VLLM_ENV_DIR=' .env | cut -d= -f2); \
	SRC=$$(grep '^VLLM_SRC_DIR=' .env | cut -d= -f2); \
	echo "stage-vllm: $${ENV} → docker/vllm/.build-env"; \
	rm -rf docker/vllm/.build-env docker/vllm/.build-src; \
	cp -al "$${ENV}" docker/vllm/.build-env; \
	cp -al "$${SRC}" docker/vllm/.build-src; \
	echo "stage-vllm: ok (если cp -al упал: разные ФС — замени на cp -a)"

# Пересобрать все образы (vllm тяжёлый: ~15 ГБ контекста)
build:
	$(COMPOSE) build

# Поднять стек (без пересборки; образы — make build)
start:
	$(COMPOSE) up -d

# Первый деплой/после смены кода: образы + запуск
up: build start

# Остановить и удалить контейнеры
down:
	$(COMPOSE) down

# Полный рестарт с пересборкой
rebuild: down up

# Логи (usage: make logs S=api|web|vllm)
logs:
	$(COMPOSE) logs -f $(S)

# Статус контейнеров
ps:
	$(COMPOSE) ps

# Стек с мок-вLLM вместо реального (не занимает GPU; usage: make mock-down)
mock-start:
	$(COMPOSE) $(MOCK_F) up -d --build api web vllm-mock

mock-down:
	$(COMPOSE) $(MOCK_F) down
