# Деплой llm-metrics (docker compose)

Прод-деплой: **vLLM (1Cat-vLLM, 4xV100 TP=4) + api + web** одним
`docker compose up -d --build`. Наружу: `web :3000` и `vllm :8000`;
API (8100) — только в compose-сети (`/api/*` через Next.js-rewrite).

## 1. Требования на сервере

* Docker + Compose + **nvidia-container-toolkit** (GPU-библиотеки и
  устройства инжектятся в контейнеры автоматически;
  установка — раздел 2, ~2 мин);
* NVIDIA-драйвер (проверить: `ls /usr/lib/x86_64-linux-gnu/libcuda.so.1`);
* conda-окружение 1Cat-vLLM + исходники editable-установки — пути
  задаются в `.env` (`VLLM_ENV_DIR`, `VLLM_SRC_DIR`);
* каталог моделей + сама модель (~29 ГБ) — `MODELS_DIR` / `MODEL` в `.env`.

> vLLM-контейнер НЕ ставит зависимости: монтирует read-only готовый
> conda-env хоста (тот же, что bare-скрипт `~/bin/work-fp8.sh`).
> Полностью автономный образ (env «впечён» в image) — следующий шаг,
> если нужно убрать зависимость от файлов хоста.

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

# 3) репозиторий + конфиг + окружение
git clone <repo-url> llm-metrics && cd llm-metrics
cp metrics.config.example.yaml metrics.config.yaml
cp .env.example .env && $EDITOR .env     # VLLM_ENV_DIR / VLLM_SRC_DIR / MODELS_DIR / MODEL
mkdir -p data
```

`metrics.config.yaml` (по умолчанию в примере всё уже под compose):

| Ключ | Значение |
|---|---|
| `sources.vllm.url` | `http://vllm:8000` (vllm в этом же compose) |
| `sources.logs` | `type: docker, container: vllm` |
| `cost.*` | реальные тарифы |
| `alerts.telegram_webhook` | URL (раздел 6) или `null` |

## 3. Запуск

```bash
docker compose up -d --build
docker compose ps    # vllm: healthy (старт ~10-20 мин: 29 ГБ модель + cudagraphs),
                     # api: healthy, web: running
```

Первая БД создаётся автоматически (авто-bootstrap схемы + alembic head).

## 4. Проверка

```bash
curl -s http://127.0.0.1:3000/api/health      # все источники online
curl -s http://127.0.0.1:8000/v1/models        # vLLM отвечает (как при bare)
```

В браузере `http://<IP>:3000`:

* 8 вкладок: Модель, GPU (5 GPU: 4xV100 под vLLM + RTX 2060), Система,
  Стоимость, Логи (идут строки vLLM через docker logs), Алерты, Health, Настройки;
* бейджи vLLM/GPU/SYS — зелёные.

## 4.1 Перенос на другой сервер (портативный деплой)

В репо жёстко закодированных путей нет — всё через `.env`. На новом хосте:

1. **Железо:** ≥4 GPU с достаточной VRAM (текущий профиль — 4xV100 32 ГБ
   под `--tensor-parallel-size 4`), диск под модель и `./data`.
2. **Софт:** Docker + NVIDIA-драйвер + nvidia-container-toolkit
   (раздел 2, шаг 1) — 5 команд, разово.
3. **Конвей vLLM (1Cat-vLLM):** готовый conda-env + исходники
   (раздел 5 — либо перенос env, либо пересборка; см. примечание в §1).
   Пути вписать в `VLLM_ENV_DIR` / `VLLM_SRC_DIR`.
4. **Модель:** ~29 ГБ — `rsync -av --partial` с текущего сервера
   (или скачать заново); путь — `MODELS_DIR` + `MODEL` в `.env`.
5. **Код:** `git clone`, `cp metrics.config.example.yaml metrics.config.yaml`,
   `cp .env.example .env` + заполнить, `make start`.
6. **Проверка:** раздел 4.

Что остаётся специфичным для «этого» сервера и переносится в `.env`:
пути env/исходников/моделей, имя модели, профиль запуска (`VLLM_SCRIPT`).
Остальное (API, web, БД, конфиг) переносится как есть; `./data` —
скопировать, если хочется сохранить историю.

## 5. Обновление bare-окружения vLLM

Если обновляете 1Cat-vLLM/torch в conda-env на хосте — контейнер vllm
подхватит изменения после `docker compose restart vllm` (env смонтирован
read-only, пересборка образа не нужна). Аргументы сервера — в
`docker/vllm/entrypoint.sh` (копия `~/bin/work-fp8.sh`).

## 6. Telegram-алерты (разовая настройка)

1. @BotFather → `/newbot` → получить токен.
2. Отправить боту любое сообщение, затем:
   `curl https://api.telegram.org/bot<TOKEN>/getUpdates` → взять `chat.id`.
3. Webhook: `https://api.telegram.org/bot<TOKEN>/sendMessage?chat_id=<CHAT>`.
4. Указать в UI (вкладка «Алерты» → поле webhook → кнопка **Тест**) **или**
   в `alerts.telegram_webhook` конфига + `docker compose restart api`.
   UI-значения имеют приоритет над конфигом (хранятся в БД).

Дальше правила/пороги/уровни редактируются в той же вкладке;
«Сбросить правила» — значения по умолчанию.

## 7. Эксплуатация

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

## 8. Что где хранится

* `./data/metrics.db` (+ WAL-файлы) — все данные (метрики, токены, логи,
  настройки, алерты). Бэкап = копия файла (желательно при остановленном api).
* `./metrics.config.yaml` — конфиг (URL, интервалы, ретенция, дефолт тарифов/алертов).
* Ретенция: raw 168 ч, hourly 180 дн, daily безлимит, логи 14 дн
  (настраивается в конфиге/`storage.retention`).
