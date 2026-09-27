# llm-metrics — контейнер vLLM (1Cat-vLLM 1.5.x, 4xV100 TP=4), автономный
#
# Зависимости впечены в образ на этапе сборки: `make stage-vllm` создаёт
# hard-link-копии в контексте (docker/vllm/.build-env, .build-src) —
# ноль доп. дисков, сборка ~время tar'а 15 ГБ:
#   .build-env/  → /opt/vllm-env             (conda-env 1Cat-vLLM + torch cu128)
#   .build-src/  → /home/arkalaust/1Cat-vLLM (исходники; путь зашит в .pth
#                site-packages — копировать только в этот путь)
# GPU-драйвер (libcuda и устройства) инжектит nvidia-container-toolkit.
#
#   make stage-vllm && make build   (или: make start)

FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
    && apt-get install -y --no-install-recommends bash ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Автономность: vLLM-окружение хоста впечено в образ (make stage-vllm)
COPY .build-env/ /opt/vllm-env/
COPY .build-src/ /home/arkalaust/1Cat-vLLM/

# Диспетчер вхендров + профили запуска (scripts/fp8.sh = bare work-fp8.sh)
COPY entrypoint.sh /entrypoint.sh
COPY scripts/ /scripts/
ENTRYPOINT ["/bin/bash", "/entrypoint.sh"]

# /health у vLLM OpenAI-сервера; старт долгий (29 ГБ модель, cudagraphs)
HEALTHCHECK --interval=30s --timeout=10s --start-period=1800s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=5)" || exit 1
