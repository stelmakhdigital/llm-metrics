# AGENTS.md — правила работы в репо llm-metrics

## Контекст
- Проект: веб-мониторинг vLLM-сервера. ТЗ: `TZ-vllm-metrics-app.md` (источник правды), контекст сессии: `PROJECT_MEMORY.md`, план/прогресс: `roadmap.md`.
- Stack: FastAPI (Python 3.11+, `api/`), Next.js + TS + Tailwind + shadcn/ui + uPlot (`web/`), SQLite WAL + Alembic, docker compose для прод-деплоя (наружу только web :3000; vLLM — хост-процесс, api ходит в него через `host.docker.internal:8000`, скрипт vLLM слушает 0.0.0.0; конфиг api — env из `.env`).
- UI — русский. Времена в БД — epoch/UTC, отображение — локальное время сервера.

## Структура
```
api/          # FastAPI: app, collectors/, storage, cost, logs, sse
  migrations/ # alembic
web/          # Next.js App Router; app/(tabs)/model|gpu|system|cost|logs|settings
docs/         # выборка метрик vLLM, инструкции
.env.example  # весь конфиг api (env); secrets/ — Telegram-webhook (в git не попадает)
docker-compose.yml, Dockerfile.*
```

## Команды (dev, без docker)
- `make dev-api` / `make dev-web` — uvicorn + next dev
- `make mock-vllm` — мок vLLM-метрик (порт 8000) для отладки
- Тесты: `cd api && pytest` (или `make test-api`); web — `cd web && npm run build` (build+lint+types; test-скрипта нет)

## Ключевые инварианты
- Сбой источника не роняет сбор остальных; пропуски данных — разрывы в графиках, не 0.
- Тарифы — отдельная версионированная сущность (`settings`), стоимость выводится на лету.
- Метрики vLLM хранятся с меткой `model` (историческое отслеживание смены модели).
- p95 из histogram — интерполяцией по buckets (метод из ТЗ §5.2).
- Минимальный diff: не трогать несвязанное, не переформатировать.
- Коммиты: только по явной команде; конвенциональные (fix/feat/refactor/docs), один коммит = одна единица, привязка к пункту roadmap.md.
