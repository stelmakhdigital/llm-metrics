#!/bin/bash
# Диспетчер вхендров: VLLM_SCRIPT=<имя> → /scripts/<имя>.sh
# Профиль по умолчанию: fp8.
# Новый профиль: положить docker/vllm/scripts/<имя>.sh, пересобрать образ
# и задать VLLM_SCRIPT=<имя> (в .env рядом с compose или в environment).
#
# Логирование: stdout+stderr запускающего скрипта дублируется в
# /var/log/vllm/vllm.log (compose-логи по-прежнему видны). Ротация простая:
# пока файл >50MB — сдвиг vllm.log.N, максимум 4 файла (vllm.log + .1..3),
# проверка ~каждые 60с.
set -euo pipefail

SCRIPT="${VLLM_SCRIPT:-fp8}"
# регистрируем смонтированные libcuda/libnvidia-ml в ld-кэше: triton ищет
# libcuda через `ldconfig -p`, а в чистом образе кэш пуст
ldconfig 2>/dev/null || true
F="/scripts/${SCRIPT}.sh"
if [ ! -f "$F" ]; then
  echo "entrypoint: нет скрипта $F" >&2
  echo "Доступные скрипты:" >&2
  ls /scripts/*.sh >&2 || true
  exit 1
fi

LOG_DIR=/var/log/vllm
LOG="$LOG_DIR/vllm.log"
MAX_BYTES=$((50 * 1024 * 1024))
mkdir -p "$LOG_DIR"

# сдвиг-ротация: vllm.log→.1, .1→.2, .2→.3, .3 удаляется
rotate() {
  [ -f "$LOG" ] || return 0
  local size
  size=$(stat -c %s "$LOG" 2>/dev/null || echo 0)
  [ "$size" -gt "$MAX_BYTES" ] || return 0
  rm -f "$LOG.3"
  for i in 2 1; do
    [ -f "$LOG.$i" ] && mv -f "$LOG.$i" "$LOG.$((i + 1))"
  done
  mv -f "$LOG" "$LOG.1"
}

rotate
(
  while :; do
    sleep 60
    rotate
  done
) &
ROT_PID=$!
trap 'kill "$ROT_PID" 2>/dev/null || true' EXIT

# exit code скрипта профиля = exit code контейнера (tee не глотает статус)
set +e
/bin/bash "$F" 2>&1 | tee -a "$LOG"
rc=${PIPESTATUS[0]}
exit "$rc"
