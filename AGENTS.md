# AGENTS.md — правила для ИИ-агентов (и напоминание для людей)

Коротко: как работать в репо llm-metrics. Подробности процесса — `CONTRIBUTING.md`,
API/конфиг — `docs/`.

## Команды

- `make test-api` — тесты API (обязательно перед коммитом);
- `cd web && npm run build` — сборка web (обязательно при правках web/);
- dev: `make dev-api` / `make dev-web` / `make mock-vllm`;
- деплой: `git push` → на сервере `git pull && make rebuild`.

## Структура

```
api/          # FastAPI: collectors/(vllm|gpu|system), storage, aggregator,
              # cost/, logs/, alerts/, query.py, model_api.py, api/ (роутеры)
  migrations/ # alembic
web/          # Next.js App Router; app/(tabs)/model|gpu|system|cost|logs|...
              # общие: components/tabs/common.tsx (ChartCard/KpiCard),
              # components/charts/UPlotChart.tsx, lib/ (periods, model-context)
docs/         # DEPLOY (запуск), CONFIG (.env + скрипты vLLM), api-contracts
```

## Инварианты (не нарушать)

1. **Пропуски данных — разрывы на графиках, никогда не 0** (и в API: null/отсутствие).
2. **Тарифы — версионированная сущность** (settings); стоимость выводится на
   лету; no-op сохранение не создаёт версию.
3. **Метрики vLLM — с меткой `model`** (в сырых данных И в hourly/daily
   агрегатах); смена модели = отдельная история.
4. p95 из histogram — линейная интерполяция по buckets.
5. Сбой одного источника не роняет остальные (status: online/degraded/offline).
6. Время в БД — epoch/UTC; отображение — локальное время браузера.

## Стиль

- Минимальный diff: не трогать несвязанное, не переформатировать чужое.
- Коммиты: `fix/feat/refactor/docs/chore` + русский текст; 1 коммит = 1 единица;
  `Closes #N` — обязательна, если есть issue.
- **Коммит — только по явной команде человека.** Исполнять: правки +
  тесты + отчёт (что изменил, как проверил), коммит ждать.
- Не деплоить без команды.
- UI — русский.

## Работа по issue

Брать issue только с лейблом `agent:ready` (чеклист «Приёмка» заполнен).
Порядок: `agent:in-progress` → работа строго по секциям issue → PR по
шаблону (все пункты Приёмки) → `agent:needs-review`. Вне секций issue
не додумывать; сомнения — в вопрос человеку в issue, не в код.
