# Roadmap — llm-metrics

Пункты отмечаются `[x]` при выполнении и закреплении коммитом.

## F0 — Каркас
- [x] 0.1 Repo: структура, git, PROJECT_MEMORY/AGENTS/roadmap
- [x] 0.2 Конфиг `metrics.config` (YAML, §3.3) + загрузка/валидация
- [x] 0.3 БД: схема §4, Alembic, WAL; автообнаружение GPU в `gpu_devices`
- [x] 0.4 Коллекторы (asyncio): vLLM (5с, маппинг имён метрик, модель из лейблов), GPU pynvml (10с), система psutil (10с); устойчивость к сбоям + статусы источников
- [x] 0.5 Агрегатор: hourly/daily + tokens-диффы; ретенция (raw 168ч, hourly 180д)
- [x] 0.6 `/api/health`, `/api/metrics/{metric}`, `/api/overview`, `/api/gpus`, `/api/system`
- [x] 0.7 Docker Compose (web+api) + Dockerfile'ы + Makefile (dev/mock)
- [x] 0.8 Dev-мок vLLM (`make mock-vllm`)
- [x] 0.9 Проверка: 24ч-нагрузка (критерий: потери <5% точек — проверка ускоренной симуляцией + soak-тест)

## F1 — UI: Модель / GPU / Система
- [x] 1.1 Каркас Next.js: тема, сайдбар, шапка (модель, статус, переключатель периодов)
- [x] 1.2 Live (SSE `/api/live`) + переключатель периодов (5м/1ч/24ч/7дн/30дн/произвольный)
- [x] 1.3 Вкладка «Модель»: KPI + графики + сегментация по моделям
- [x] 1.4 Вкладка «GPU»: KPI «весь GPU» + живой график 2–5 мин + карточки GPU (VRAM-бары, троттлинг, ECC)
- [x] 1.5 Вкладка «Система»: CPU/RAM/диски/сеть/PSI/топ-5 процессов
- [x] 1.6 Критерий: Live 2с без просадок; графики по периодам (≤1500 точек за 30дн)

## F2 — Стоимость
- [x] 2.1 Cost engine: ∫P dt (сырые 7дн → hourly), токены × тарифы, unit costs
- [x] 2.2 Вкладка «Стоимость»: KPI, stacked токены/электричество, тренд 30дн, накопительная
- [x] 2.3 Версионирование тарифов (`settings`), PUT /api/settings/cost, пересчёт истории на лету
- [x] 2.4 Критерий: сверка с ручным расчётом ±1%

## F3 — Логи
- [x] 3.1 Log poller: file-tail (nohup.log) + docker-logs (конфигурируемый тип), парсинг уровня
- [x] 3.2 Индекс `log_entries`, ретенция 14дн, мини-график по уровням (stats)
- [x] 3.3 Вкладка «Логи»: фильтры, дни, страницы, экспорт txt/csv, копирование
- [x] 3.4 Live-хвост (SSE, автопрокрутка, пауза), автопарсинг vLLM stat-строк
- [x] 3.5 Критерий: 100k строк/день без деградации UI

## F4 — усиление (выбран scope: алерты, экспорт, health, multi-модель; PDU — нет реального счётчика)
- [x] 4.1 Алерты: движок правил (пороги + оффлайн источников, cooldown/длительность), Telegram webhook, журнал в БД, вкладка «Алерты» (активные, журнал, правила, тестовое уведомление)
- [x] 4.2 Экспорт CSV/PNG по активному графику
- [x] 4.3 Вкладка «Health»: сервис, источники, модель, GPU (ECC/троттлинг), диски, логи (ошибки), алерты
- [x] 4.4 Multi-модель: селектор модели в шапке, фильтр метрик модели по модели (историческое отслеживание смены)
- [x] 4.5 Тесты (pytest/build), сквозной прогон, README, коммит

