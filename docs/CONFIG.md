# Конфигурация llm-metrics

Весь конфиг api — переменные окружения (`.env` рядом с `docker-compose.yml`;
шаблон — `.env.example`). **Inline-комментарии после значения не использовать**
(`VALUE # коммент` — compose передаёт комментарий как часть значения).

## `.env`

| Переменная | Дефолт | Назначение |
|---|---|---|
| **vLLM** | | |
| `VLLM_URL` | — (обязателен) | URL vLLM. vLLM на хосте: `http://host.docker.internal:8000` (скрипт vLLM обязан слушать `0.0.0.0`, а не `127.0.0.1` — loopback хоста из контейнеров не виден) |
| `VLLM_METRICS_PATH` | `/metrics` | путь Prometheus-эндпоинта |
| `VLLM_POLL_S` | 5 | период опроса vLLM, с |
| `VLLM_MODEL_NAME` | из `/v1/models` | метка модели для истории (фильтр «Модель»); обычно не нужен |
| `VLLM_TIMEOUT_S` | 5 | таймаут запросов к vLLM, с |
| **Обёртка vLLM на хосте** | | |
| `VLLM_SCRIPT` | `~/bin/work-fp8.sh` | хост-скрипт запуска vLLM (используется `make vllm-start/stop`; пример — ниже) |
| `VLLM_LOG_DIR` | `/mnt/storage/vllm` | каталог логов на хосте: сюда пишется `vllm.log` (nohup-redirect), pid-файл; api читает его read-only (bind в `/var/log/vllm`) |
| **GPU / система** | | |
| `GPU_POLL_S` | 10 | период опроса GPU (NVML), с |
| `GPU_VISIBLE` | `all` | `all` или список индексов: `0,1` |
| `SYS_POLL_S` | 10 | период опроса системы (CPU/RAM/диск/сеть), с |
| **Логи vLLM** | | |
| `LOG_SOURCE_NAME` | `vllm` | имя источника |
| `LOG_SOURCE_TYPE` | `file` | `file` или `docker` |
| `LOG_SOURCE_PATH` | `/var/log/vllm/vllm.log` | путь в контейнере api (bind-ro хост-каталога) |
| `LOG_SOURCE_CONTAINER` | — | имя контейнера (при `TYPE=docker`) |
| `LOG_POLL_S` | 1 | период чтения лога, с |
| `LOG_RETENTION_DAYS` | 14 | ретенция проиндексированных строк, дней |
| **БД и ретенция** | | |
| `SQLITE_PATH` | `/data/metrics.db` | путь БД в контейнере api (volume `./data`) |
| `RETENTION_RAW_HOURS` | 168 | сырые сэмплы, часов |
| `RETENTION_HOURLY_DAYS` | 180 | часовые агрегаты, дней |
| `RETENTION_DAILY_DAYS` | *(пусто = ∞)* | суточные агрегаты, дней |
| **Стоимость (дефолты; в UI меняется, история пересчитывается)** | | |
| `CURRENCY` | `USD` | код валюты (отображение) |
| `RATE_PER_KWH_USD` | 0.10 | цена электричества, $/кВт·ч |
| `BASELINE_WATTS` | 200 | базовая мощность хоста (CPU/SSD/сеть), Вт — считается в стоимость |
| `PROMPT_PRICE_PER_M` | 0.5 | цена prompt-токенов, $/1M |
| `COMPLETION_PRICE_PER_M` | 1.5 | цена completion-токенов, $/1M |
| **Алерты** | | |
| `ALERTS_ENABLED` | `true` | вкл/выкл движок алертов |
| `ALERTS_INTERVAL_S` | 30 | период проверки правил, с |
| `TELEGRAM_WEBHOOK` | — | полный URL `https://api.telegram.org/bot<TOKEN>/sendMessage?chat_id=<CHAT>`; либо файлом `secrets/telegram_webhook.txt` (рекомендуется). UI-настройки имеют приоритет и хранятся в БД |

Тарифы (вкладка «Стоимость» → «Тарифы») и правила алертов (вкладка «Алерты»)
— редактируются в UI, хранятся в БД, рестарт не нужен. `.env`-значения —
только стартовые дефолты.

## Скрипты запуска vLLM

