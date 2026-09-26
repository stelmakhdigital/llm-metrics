# Деплой llm-metrics (docker compose)

Прод-деплой на сервере с vLLM: `web :3000` наружу, API — только в
compose-сети (`/api/*` проксируется Next.js-rewrite'ом).

## 1. Требования на сервере

* Docker + Compose plugin;
* NVIDIA-драйвер (`nvidia-smi` работает) — для NVML/GPU-метрик;
* vLLM запущен на `:8000`;
* (опц.) лог-файл vLLM, например `/mnt/storage/vllm/nohup.log`.

## 2. Установка

```bash
git clone <repo-url> llm-metrics && cd llm-metrics
cp metrics.config.example.yaml metrics.config.yaml
mkdir -p data
```

Отредактировать `metrics.config.yaml`:

| Ключ | Значение для прода |
|---|---|
| `sources.vllm.url` | `http://127.0.0.1:8000` |
| `sources.logs[].type/path` | `file` + реальный путь к лог-файлу (или `type: docker`, `container: vllm`) |
| `storage.sqlite_path` | `/data/metrics.db` (по умолчанию) |
| `cost.*` | реальные тарифы: $/кВт·ч, baseline W, $/1M токенов prompt/completion |
| `alerts.telegram_webhook` | URL (раздел 5) или `null` — задать в UI |

Примечания:

* Монтирование `/mnt/storage/vllm:ro` для file-источника логов уже
  раскомментировано в `docker-compose.yml` (для docker-источника не нужно).
* Больше 1 GPU: добавить в `devices:` секции api — `/dev/nvidia1`, `/dev/nvidia2`, …

## 3. Запуск

```bash
docker compose up -d --build
docker compose ps        # api: healthy, web: running
```

Первая БД создаётся автоматически (авто-bootstrap схемы + alembic head).

## 4. Проверка

```bash
curl -s http://127.0.0.1:3000/api/health        # через web-прокси
```

В браузере `http://<IP-сервера>:3000`:

* 8 вкладок: Модель, GPU, Система, Стоимость, Логи, Алерты, Health, Настройки;
* бейджи источников vLLM/GPU/SYS — зелёные (сводно — вкладка «Health»);
* «Логи»: идут строки, мини-график по уровням;
* «Алерты»: правила по умолчанию, колокольчик в шапке — 0;
* графики/стоимость наполняются со временем: raw — каждые 5 с,
  hourly — после первой часовых границы, daily — к первой полуночи UTC.

## 5. Telegram-алерты (разовая настройка)

1. @BotFather → `/newbot` → получить токен.
2. Отправить боту любое сообщение, затем:
   `curl https://api.telegram.org/bot<TOKEN>/getUpdates` → взять `chat.id`.
3. Webhook: `https://api.telegram.org/bot<TOKEN>/sendMessage?chat_id=<CHAT>`.
4. Указать в UI (вкладка «Алерты» → поле webhook → кнопка **Тест**) **или**
   в `alerts.telegram_webhook` конфига + `docker compose restart api`.
   UI-значения имеют приоритет над конфигом (хранятся в БД).

Дальше правила/пороги/уровни редактируются в той же вкладке;
«Сбросить правила» — значения по умолчанию.

## 6. Эксплуатация

```bash
# обновление кода
git pull && docker compose up -d --build

# смена конфига (URL vLLM, источники логов, интервалы, ретенция)
nano metrics.config.yaml
docker compose restart api

# логи процесса
docker compose logs -f api

# миграции схемы (обычно не нужны: авто-bootstrap + идемпотентная схема)
docker compose exec api python -m alembic upgrade head
```

Тарифы (Настройки/Стоимость) и алерты (Алерты) — только через UI:
хранятся в БД, рестарт не нужен, история пересчитывается на лету.

## 7. Что где хранится

* `./data/metrics.db` (+ WAL-файлы) — все данные (метрики, токены, логи,
  настройки, алерты). Бэкап = копия файла (желательно при остановленном api).
* `./metrics.config.yaml` — конфиг (URL, интервалы, ретенция, дефолт тарифов/алертов).
* Ретенция: raw 168 ч, hourly 180 дн, daily безлимит, логи 14 дн
  (настраивается в конфиге/`storage.retention`).
