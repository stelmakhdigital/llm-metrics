# PROJECT_MEMORY — llm-metrics

Одностраничное веб-приложение мониторинга vLLM-сервера: модель/GPU/система/стоимость/логи.
Спека: `TZ-vllm-metrics-app.md` (v0.2, согласована). Референс UI: тёмная тема, сайдбар-иконки, KPI «весь GPU» (W + VRAM) сверху, живой график 2 мин, сетка карточек GPU.

## Решения (согласовано с пользователем, 2026-07-13)

- Scope сессии: **F0–F5** (каркас, UI Модель/GPU/Система, Стоимость, Логи, прод-операционка: автономный vLLM, env-конфиг, docker-гигиена).
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
- **Конфиг: только env** (F5, 2026-07-20): `AppConfig` строится из env (`api/app/config.py`), YAML/`metrics.config.example.yaml` удалены. Обязателен `VLLM_URL` (без него API падает с понятной ошибкой); остальные переменные — с дефолтами. Шаблон — `.env.example`. Секреты (Telegram webhook) — через docker-compose `secrets:` → файл `secrets/telegram_webhook.txt` → env `TELEGRAM_WEBHOOK`.
- Схема БД — §4 ТЗ: `metric_samples`, `metric_hourly`, `metric_daily`, `tokens`, `log_entries`, `settings`, `gpu_devices`

## Структура кода

```
api/
  app/main.py               # FastAPI app, lifespan: db init/migrate, pollers, retention, alerts
  app/db.py                 # sqlite WAL, PRAGMA, migrate_from_sql / alembic stamp
  app/aggregator.py         # hourly/daily агрегатор, tokens-диффы, cost
  app/retention.py          # очистка по RetentionConfig
  app/collector.py          # poll loop, retry/backoff, SourceState, SourceStatus
  app/cost.py               # PricingProfile, cost-per-token, per-model totals
  app/sse.py                # ring buffer + subscribe (asyncio)
  app/collectors/           # vllm.py (HTTP), gpu.py (pynvml), system.py (psutil), logs/
  tests/                    # 102 pytest
web/
  src/components/
    layout/  (app-shell, sidebar, header, live-indicator)
    ui/      (shadcn: card, badge, switch, skeleton, tooltip, table)
    charts/  (uplot.tsx — общий uPlot-обёртка, kpi.tsx)
    model/ gpu/ system/ cost/ logs/
  src/app/(tabs)/model|gpu|system|cost|logs
  src/lib/    (api.ts, utils.ts, time.ts, use-live.ts, sse.ts)
  next.config.ts             # rewrites /api/* → BACKEND
  public/                     # uPlot bundle (npm uplot)
TZ-vllm-metrics-app.md         # ТЗ (спека)
PROJECT_MEMORY.md              # этот файл
```

## Интеграция vLLM / GPU / логи

- **vLLM** (`collectors/vllm.py`): `GET {vllm_url}/metrics` (Prometheus text), парсит гейджи/счётчики/histogram'ы; p95 из buckets интерполяцией (§5.2 ТЗ). Name mapping: `num_requests_running`→`running_requests` и т.д. (см. `_GAUGES`/`_COUNTERS`/`_HISTOGRAMS`).
- **GPU** (`collectors/gpu.py`): pynvml, init с retry, `vllm_gpu`/`gpu_power`/`gpu_mem_total`/`gpu_mem_used` per device. Fallback: `mem_limit` на container.
- **Логи** (`collectors/logs/tailer.py`): tail файла (seek end, poll), index → SQLite `log_entries`, search API, retention. В dev-мок: `make mock-vllm` пишет лог-файл.
- **Alerts** (`collectors/logs/alerts.py`): правила (regex → severity → cooldown), dedup key = `rule_id + line_hash`, Telegram webhook.

## Деплой (схема от 2026-07-20: vLLM на хосте, в docker — только api + web)

- `docker-compose.yml`: `api` (env-конфиг, volumes: data + `${VLLM_LOG_DIR}:/var/log/vllm:ro`, `extra_hosts: host-gateway`, `mem_limit 2g`, NVML через nvidia-toolkit), `web` (build, port 3000). vllm-контейнер УБРАН.
- **vLLM — хост-процесс**: внешний скрипт (на сервере `~/bin/work-fp8.sh`), обёртка `scripts/vllm-host.sh start|stop|status` (nohup, pid-файл, лог append → `$VLLM_LOG_DIR/vllm.log`). **Обязателен bind 0.0.0.0:8000** (127.0.0.1 из контейнеров не виден); порт 8000 — единственное открытое наружу (фаервол при необходимости).
- api → vLLM: `VLLM_URL=http://host.docker.internal:8000`. Лог vLLM: host-файл, tailer понимает ротацию (inode/size); ротация — logrotate copytruncate 100M×4 (`deploy/logrotate-vllm.conf`, `make install-logrotate`).
- `make install` — первичный деплой (.env + secrets + toolkit + build + up, в конце подсказывает vllm-start/install-logrotate). `make vllm-start|stop|status|logs` — vLLM на хосте. `make build-bg` — build api/web в фоне (build.log).
- `.env` — весь конфиг (VLLM_URL обязателен; VLLM_SCRIPT, VLLM_LOG_DIR — пути хоста). Секреты в `secrets/telegram_webhook.txt`.
- Документация: `docs/DEPLOY.md` (инструкция по деплою), `README.md` (dev + прод), `AGENTS.md` (правила работы).

