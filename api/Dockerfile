# llm-metrics API (ТЗ §8)
# Бэкенд биндится только внутри compose-сети (наружу — только web:3000,
# 8100 на хост НЕ публикуется).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    METRICS_CONFIG=/data/metrics.config.yaml

WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# docker CLI (статический бинарник) — лог-индексатор читает `docker logs vllm`
# (sources.logs[].type=docker, сокет /var/run/docker.sock монтируется в compose)
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/* \
    && curl -fsSL https://download.docker.com/linux/static/stable/x86_64/docker-27.5.1.tgz \
         | tar xz -C /tmp docker/docker \
    && install -m 0755 /tmp/docker /usr/local/bin/docker \
    && rm -rf /tmp/docker

COPY app ./app
COPY migrations ./migrations
COPY alembic.ini .

RUN useradd -m appuser \
    && mkdir -p /data \
    && chown -R appuser:appuser /data
VOLUME ["/data"]
USER appuser

EXPOSE 8100
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8100/api/health', timeout=3).status==200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8100"]
