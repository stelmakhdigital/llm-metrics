# Деплой llm-metrics (vLLM на хосте + api/web в docker)

Прод-деплой: **vLLM — процесс на хосте** (внешний скрипт `~/bin/work-fp8.sh`,
обёртка `scripts/vllm-host.sh`), **api + web — docker compose**.
Наружу только `web :3000`; api (8100) — только в compose-сети
(`/api/*` через Next.js-rewrite). api ходит в vLLM на хосте по
`http://host.docker.internal:8000` (extra_hosts: host-gateway).

## 1. Требования на сервере

* Docker + Compose + **nvidia-container-toolkit** (NVML-коллектор api видит
  все GPU хоста; установка — раздел 2, ~2 мин);
* NVIDIA-драйвер (проверить: `ls /usr/lib/x86_64-linux-gnu/libcuda.so.1`);
* **vLLM, работающий на хосте** (своё окружение/скрипт, например
  `~/bin/work-fp8.sh`), слушающий **`0.0.0.0:8000`**.
  Важно: `127.0.0.1` из контейнеров НЕ виден — api ходит в хост через
  IP docker-моста. Если порт 8000 не должен быть доступен из LAN —
  закрыть фаерволом (например, разрешить только подсеть docker-моста).
* Каталог логов на хосте (по умолчанию `/mnt/storage/vllm`) — лог vLLM
  пишется в `vllm.log` там же, api читает read-only.

## 2. Установка

```bash
# 1) nvidia-container-toolkit (разово, ~2 мин; нужен sudo)
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
  | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker && sudo systemctl restart docker
# проверка: docker run --rm --gpus all ubuntu:24.04 nvidia-smi

# 2) репозиторий + окружение
git clone <repo-url> llm-metrics && cd llm-metrics
cp .env.example .env && $EDITOR .env     # VLLM_URL / VLLM_SCRIPT / VLLM_LOG_DIR
mkdir -p data
# опционально: secrets/telegram_webhook.txt с URL Telegram-webhook
# (не нужен — закомментировать секцию secrets в docker-compose.yml)

# 3) образы api + web (сборка быстрая)
make build

# 4) vLLM на хосте: обёртка (nohup, лог → $VLLM_LOG_DIR/vllm.log)
make vllm-start          # = scripts/vllm-host.sh start
make install-logrotate   # ротация хост-лога: 100M×4, copytruncate

# 5) api + web
make start
```

Порядок 4↔5 не критичен: пока vLLM недоступен, api показывает его как
degraded и опрашивает дальше (retry), метрики появляются сами.

`.env` (пример: `.env.example`):

| Переменная | Значение |
|---|---|
| `VLLM_URL` | `http://host.docker.internal:8000` (vLLM на хосте) |
| `VLLM_SCRIPT` | путь к хост-скрипту vLLM (`~/bin/work-fp8.sh`) |
| `VLLM_LOG_DIR` | каталог логов на хосте (`/mnt/storage/vllm`) |
| `LOG_SOURCE_*` | `file`, `/var/log/vllm/vllm.log` (bind-ro хост-каталога) |
| `*PRICE_PER_M`, `RATE_PER_KWH_USD` | реальные тарифы |
| `TELEGRAM_WEBHOOK` (или secrets-файл) | URL (раздел 6) или пусто |

## 3. Запуск

```bash
make vllm-status         # vLLM на хосте (PID + хвост лога)
make start               # api + web (up -d без пересборки)
make ps                  # api: healthy, web: running
# пересборка после смены кода: make rebuild (= down + build + up)
```

Первая БД создаётся автоматически (авто-bootstrap схемы + alembic head).

## 4. Проверка

```bash
curl -s http://127.0.0.1:3000/api/health      # все источники online
make vllm-logs                 # хвост лога vLLM (host)
```

В браузере `http://<IP>:3000`:

* вкладки: Модель, GPU (все GPU хоста, включая не занятые vLLM), Система,
  Стоимость, Логи (строки vLLM из хост-файла `vllm.log`), Алерты,
  Health, Настройки;
* бейджи vLLM/GPU/SYS — зелёные.

## 4.1 Перенос на другой сервер (портативный деплой)

В репо жёстко закодированных путей нет — всё через `.env`. На новом хосте:

1. **Железо:** GPU с достаточной VRAM под vLLM, диск под `./data` и лог.
2. **Софт:** Docker + NVIDIA-драйвер + nvidia-container-toolkit
   (раздел 2, шаг 1) — 5 команд, разово.
3. **vLLM на хосте:** своё окружение и скрипт запуска (work-fp8.sh или
   аналог) — переносятся штатными средствами (conda-pack, git и т.п.);
   обязателен bind `0.0.0.0:8000` и лог в файл (обёртка делает redirect).
4. **Код:** `git clone`, `cp .env.example .env` + заполнить
   (VLLM_URL/VLLM_SCRIPT/VLLM_LOG_DIR), `make build && make vllm-start
   && make start`.
5. **Проверка:** раздел 4.

`./data` — скопировать, если хочется сохранить историю метрик.

## 5. Обновление vLLM

Обновление vLLM — на хосте, в вашем окружении (git/pip + смена модели в
скрипте). Для мониторинга достаточно: `make vllm-stop && make vllm-start`.
`VLLM_MODEL_NAME` в `.env` (опционально) — метка модели для истории,
по умолчанию берётся из `/v1/models`.

## 6. Telegram-алерты (разовая настройка)

1. @BotFather → `/newbot` → получить токен.
2. Отправить боту любое сообщение, затем:
   `curl https://api.telegram.org/bot<TOKEN>/getUpdates` → взять `chat.id`.
3. Webhook: `https://api.telegram.org/bot<TOKEN>/sendMessage?chat_id=<CHAT>`.
4. Указать в UI (вкладка «Алерты» → поле webhook → кнопка **Тест**) **или**
   в `TELEGRAM_WEBHOOK` в `.env` / файле `secrets/telegram_webhook.txt` +
   `docker compose restart api`.
   UI-значения имеют приоритет (хранятся в БД).

Дальше правила/пороги/уровни редактируются в той же вкладке;
«Сбросить правила» — значения по умолчанию.

## 7. Эксплуатация

```bash
# обновление кода
git pull && make rebuild

# vLLM на хосте
make vllm-stop / vllm-start / vllm-status / vllm-logs

# смена конфига (URL vLLM, источники логов, интервалы, ретенция)
nano .env
docker compose restart api

# логи процесса
docker compose logs -f api
make vllm-logs                       # лог vLLM (host)

# миграции схемы (обычно не нужны: авто-bootstrap + идемпотентная схема)
docker compose exec api python -m alembic upgrade head
```

Тарифы (Настройки/Стоимость) и алерты (Алерты) — только через UI:
хранятся в БД, рестарт не нужен, история пересчитывается на лету.

## 8. Что где хранится

* `./data/metrics.db` (+ WAL-файлы) — все данные (метрики, токены, логи,
  настройки, алерты). Бэкап = копия файла (желательно при остановленном api).
* `$VLLM_LOG_DIR/vllm.log` — лог vLLM на хосте (ротация logrotate, 100M×4).
* `.env` — конфиг (URL, интервалы, ретенция, дефолт тарифов/алертов);
  `secrets/` — Telegram-webhook (не в git).
* Ретенция: raw 168 ч, hourly 180 дн, daily безлимит, логи 14 дн
  (настраивается в `.env`).

## 9. Архитектура и изоляция

* **vLLM (host)** — только инференс, не знает про мониторинг. Слушает
  `0.0.0.0:8000` (единственное, что нужно открыть наружу; при
  необходимости — фаервол, чтобы порт был виден только из docker-моста).
* **api** — весь мониторинг: метрики vLLM (`host.docker.internal:8000`),
  NVML (все GPU хоста), лог-индексатор vLLM (bind-ro хост-каталога),
  БД, алерты. 8100 наружу не публикуется.
* **web** — только UI, `/api/*` rewrite на api, напрямую к vLLM не ходит.

NVML читаем в api: один процесс видит все GPU хоста (включая не занятые
vLLM); toolkit инжектит libnvidia-ml и устройства.

Логи vLLM: хост-обёртка пишет `vllm.log` (nohup redirect), logrotate
(copytruncate) режет по 100M×4, api читает файл read-only (тейлер
переносит ротацию: смена inode / уменьшение размера). Docker-сокет не нужен.