## Ф5: прод-операционка (2026-07-20)

### Смена схемы (2026-07-20, после OOM-сбоев сборки vLLM-обраба)
- **vLLM вынесен из docker** (по решению пользователя): хост-процесс через обёртку `scripts/vllm-host.sh` над `~/bin/work-fp8.sh` (nohup+pid+stop/status, лог → `$VLLM_LOG_DIR/vllm.log`); `docker/vllm/` (in-image build) **удалён** (`9a3673b`). Причина: OOM-киллер при CUDA-компиляции даже на -j4 (RAM не хватает на несколько nvcc по ~8-10 ГБ).
- api ходит в vLLM через `host.docker.internal:8000` (host-gateway); скрипт vLLM обязан слушать 0.0.0.0. Лог vLLM — host-файл, api читает bind-ro; logrotate copytruncate 100M×4 (`make install-logrotate`).
- Изначальная версия (in-image build, пин SHA 14abfc27, MAX_JOBS) — в git-истории, актуальна только как референс: setup.py форка читает `MAX_JOBS` (не VLLM_MAX_JOBS).

### Решения (согласовано с пользователем)
- **vLLM — автономный**: сборка 1CatAI/1Cat-vLLM из исходников **внутри образа** (не из conda-окр. хоста); base `nvidia/cuda:12.8.0-devel` (build) / `-cudnn9-runtime` (runtime); `git fetch --depth 1 origin <SHA>` по SHA (git clone --branch не принимает raw SHA); пин `14abfc27ee4e13cd2a9d1a8a882f36a629e5889a` (head main, 2026-07-14) — переопределяется `--build-arg VLLM_REF=...`.
- **Конфиг API — только env**: YAML удалён, `AppConfig` из env; `VLLM_URL` обязателен; 23 переменные (см. `.env.example`).
- **Docker socket убран**: API читает лог vLLM из shared volume-файла (`LOG_SOURCE_TYPE=file`, дефолт `LOG_SOURCE_NAME=vllm`, `LOG_SOURCE_PATH=/logs/vllm.log`); vLLM пишет в `/var/log/vllm/vllm.log` (volume `vllm-logs`, rotation 50MB×4 в entrypoint).
- **vLLM не публичный**: в compose порты наружу не публикуются (внутри — 127.0.0.1:8000).
- **NVML остаётся в API** (не отдельный сервис): тонкий защитный `collectors/gpu.py`, изоляция — poll_loop + mem_limit.
- **Доп. гигиена**: multi-stage api/web, .dockerignore (api/web/корень), `secrets:` compose (telegram_webhook), healthcheck web → /healthz (health/page.tsx → healthz/page.tsx, конфликт с (tabs)/health), JSON-логи API (stdlib `_JsonFormatter` в main.py, без новых зависимостей), UBU_MIRROR apt-зеркала, apt-get update отдельным слоем.
- **Makefile**: `stage-vllm` удалён; `all: install-toolkit up`; `make install` (первичный деплой), `make build-bg` (nohup → build.log).

### Коммиты F5
- `e4a2f76` vLLM-образ из исходников (multi-stage, nvidia/cuda:12.8.0)
- `1bf3f5b` api: конфиг из env (YAML удалён), JSON-логи, multi-stage
- `aece6f9` web: healthcheck /healthz (конфликт с вкладкой health)
- `39ffbed` compose без публикации vLLM, common том логов, secrets; Makefile без stage-vllm
- `3908f25` docs: F5 в README/AGENTS/DEPLOY; roadmap F5, PROJECT_MEMORY
Фиксы: `65bc8e8` (fetch по SHA), `bbfa566` (COPY mock в api-образ), `73d0cce` (VLLM_MAX_JOBS, build-bg), `afeebde` (build-bg под /bin/sh, make install), `830dde6` (MAX_JOBS — setup.py форка читает MAX_JOBS, не VLLM_MAX_JOBS).

### Не закрыто
- [ ] 5.10 прогон на GPU-сервере: `make vllm-start` + `make start`, проверка UI/метрик/логов (схема — vLLM на хосте).
- [ ] 5.11 обновить roadmap/memory: F5 закрыт (после 5.10).

## Стек

- `fastapi`, `uvicorn[standard]`, `httpx`, `prometheus-client` (parser), `pynvml`, `psutil`, `aiosqlite`, `alembic`, `pydantic`, `pydantic-settings`
- `next`, `react`, `react-dom`, `tailwindcss`, `uPlot`, shadcn/ui, `lucide-react`
- Python 3.11+ (venv `.venv` в api/), Node 22 (web/)

