# PROJECT_MEMORY — llm-metrics

Одностраничное веб-приложение мониторинга vLLM-сервера: модель/GPU/система/стоимость/логи.
Спека: `TZ-vllm-metrics-app.md` (v0.2, согласована). Референс UI: тёмная тема, сайдбар-иконки, KPI «весь GPU» (W + VRAM) сверху, живой график 2 мин, сетка карточек GPU.

## Решения (согласовано с пользователем, 2026-07-13)

- Scope сессии: **F0–F3** (каркас, UI Модель/GPU/Система, Стоимость, Логи). F4 — не в этой сессии.
- Тестирование: **без docker локально** (docker/podman в dev-окружении нет) — бек `uvicorn`, фронт `next dev`. Docker Compose готов для деплоя на сервер с vLLM.
- **vLLM реальный: http://192.168.1.114:8000**, модель `qwen3.8-27b-dflash2` (Qwen3.8-27B-NVFP4-DFlash2, max_model_len 262144). В проде URL будет `http://127.0.0.1:8000` (compose на том же хосте).
- **Логи vLLM: файл `/mnt/storage/vllm/nohup.log`** (tail). В README — инструкция, как переключиться на docker-logs.
- Принятые рекомендации: **dev-мок vLLM** (`make mock-vllm`), **чистый asyncio** для poller'ов (без APScheduler).
- НЕ принято: SQL-миграции без Alembic → используем **Alembic** (ТЗ: alembic-совместимые SQL-схемы).

## Проверенные факты по vLLM-метрикам (curl :8000/metrics, 2026-07-13)

Настоящий набор V1-метрик подтверждён (выборка в `docs/vllm-metrics-sample.txt`):
- Гейджи: `num_requests_running`, `num_requests_waiting`(+`_by_reason`), `kv_cache_usage_perc` (0..1), `engine_sleep_state`
- Счётчики: `prompt_tokens_total`, `generation_tokens_total`, `prefix_cache_hits/queries_total`, `num_preemptions_total`, `request_success_total{finished_reason=stop|length|abort|error|repetition}` — **finish reasons ЕСТЬ**
- Histogram'ы: `time_to_first_token_seconds` (TTFT), `inter_token_latency_seconds` (ITL), `request_time_per_output_token_seconds` (TPOT), `e2e_request_latency_seconds`, `request_queue_time_seconds`, `request_prefill/decode_time_seconds`
- Имя модели — лейбл `model_name="..."` в метриках; `vllm:cache_config_info` (gauge с лейблами) доступен
- Версии vLLM нет нигде: метрика `vllm:version` отсутствует, заголовок `Server: uvicorn`, `info`-метрик нет. Отклонение от ТЗ §5.7: в «Проверке источников» показываем доступное (model id, max_model_len, cache_config) + «версия: n/a (не экспортируется этой сборкой)».

## Архитектура (из ТЗ)

- `web/` — Next.js (TS, Tailwind, shadcn/ui, uPlot), App Router, порт 3000, прокси `/api/*` → бек (rewrites)
- `api/` — FastAPI + Python 3.11+, порт 8100 (бинд 127.0.0.1 в проде), SQLite WAL, Alembic, poller'ы asyncio (vllm 5с / gpu 10с / system 10с / logs 1с), агрегатор (hourly/daily + tokens-диффы), cost engine, log tailer, SSE `/api/live`
- Конфиг `metrics.config` (YAML) по §3.3 ТЗ; тарифы версионированы в `settings`
- Схема БД — §4 ТЗ: `metric_samples`, `metric_hourly`, `metric_daily`, `tokens`, `log_entries`, `settings`, `gpu_devices`

## Команда / окружение

- Dev-хост: Linux, Python 3.14.4 (для prod-образа брать 3.11–3.12 по ТЗ), Node 22, GPU RTX 5070 Ti (для локального GPU-полинга)
- Целевой сервер: 192.168.1.114, vLLM на :8000
- Деплой: docker compose (web + api), volumes: `/data` (БД+конфиг), опц. `/mnt/storage/vllm` (лог), `/dev/nvidia*`

