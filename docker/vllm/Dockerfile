# llm-metrics — контейнер vLLM (1Cat-vLLM 1.5.x, 4xV100 TP=4)
#
# Зависимости НЕ ставятся в образ: conda-окружение хоста (собранный 1Cat-vLLM
# + torch cu128) монтируется read-only в /opt/vllm-env — тот самый,
# проверенный в bare-запуске. Base = ubuntu:24.04 (glibc хоста 24.04 совпадает).
#
#   docker build -t llm-metrics-vllm:latest -f docker/vllm/Dockerfile docker/vllm/

FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
    && apt-get install -y --no-install-recommends bash ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Вхендр = тот же запуск, что bare-скрипт ~/bin/work-fp8.sh
COPY entrypoint.sh /entrypoint.sh
ENTRYPOINT ["/bin/bash", "/entrypoint.sh"]

# /health у vLLM OpenAI-сервера; старт долгий (29 ГБ модель, cudagraphs)
HEALTHCHECK --interval=30s --timeout=10s --start-period=1800s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=5)" || exit 1