## Состояние

- **F0–F4 выполнены** (F4: стоимость + логи, 2026-09-26): 102 pytest (api), web build ✓ / eslint 0.
- **F5 (2026-07-20)**: env-конфиг, docker-гигиена, security, JSON-логи, healthchecks, secrets; vLLM — на хосте (обёртка scripts/vllm-host.sh), в docker только api+web. Осталось: прогон на GPU-сервере (5.10).
- Осталось: 5.10 (прогон на GPU-сервере), 5.11 (закрыть roadmap).
- Ограничения: без docker локально (test через pytest + next build).
- vLLM-форк: 1CatAI/1Cat-vLLM (SM70-оптимизации, NVFP4, DFlash2, FP8-инфра) — установлен в conda-окружении хоста; docker-сборка (docker/vllm) отменена после OOM.

## F8 (2026-09-28): аудит «Стоимости» и «Модели»
- Cost: cum += day_total каждый час → «сегодня» $153 при $37 (фикс: почасовые приросты); prev счётчика только в своём бакете → потеря ~10с/час (фикс: prev из прошлого бакета, точка ts==граница — прошлого часа); partial-час из tokens — проратация; «к платёжке» — по суткам для завершённых дней; тариф mid-hour; no-op PUT тарифов не создаёт версию. Live: 30д-запрос 1/5 мин; пустые дни — разрывы; stacked; подписи: «1k completion (вся стоимость)», «сегодня — с 00:00 UTC», мощность; форма тарифов: пустое поле = невалидно.
- Ось X: русские метки (UPlotChart fmtAxisTime: ≤36ч HH:MM, ≤14д ДД.ММ ЧЧ:ММ, больше ДД.ММ).
- Live prefix_hit_rate — rolling 60с (collector _pfx_hist), fallback 5с/null.
- «Модель»: prompt tok/s ВКЛЮЧАЕТ cached prefix (prompt_tokens_total = local_cache_hit + local_compute) — пики 40k+ при «Avg prompt throughput» в логах ≈0: это семантика vLLM, не баг (ТЗ §5.2 фиксирует rate(prompt_tokens_total)). Если нужна «вычислительная» скорость — rate(prompt_tokens_by_source_total{source="local_compute"}). TTFT/TPOT/ITL/E2E — по кумулятивным histogram'ам vLLM (сброс при рестарте).

## F7 (2026-09-28): аудит и фиксы расчётов/графиков
- Находи и фиксы (prod 114): downsample (24ч было 7-20 точек → buckets=max_points//2); KPI p50/p95 — по отдельным сериям (ttft_p50 был завышен 2.4x); cost-engine Σ_gpu P + baseline (кВт·ч были занижены ~×3, avg_power_w 279→~860 Вт); gpu-колонка в metric_hourly/daily (миграция 0003 + бэкфилл, per-GPU 7д/30д); фронт cacheKey GpuPeriod + from/to. Бонус: баг alembic env.py — без commit после run_migrations версия-штамп откатывалась (DDL/DML приживались, alembic_version застревал).
- Деплой: на 114 `docker exec -e METRICS_DB_URL=sqlite:////data/metrics.db llm-metrics-api alembic upgrade head` (alembic.ini url относительный, env обязателен).
- Косметика, сознательно НЕ чинили: время на осях/карах — часовой пояс браузера (не сервера, ТЗ §5.1); подпись «KV cache (средняя)» = последнее значение; uPlot пересоздаётся на каждый SSE-пакет (не append).

## F6 (2026-09-28): доработка живого дашборда
- Диагностика прод (192.168.1.114): Live SSE ломался gzip-компрессией Next (fix: `compress: false`); GPU-периоды — parsePoints ждал {ts,value} вместо кортежей; имена метрик: `gpu_clock_sm` (не gpu_sm_clock), `e2e_latency_p95` (не e2e_p95); prefix_hit_rate не персистился; порог ttft_high 2с→120с. Детали — roadmap.md F6.
- Деплой: прод-репо /home/arkalaust/Code/llm-metrics на 192.168.1.114 (git pull + docker compose build), доступ `ssh -p 2214 arkalaust@192.168.1.114`.

## Следующие шаги (roadmap.md → Ф5)

1. На GPU-сервере: `git pull` (схема vLLM-на-хосте, `9a3673b`); проверить что в `~/bin/work-fp8.sh` bind **0.0.0.0** (не 127.0.0.1).
2. Заполнить `.env` (VLLM_URL=http://host.docker.internal:8000, VLLM_SCRIPT, VLLM_LOG_DIR) и `secrets/telegram_webhook.txt`.
3. `make vllm-start` (хост-обёртка) + `make start` (api+web); `make install-logrotate` (разово).
4. `make ps` / `make vllm-status` / `curl 127.0.0.1:3000/api/health` — все healthy, vLLM online, логи идут.
5. Обновить roadmap.md / PROJECT_MEMORY.md: отметить Ф5 выполненным.
