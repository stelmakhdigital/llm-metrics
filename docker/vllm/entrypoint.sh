#!/bin/bash
# Диспетчер вхендров: VLLM_SCRIPT=<имя> → /scripts/<имя>.sh
# Профиль по умолчанию: fp8 (= bare ~/bin/work-fp8.sh, TP=4).
# Новый профиль: положить docker/vllm/scripts/<имя>.sh, пересобрать образ
# и задать VLLM_SCRIPT=<имя> (в .env рядом с compose или в environment).
set -euo pipefail

SCRIPT="${VLLM_SCRIPT:-fp8}"
F="/scripts/${SCRIPT}.sh"
if [ ! -f "$F" ]; then
  echo "entrypoint: нет скрипта $F" >&2
  echo "Доступные скрипты:" >&2
  ls /scripts/*.sh >&2 || true
  exit 1
fi
exec /bin/bash "$F"
