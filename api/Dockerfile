# llm-metrics API (ТЗ §8)
# Бэкенд биндится только внутри compose-сети (наружу — только web:3000,
# 8100 на хост НЕ публикуется).
# Конфигурация — только ENV (F5.4), см. .env / docs.

FROM python:3.12-slim AS deps
WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /srv
COPY --from=deps /install /usr/local

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
