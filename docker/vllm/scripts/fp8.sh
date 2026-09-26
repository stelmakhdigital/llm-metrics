#!/bin/bash
# Вхендр vLLM-контейнера = ~/bin/work-fp8.sh (bare-запуск на сервере),
# адаптированный под контейнер: conda-env хоста смонтирован в /opt/vllm-env,
# исходники editable-установки — в /home/arkalaust/1Cat-vLLM (тот же путь,
# что и .pth в site-packages), модель — в /mnt/storage/models (ro).
set -euo pipefail

export PATH=/opt/vllm-env/bin:$PATH
export CUDA_DEVICE_ORDER=PCI_BUS_ID
export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0,1,2,3}"
export VLLM_SM70_FLASH_ATTN_V100=1
export VLLM_SM70_NVFP4_TURBOMIND=1
unset LD_LIBRARY_PATH VLLM_SM70_FLASHQLA_ORIGINAL_PREFILL VLLM_1CAT_ENABLE_SM70_MTP_DEFAULTS

MODEL="${MODEL:-/mnt/storage/models/Qwen3.8-27B-FP8}"
PORT="${PORT:-8000}"
# Имя модели для клиентов/API: по умолчанию basename(MODEL) в нижнем регистре
SERVED_NAME="${SERVED_NAME:-$(basename "$MODEL" | tr 'A-Z' 'a-z')}"

exec python -m vllm.entrypoints.openai.api_server \
  --model "$MODEL" \
  --served-model-name "$SERVED_NAME" \
  --trust-remote-code \
  --tensor-parallel-size 4 \
  --attention-backend FLASH_ATTN_V100 \
  --kv-cache-dtype fp8_e5m2 \
  --enable-prefix-caching \
  --mamba-cache-mode align \
  --enable-chunked-prefill \
  --max-num-seqs 4 \
  --max-num-batched-tokens 16384 \
  --max-model-len 262144 \
  --gpu-memory-utilization 0.90 \
  --compilation-config '{"cudagraph_mode":"FULL"}' \
  --generation-config auto \
  --override-generation-config '{"temperature":1.0,"top_p":0.95,"top_k":20,"max_new_tokens":16384}' \
  --enable-auto-tool-choice \
  --tool-call-parser qwen3_coder \
  --reasoning-parser qwen3 \
  --default-chat-template-kwargs '{"enable_thinking":true, "preserve_thinking":true , "reasoning_effort":"medium"}' \
  --limit-mm-per-prompt '{"image": 1000}' \
  --mm-processor-cache-type shm \
  --mm-processor-kwargs '{"truncation": false}' \
  --mm-encoder-tp-mode data \
  --mm-shm-cache-max-object-size-mb 256 \
  --host 0.0.0.0 \
  --port "$PORT"
