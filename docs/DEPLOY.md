# Деплой llm-metrics (docker compose)

Прод-деплой: **vLLM (1Cat-vLLM, 4xV100 TP=4) + api + web** одним
`docker compose up -d --build`. Наружу только `web :3000` (vLLM наружу
НЕ публикуется — api ходит в него по имени в compose-сети);
API (8100) — только в compose-сети (`/api/*` через Next.js-rewrite).

## 1. Требования на сервере

* Docker + Compose + **nvidia-container-toolkit** (GPU-библиотеки и
  устройства инжектятся в контейнеры автоматически;
  установка — раздел 2, ~2 мин);
* NVIDIA-драйвер (проверить: `ls /usr/lib/x86_64-linux-gnu/libcuda.so.1`);
* каталог моделей + сама модель (~29 ГБ) — `MODELS_DIR` / `MODEL` в `.env`;
* образ `llm-metrics-vllm:latest` — собирается из исходников (контекст сборки
  маленький, сборка быстрая); пин версии vLLM:
  `docker compose build --build-arg VLLM_REF=<git sha> vllm`.

> vLLM-контейнер полностью самодостаточен: из хоста нужны только модель
> (mount), GPU (toolkit) и общий лог-том `vllm-logs` (логи → api).

## 2. Установка

```bash
# 1) nvidia-container-toolkit (разово, ~2 мин; нужен sudo)
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
  | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
  sed 's#deb https://#deb [signed-by=/usr/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker && sudo systemctl restart docker
# проверка: sudo docker run --rm --gpus all ubuntu:24.04 nvidia-smi

# 2) остановить bare-vLLM (занимает GPU 0-3 и :8000)
#    (процесс от ~/bin/work-fp8.sh; Ctrl-C в терминале или kill <pid>)

# 3) репозиторий + окружение
git clone <repo-url> llm-metrics && cd llm-metrics
cp .env.example .env && $EDITOR .env     # MODELS_DIR / MODEL
mkdir -p data
# опционально: secrets/telegram_webhook.txt с URL Telegram-webhook
# (не нужен — закомментировать секцию secrets в docker-compose.yml)

# 4) образы (контексты сборки маленькие; vLLM — из исходников)
make build
```

`.env` (в примере всё уже под compose по умолчанию):

| Переменная | Значение |
|---|---|
| `VLLM_URL` | `http://vllm:8000` (vllm в этом же compose) |
| `LOG_SOURCE_*` | `file`, `/var/log/vllm/vllm.log` (общий том `vllm-logs`) |
| `*PRICE_PER_M`, `RATE_PER_KWH_USD` | реальные тарифы |
| `TELEGRAM_WEBHOOK` (или secrets-файл) | URL (раздел 6) или пусто |

## 3. Запуск

```bash
make start               # up -d без пересборки (образы уже есть)
make ps                  # vllm: healthy (старт ~10-20 мин: 29 ГБ модель + cudagraphs),
                         # api: healthy, web: running
# пересборка после смены кода: make rebuild (= down + build + up)
```

Первая БД создаётся автоматически (авто-bootstrap схемы + alembic head).

## 4. Проверка

```bash
curl -s http://127.0.0.1:3000/api/health      # все источники online
```

В браузере `http://<IP>:3000`:

* 8 вкладок: Модель, GPU (5 GPU: 4xV100 под vLLM + RTX 2060), Система,
  Стоимость, Логи (идут строки vLLM из общего тома `vllm-logs`), Алерты,
  Health, Настройки;
* бейджи vLLM/GPU/SYS — зелёные.

## 4.1 Перенос на другой сервер (портативный деплой)

В репо жёстко закодированных путей нет — всё через `.env`. На новом хосте:

1. **Железо:** ≥4 GPU с достаточной VRAM (текущий профиль — 4xV100 32 ГБ
   под `--tensor-parallel-size 4`), диск под модель и `./data`.
2. **Софт:** Docker + NVIDIA-драйвер + nvidia-container-toolkit
   (раздел 2, шаг 1) — 5 команд, разово.
3. **vLLM-образ:** собрать на новом: `docker compose build vllm`
   (контекст маленький, исходники из git), либо перенести docker save/load.
4. **Модель:** ~29 ГБ — `rsync -av --partial` с текущего сервера
   (или скачать заново); путь — `MODELS_DIR` + `MODEL` в `.env`.
5. **Код:** `git clone`, `cp .env.example .env` + заполнить, `make start`
   (образ vllm уже собран).
6. **Проверка:** раздел 4.

Что остаётся специфичным для «этого» сервера и переносится в `.env`:
путь каталога моделей, имя модели, профиль запуска (`VLLM_SCRIPT`).
Остальное (API, web, БД, конфиг) переносится как есть; `./data` —
скопировать, если хочется сохранить историю.

## 5. Обновление vLLM

Обновить или зафиксировать версию: `docker compose build --build-arg VLLM_REF=<git sha> vllm`
(без аргумента — дефолтная ветка/реф). Затем `make start` (или `docker compose up -d`).
Аргументы сервера — в `docker/vllm/scripts/fp8.sh`.

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

# смена конфига (URL vLLM, источники логов, интервалы, ретенция)
nano .env
docker compose restart api

# логи процесса
docker compose logs -f api

# миграции схемы (обычно не нужны: авто-bootstrap + идемпотентная схема)
docker compose exec api python -m alembic upgrade head
```

Тарифы (Настройки/Стоимость) и алерты (Алерты) — только через UI:
хранятся в БД, рестарт не нужен, история пересчитывается на лету.

## 8. Что где хранится

* `./data/metrics.db` (+ WAL-файлы) — все данные (метрики, токены, логи,
  настройки, алерты). Бэкап = копия файла (желательно при остановленном api).
* `.env` — конфиг (URL, интервалы, ретенция, дефолт тарифов/алертов);
  `secrets/` — Telegram-webhook (не в git).
* Ретенция: raw 168 ч, hourly 180 дн, daily безлимит, логи 14 дн
  (настраивается в `.env`).

## 9. Архитектура и изоляция

* **vllm** — только инференс, не знает про мониторинг. Наружу НЕ публикуется:
  api ходит в него по имени vllm в compose-сети.
* **api** — весь мониторинг: метрики vLLM (`/metrics`), NVML (все 5 GPU,
  включая RTX 2060 вне vLLM), лог-индексатор vLLM, БД, алерты. 8100 наружу
  не публикуется.
* **web** — только UI, `/api/*` rewrite на api, напрямую к vLLM не ходит.

NVML читаем в api (а не в vLLM): один процесс видит все GPU хоста, включая
RTX 2060, которой в vLLM (TP=4, GPU 0-3) нет; toolkit инжектит libnvidia-ml.

Логи vLLM собираются через общий том `vllm-logs` (vLLM пишет
`/var/log/vllm/vllm.log`, api читает ro, лог-источник `file`) — docker-сокет
не нужен.