## F5 — автономный vLLM, env-конфиг, docker-гигиена (сессия 2026-09-27)
- [x] 5.1 vLLM вынесен из docker: хост-процесс (свой скрипт ~/bin/work-fp8.sh) + обёртка scripts/vllm-host.sh (nohup+pid+stop/status), docker/vllm (in-image build) удалён после OOM-проблем сборки
- [x] 5.2 vLLM на хосте слушает 0.0.0.0:8000 (api — через host.docker.internal, extra_hosts host-gateway); фаервол при необходимости
- [x] 5.3 Лог vLLM — хост-файл $VLLM_LOG_DIR/vllm.log (nohup redirect) + logrotate (100M×4, copytruncate; make install-logrotate)
- [x] 5.4 api: полный перевод конфига на env (yaml убираем), VLLM_URL обязателен; список имён — .env.example
- [x] 5.5 api: убрать docker-сокет и docker CLI из compose/образа; лог-источник vLLM — host-файл (bind-ro каталога $VLLM_LOG_DIR)
- [x] 5.6 api: JSON-логи (stdlib formatter), multi-stage Dockerfile, Telegram webhook через docker secret/env
- [x] 5.7 compose: роли зафиксированы (vllm=инференс, api=агрегация+БД, web=UI), mem_limit, healthcheck (есть), version уже убрана
- [x] 5.8 Makefile: убрать stage-vllm, обновить all/комментарии; .env.example под новые env; .dockerignore (вкл. docker/vllm)
- [x] 5.9 Документация: README, AGENTS.md, PROJECT_MEMORY.md, .env.example
- [ ] 5.10 Прогон на GPU-сервере: make vllm-start + make start; проверка UI/метрик/логов; pytest api ✓, next build ✓, compose yaml ✓
- [x] 5.11 Разрешение на коммит

## F6 — доработка живого дашборда (сессия 2026-09-28, диагностика прод 192.168.1.114)
- [x] 6.1 Live SSE мёртв в браузере: Next.js gzip без flush на /api/live (+ /api/logs/live, счётчик алертов) → `compress: false` в web/next.config.ts
- [x] 6.2 GPU-периоды «нет данных»: parsePoints ждёт {ts,value}, API отдаёт [ts,value] → web/src/components/tabs/gpu/gpu-period.tsx
- [x] 6.3 GPU: gpu_sm_clock → gpu_clock_sm (имя метрики в БД)
- [x] 6.4 Модель: E2E-график e2e_p95 → e2e_latency_p95 (имя в БД) + docs/api-contracts.md
- [x] 6.5 prefix_hit_rate персистить в metric_samples (вкладчик vLLM + whitelist), график «Prefix cache hit rate» перестанет быть пустым
- [x] 6.6 Дефолтный порог алерта ttft_high: 2 с → 120 с (api/app/alerts/rules.py) + обновить живую настройку на 114
- [x] 6.7 Сборка web + pytest api
- [x] 6.8 Деплой на 114 (push → pull → rebuild) и проверка живого UI (Live, GPU 5м/7д, E2E, алерт)
- [x] 6.9 Разрешение на коммит

## F7 — аудит и фиксы расчётов/графиков (сессия 2026-09-28, после F6)
- [x] 7.1 downsample (query.py): min-max decimation — 24ч схлопывался до 7-20 точек → buckets = max_points//2
- [x] 7.2 KPI p50/p95 (model_api.py): квантили по смешанному списку p50+p95 → считать отдельно (ttft/tpot/e2e)
- [x] 7.3 Cost-engine: Σ_gpu P + baseline (кВт·ч и электро-стоимость были занижены ~×3)
- [x] 7.4 gpu-колонка в metric_hourly/daily: миграция + агрегатор + routes (per-GPU 7д/30д) + бэкфилл
- [x] 7.5 Фронт: кэш GpuPeriod без from/to — при смене периода были чужие данные (cacheKey + from:to)
- [x] 7.6 Тесты (pytest + build) и пересборка
- [x] 7.7 Деплой на 114 + числовая сверка (кВт·ч vs ручной ∫, per-GPU 7д ≠ идентичные, 24ч ≥1000 точек, p50)
- [x] 7.8 Разрешение на коммит

## Сквозные
- [x] Компиляция и тестирование (pytest, build, прогон против 192.168.1.114)
- [x] Разрешение на коммит
