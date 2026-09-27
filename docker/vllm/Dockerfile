# llm-metrics — контейнер vLLM (1Cat-vLLM 1.5.x, 4xV100 TP=4), автономный
#
# vLLM собирается из исходников внутри образа (multi-stage):
#   stage build    — nvidia/cuda 12.8 devel: venv + torch cu128 + 1Cat-vLLM
#                    из исходников (SM70), pip install
#   stage runtime  — nvidia/cuda 12.8 runtime: venv из build + entrypoint/scripts
#
# Пин форка: --build-arg VLLM_REF=<git sha> (дефолт — пин в репо).
# Ubuntu-зеркало (опционально): --build-arg UBU_MIRROR=<base-url>
#   (полный URL со схемой и /ubuntu, напр. http://mirror.example/ubuntu).
# GPU-драйвер (libcuda и устройства) инжектит nvidia-container-toolkit.
# Сборка занимает часы (CUDA-экстензии под SM70) — на GPU-сервере.

ARG VLLM_REF=14abfc27ee4e13cd2a9d1a8a882f36a629e5889a

# ---------------------------------------------------------------- build stage
FROM nvidia/cuda:12.8.0-devel-ubuntu24.04 AS build
ARG VLLM_REF
ARG UBU_MIRROR
ENV DEBIAN_FRONTEND=noninteractive

# Ubuntu-зеркало — подстановка в apt-источники один раз (до apt-get update)
RUN if [ -n "${UBU_MIRROR}" ]; then \
      sed -i "s|https://archive.ubuntu.com|${UBU_MIRROR}|; s|https://security.ubuntu.com|${UBU_MIRROR}|; \
             s|http://archive.ubuntu.com|${UBU_MIRROR}|; s|http://security.ubuntu.com|${UBU_MIRROR}|g" \
        /etc/apt/sources.list.d/ubuntu.sources /etc/apt/sources.list 2>/dev/null || true; \
    fi
# apt-метаданные — отдельный слой (кэшируется между пересборками)
RUN apt-get update
RUN apt-get install -y --no-install-recommends \
      gcc g++ make cmake ninja-build git ca-certificates \
      python3 python3-venv python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Фиксированный путь venv — runtime-стадия копирует его в тот же путь.
# Ubuntu 24.04 → Python 3.12: нужен для torch cu128 cp312-колёс форка.
RUN python3 -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
RUN pip install --upgrade pip

# torch/torchaudio/torchvision cu128 — версии из requirements/cuda.txt форка
# (1Cat-vLLM на пин-коммите)
RUN pip install --index-url https://download.pytorch.org/whl/cu128 \
      torch==2.10.0 torchaudio==2.10.0 torchvision==0.25.0
# build-зависимости vLLM (из pyproject.toml форка). --no-build-isolation ниже:
# иначе pip поставит torch заново в изолированное окружение сборки
RUN pip install cmake ninja packaging patchelf wheel jinja2 \
      "setuptools>=77.0.3,<81.0.0" setuptools-scm setuptools-rust

# Исходники форка на пин-коммите
RUN git clone --depth 1 --branch "${VLLM_REF}" \
      https://github.com/1CatAI/1Cat-vLLM /build/vllm

# Сборка: только SM70 (V100), см. README форка «Build From Source».
# torch уже установлен из cu128-индекса → requirement torch==2.10.0 форка
# считается выполненным (PEP 440: 2.10.0+cu128 satisfies ==2.10.0),
# повторная загрузка не происходит.
# Rust-фронтенд (vllm-rs) в форке опционален (VLLM_USE_RUST_FRONTEND=1,
# по умолчанию выключен) — cargo/rustup не ставим.
RUN TORCH_CUDA_ARCH_LIST=7.0 \
    CMAKE_CUDA_ARCHITECTURES=70 \
    pip install --no-build-isolation /build/vllm

# ------------------------------------------------------------- runtime stage
FROM nvidia/cuda:12.8.0-cudnn9-runtime-ubuntu24.04 AS runtime
ARG UBU_MIRROR
ENV DEBIAN_FRONTEND=noninteractive

RUN if [ -n "${UBU_MIRROR}" ]; then \
      sed -i "s|https://archive.ubuntu.com|${UBU_MIRROR}|; s|https://security.ubuntu.com|${UBU_MIRROR}|; \
             s|http://archive.ubuntu.com|${UBU_MIRROR}|; s|http://security.ubuntu.com|${UBU_MIRROR}|g" \
        /etc/apt/sources.list.d/ubuntu.sources /etc/apt/sources.list 2>/dev/null || true; \
    fi
RUN apt-get update
# Минимум: ca-certificates (https/urllib), gcc+libc6-dev (triton
# JIT-компилирует C-модуль драйвер-интерфейса при первом запуске),
# python3 (интерпретатор для скопированного venv, тот же Python 3.12)
RUN apt-get install -y --no-install-recommends \
      ca-certificates gcc libc6-dev python3 \
    && rm -rf /var/lib/apt/lists/*

# vLLM + зависимости из build-стадии
COPY --from=build /opt/venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH

# Диспетчер вхендров + профили запуска (scripts/fp8.sh)
COPY entrypoint.sh /entrypoint.sh
COPY scripts/ /scripts/
ENTRYPOINT ["/bin/bash", "/entrypoint.sh"]

# /health у vLLM OpenAI-сервера; старт долгий (29 ГБ модель, cudagraphs)
HEALTHCHECK --interval=30s --timeout=10s --start-period=1800s --retries=5 \
    CMD /opt/venv/bin/python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=5)" || exit 1
