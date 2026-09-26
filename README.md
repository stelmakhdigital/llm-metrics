# llm-metrics — веб-мониторинг vLLM-сервера

Стек: FastAPI (`api/`) + Next.js (`web/`), SQLite WAL. ТЗ —
`TZ-vllm-metrics-app.md`, контекст — `PROJECT_MEMORY.md`, план — `roadmap.md`.

## Запуск

Prod (сервер с vLLM): `docker compose up -d --build` (web :3000, API без
публичного порта — `/api/*` проксирует Next.js). Конфиг: скопировать
`metrics.config.example.yaml` → `./metrics.config.yaml` и отредактировать.

Dev (без docker): `make dev-api` (uvicorn :8100) + `make dev-web` (:3000);
мок vLLM — `make mock-vllm`; тесты — `make test-api`, `cd web && npm test`.

## Логи vLLM (вкладка «Логи»)

Лог-индексатор (`api/app/logs`) опрашивает источники из секции `logs`
конфига раз в `poll_seconds` (default 1 с) и пишет их в `log_entries`
(ретенция — `logs.retention_days`, default **14 дней**, ежечасная чистка).

### Файл логов (тип `file`, по умолчанию)

Укажите путь к файлу, который пишет vLLM (например, `nohup.out`):

```yaml
sources:
  logs:
    sources:
      - name: vllm            # имя источника (видно в UI и в /api/health)
        type: file
        path: /mnt/storage/vllm/nohup.log
    poll_seconds: 1
    retention_days: 14
```

* Tail идёт по offset+inode: ротация/пересоздание файла обрабатывается,
  при исчезновении файла источник помечается `offline` (приложение живёт,
  остальные источники не страдают).
* Первая встреча файла — старт **с конца** (история до запуска индексатора
  не подтягивается).
* Для compose смонтируйте файл в контейнер api (в `docker-compose.yml`):

```yaml
    volumes:
      - /mnt/storage/vllm:/mnt/storage/vllm:ro
```

### Docker logs (тип `docker`)

Если vLLM запущен как контейнер — можно читать `docker logs` напрямую:

```yaml
sources:
  logs:
    sources:
      - name: vllm
        type: docker
        container: vllm      # имя/ID контейнера
```

Бэк поднимает `docker logs -t -f --tail=0 <container>` (subprocess, pipe;
`--tail=0` — только новые строки). Требования:

1. **docker CLI** должен быть доступен в контейнере api — в
   `docker-compose.yml` уже смонтирован сокет:
   `- /var/run/docker.sock:/var/run/docker.sock` (для docker-источников логов);
2. контейнер vLLM и контейнер api должны видеть один и тот же docker-демон
   (в типичном деплое они на одном хосте — ок).

При отсутствии/недоступности docker CLI источник переходит в `offline`
со статусом `last_error = "docker CLI не найден …"` (показывается в UI,
вкладка «Логи»); повторные попытки — раз в 60 с.

### Что попадает в UI

Вкладка «Логи»: мини-график по дням/уровням, таблица (фильтры уровень/
текст/источник, страницы 100/250/500), Live-хвост (SSE), экспорт
txt/csv, автопарсинг stat-строк vLLM в боковую колонку
(Running/Waiting/KV%/throughput, `api/app/logs/patterns.py`).
