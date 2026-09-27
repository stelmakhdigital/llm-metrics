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
- [x] 5.1 vLLM: сборка 1CatAI/1Cat-vLLM (main, пин-коммит 14abfc27) внутри multi-stage Dockerfile на nvidia/cuda:12.8.0; без stage-vllm/conda-env
- [x] 5.2 vLLM: bind 127.0.0.1:8000, убрать публикацию порта наружу (только compose-сеть); apt-зеркало UBU_MIRROR, apt-get update отдельным слоем
- [x] 5.3 vLLM: логи stdout → файл /var/log/vllm/vllm.log (общий volume) + простая ротация (50MB×4)
- [x] 5.4 api: полный перевод конфига на env (yaml убираем), VLLM_URL обязателен; список имён — .env.example
- [x] 5.5 api: убрать docker-сокет и docker CLI из compose/образа; лог-источник vLLM — file из volume vllm-logs
- [x] 5.6 api: JSON-логи (stdlib formatter), multi-stage Dockerfile, Telegram webhook через docker secret/env
- [x] 5.7 compose: роли зафиксированы (vllm=инференс, api=агрегация+БД, web=UI), mem_limit, healthcheck (есть), version уже убрана
- [x] 5.8 Makefile: убрать stage-vllm, обновить all/комментарии; .env.example под новые env; .dockerignore (вкл. docker/vllm)
- [x] 5.9 Документация: README, AGENTS.md, PROJECT_MEMORY.md, .env.example
- [ ] 5.10 Компиляция и тестирование: pytest api ✓, next build ✓, compose config ✓ (YAML); build vLLM-образа + прогон на GPU-сервере — ожидает
- [x] 5.11 Разрешение на коммит

## Сквозные
- [x] Компиляция и тестирование (pytest, build, прогон против 192.168.1.114)
- [x] Разрешение на коммит