## Статус (обновлять)
- F0–F4 реализованы (2026-09-26): бек 102 теста (pytest), web build ✓ / eslint 0.
- F4 (выбранный scope; PDU отброшен — нет реального счётчика): алерты (движок 30с, Telegram webhook, журнал `alerts`, cooldown/restore, вкладка «Алерты»), экспорт CSV/PNG графиков, вкладка «Health», multi-модель (селектор в шапке, фильтр /api/model + /api/metrics по метке model, только raw/168ч).
- Деплой: docs/DEPLOY.md (инструкция); compose — web-сервис включён (ARG API_URL в web/Dockerfile, rewrite на этапе build), /mnt/storage/vllm:ro раскомментирован.
- Миграция 0002_alerts (alembic head); alerts seed в settings key=`alert_rules` (дефолты из кода, UI имеет приоритет над конфигом `alerts.*`).
- Нюанс web: установленная сборка uPlot 1.6.32 не имеет `toDataURL` — PNG-экспорт рисует график сам на canvas (metric-chart.tsx).
- Сквозной прогон F4: алерт src_vllm (offline→trigger→mock→resolve) ✓, /api/health/summary ✓, /api/model/models ✓, все 8 вкладок 200.
- api/dev.config.yaml — untracked-артефакт dev, в .gitignore.
- Зависимость: `test_cost.py` при параллельном запуске с F3 вешался (порт/БД?), в одиночку ок.

## Соглашения

- Минимальный diff; разбор без правок; коммиты — только по явной команде, конвенциональные, привязка к roadmap
- Todos каждого шага на русском; пункты «компиляция и тестирование» и «разрешение на коммит» всегда в todos
- Задачи и прогресс — `roadmap.md`; правила для агентов — `AGENTS.md`

## Сессия 2026-09-27 — F5: автономный vLLM, env-конфиг, docker-гигиена
Решения (согласовано с пользователем):
- vLLM: multi-stage Dockerfile на nvidia/cuda:12.8.0; 1CatAI/1Cat-vLLM head main (пин-коммит 14abfc27ee4e13cd2a9d1a8a882f36a629e5889a, ARG VLLM_REF) собирается в образе; stage-vllm/conda-env УБРАНЫ.
- vLLM слушает 127.0.0.1:8000 внутри контейнера, наружу не публикуется (только compose-сеть; api ходит по имени vllm).
- Логи vLLM: stdout → /var/log/vllm/vllm.log (общий volume vllm-logs, монтируется и в api) + ротация 50MB×4 в entrypoint. Docker-сокет и docker CLI из api УБРАНЫ (лог-источник — file).
- api: полный перевод конфига на ENV (yaml metrics.config.yaml убран). Список имён — .env.example / compose. VLLM_URL обязателен.
- api: JSON-логи (stdlib formatter), multi-stage Dockerfile, Telegram-webhook — docker secret /run/secrets/telegram_webhook с fallback env TELEGRAM_WEBHOOK.
- NVML остаётся в api (решение: один тонкий defensiv'ный коллектор, вынос в сервис не оправдан).
- Roles: vllm — только inference; api — агрегация метрик, БД, бизнес-правила; web — только UI.
- mem_limit api/web 2g, healthcheck'и, лог-ротация compose, no-new-privileges — уже были, сохраняем.
- Итог F5 (2026-09-27, до коммита): api — env-конфиг (config.py, VLLM_URL обязателен, дефолт VLLM_TIMEOUT_S=5), JSON-логи, multi-stage Dockerfile без docker CLI; pytest 102 passed. docker/vllm — multi-stage nvidia/cuda:12.8.0 (build=devel: clone 1CatAI/1Cat-vLLM $VLLM_REF + torch 2.10.0+cu128, TORCH_CUDA_ARCH_LIST=7.0; runtime=cudnn9-runtime + venv + gcc для triton JIT), 127.0.0.1:8000, логи→vllm-logs volume (/var/log/vllm/vllm.log) + ротация 50MB×4, UBU_MIRROR. compose: ports vllm убран, volume vllm-logs, secrets telegram_webhook (file ./secrets/telegram_webhook.txt — создать или закомментировать секцию), no-new-privileges убран. Makefile: −stage-vllm, all=install-toolkit up. metrics.config.example.yaml удалён.
- Фикс: web/src/app/health/ (stub healthcheck, ломал build: конфликт с (tabs)/health) → переименован в /healthz, web/Dockerfile HEALTHCHECK → /healthz. next build ✓.
- Осталось: build vLLM-образа на GPU-сервере (часы), docker compose config/прогон, коммит.