Мониторинг не зависит от того, как запущен vLLM: нужен процесс на хосте,
слушающий `0.0.0.0:8000`, с `/metrics` и логами в файл. Запуск — через
хост-скрипт + обёртку `scripts/vllm-host.sh` (`make vllm-start`): obёртка
делает `nohup "$VLLM_SCRIPT" >> $VLLM_LOG_DIR/vllm.log`, pid-файл, stop/status.

### Пример 1 — FP8-модель, 4×V100 (основной, `~/bin/work-fp8.sh`)

```bash
#!/usr/bin/env bash
set -euo pipefail

source /home/arkalaust/miniconda3/etc/profile.d/conda.sh
conda activate 1cat-vllm-15

export CUDA_HOME=/usr/local/cuda-12.8
export PATH=$CUDA_HOME/bin:$PATH
export CUDA_DEVICE_ORDER=PCI_BUS_ID
export CUDA_VISIBLE_DEVICES=0,1,2,3
export VLLM_SM70_FLASH_ATTN_V100=1

MODEL="${MODEL:-/mnt/storage/models/Qwen3.8-27B-FP8}"
PORT="${PORT:-8000}"

exec python -m vllm.entrypoints.openai.api_server \
  --model "$MODEL" \
  --served-model-name qwen3.8-27b-fp8 \
  --trust-remote-code \
  --tensor-parallel-size 4 \
  --attention-backend FLASH_ATTN_V100 \
  --kv-cache-dtype fp8_e5m2 \
  --enable-prefix-caching \
  --enable-chunked-prefill \
  --max-num-seqs 128 \
  --max-num-batched-tokens 16384 \
  --max-model-len 262144 \
  --gpu-memory-utilization 0.95 \
  --compilation-config '{"cudagraph_mode":"FULL"}' \
  --generation-config auto \
  --enable-auto-tool-choice \
  --host 0.0.0.0 \
  --port "$PORT"
```

### Пример 2 — bf16-модель на всех 4 GPU (больше контекст/качество, медленнее)

```bash
#!/usr/bin/env bash
set -euo pipefail
source /home/arkalaust/miniconda3/etc/profile.d/conda.sh
conda activate 1cat-vllm-15
export CUDA_HOME=/usr/local/cuda-12.8
export PATH=$CUDA_HOME/bin:$PATH
export CUDA_DEVICE_ORDER=PCI_BUS_ID
export CUDA_VISIBLE_DEVICES=0,1,2,3

exec python -m vllm.entrypoints.openai.api_server \
  --model /mnt/storage/models/Qwen3.8-27B \
  --served-model-name qwen3.8-27b-bf16 \
  --trust-remote-code \
  --tensor-parallel-size 4 \
  --attention-backend FLASH_ATTN_V100 \
  --enable-prefix-caching \
  --enable-chunked-prefill \
  --max-model-len 32768 \
  --gpu-memory-utilization 0.95 \
  --host 0.0.0.0 --port 8000
```

Переключение конфигурации: поменяйте `VLLM_SCRIPT` в `.env` (или запустите
вручную), `make vllm-stop && make vllm-start`. В UI новая `served-model-name`
появится в селекторе «Модель» — история каждой модели отслеживается отдельно
(KPI/графики с фильтром, переключение видно вертикальными линиями на графиках).

### Пример 3 — один GPU (отладка / лёгкая модель)

```bash
#!/usr/bin/env bash
set -euo pipefail
source /home/arkalaust/miniconda3/etc/profile.d/conda.sh
conda activate 1cat-vllm-15
export CUDA_VISIBLE_DEVICES=4   # отдельная карта (напр. RTX 2060)

exec python -m vllm.entrypoints.openai.api_server \
  --model /mnt/storage/models/Qwen2.5-7B-Instruct \
  --served-model-name qwen2.5-7b \
  --tensor-parallel-size 1 \
  --max-model-len 32768 \
  --gpu-memory-utilization 0.90 \
  --host 0.0.0.0 --port 8000
```

## Частые настройки

```bash
# Только 2 GPU в мониторинге:
GPU_VISIBLE=0,1
# Реже опрашивать vLLM (нагруженный сервер):
VLLM_POLL_S=10
# Держать сырые данные неделю, hourly — 90 дней:
RETENTION_RAW_HOURS=168
RETENTION_HOURLY_DAYS=90
# Telegram-webhook файлом (рекомендуется вместо .env):
echo "https://api.telegram.org/bot<TOKEN>/sendMessage?chat_id=<CHAT>" \
  > secrets/telegram_webhook.txt
```
