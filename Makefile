# llm-metrics: dev-задачи (без docker) + прод (docker compose)
VENV     := api/.venv
PY       := $(VENV)/bin/python
# docker compose (v2) если есть, иначе docker-compose (v1); переопределяется: make COMPOSE=...
COMPOSE  ?= $(shell docker compose version >/dev/null 2>&1 && echo "docker compose" || echo docker-compose)
MOCK_F   := -f docker-compose.yml -f docker-compose.mock.yml

.PHONY: setup dev-api dev-web mock-vllm test-api alembic
.PHONY: start down rebuild logs ps mock-start mock-down build build-bg install install-toolkit gpu-check all

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

# nvidia-container-toolkit: разово, нужен sudo (Ubuntu/Debian)
install-toolkit:
	@command -v nvidia-ctk >/dev/null 2>&1 && { echo "toolkit уже установлен"; exit 0; } || \
	{ sudo rm -f /etc/apt/sources.list.d/nvidia-container-toolkit.list \
	    /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg; \
	  curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
	    | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg && \
	  curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
	    | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
	    | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list >/dev/null && \
	  sudo apt-get update && \
	  sudo apt-get install -y nvidia-container-toolkit && \
	  sudo nvidia-ctk runtime configure --runtime=docker && \
	  sudo systemctl restart docker && \
	  echo "toolkit установлен, docker перезапущен"; }

# Проверка GPU-инжекта (нужен образ ubuntu:24.04, подтянется сам)
gpu-check:
	docker run --rm --gpus all ubuntu:24.04 nvidia-smi

# Полный деплой с нуля: toolkit + образы + запуск.
# Идемпотентно (повторный запуск безопасен).
# Для повседневного старта достаточно: make start
all: install-toolkit up

# Параллелизация CUDA-компиляции vLLM (нужна RAM ~2-4 ГБ на nvcc-процесс).
# Если сборка упала OOM ("Killed"/exit 137 в build.log) — уменьшить: VLLM_MAX_JOBS=2.
VLLM_MAX_JOBS ?= 4

# Пересобрать все образы (контексты сборки маленькие — сборка быстрая).
# Пин версии vLLM: docker compose build --build-arg VLLM_REF=<git sha> vllm
build:
	$(COMPOSE) build --build-arg VLLM_MAX_JOBS=$(VLLM_MAX_JOBS)

# Тот же build, но в фоне (переживает обрыв ssh); прогресс: tail -f build.log.
# Если сборка упала: grep -nE "error:|Error|Killed|status 137" build.log | tail
build-bg:
	nohup $(COMPOSE) build --progress=plain --build-arg VLLM_MAX_JOBS=$(VLLM_MAX_JOBS) >build.log 2>&1 &
	echo "build в фоне (PID $$!); следите: tail -f build.log"

# Полный первичный деплой на новом сервере: .env + secrets + toolkit + образы + запуск.
# Идемпотентно; после создания .env/secrets их заполнить под себя.
install:
	@test -f .env || { cp .env.example .env; echo "создан .env — заполнить MODELS_DIR/MODEL/VLLM_URL под свой сервер"; }
	@test -f secrets/telegram_webhook.txt || { mkdir -p secrets; printf 'https://api.telegram.org/bot<TOKEN>/sendMessage?chat_id=<CHAT>' > secrets/telegram_webhook.txt; echo "создан плейсхолдер secrets/telegram_webhook.txt — заменить на реальный webhook (или закомментировать секцию secrets: в docker-compose.yml)"; }
	@$(MAKE) install-toolkit
	@$(MAKE) up

# Поднять стек (без пересборки; образы — make build)
start:
	@test -f secrets/telegram_webhook.txt || echo "ВНИМАНИЕ: secrets/telegram_webhook.txt не найден — создайте файл (URL Telegram-webhook) или закомментируйте секцию secrets: в docker-compose.yml"
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
