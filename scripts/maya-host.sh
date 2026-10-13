#!/usr/bin/env bash
# Обёртка над хост-скриптом Project Maya (run-maya-*.sh): nohup-запуск,
# лог в $MAYA_LOG_DIR/maya.log, pid-файл, stop/status.
#
# Maya — не vLLM: перед движком (build/strata) стоит Python-сервер
# serve/server.py. Метрики api забирает с его GET /metrics (JSON) при
# VLLM_SOURCE_TYPE=maya — см. docs/CONFIG.md.
#
# Использование: scripts/maya-host.sh start|stop|status [аргументы maya.py]
# Env (можно задать в .env): MAYA_SCRIPT, MAYA_LOG_DIR, MAYA_EXTRA_ARGS
#
# ВАЖНО: maya.py должен слушать 0.0.0.0, а не 127.0.0.1 — api в docker
# ходит на хост через host.docker.internal (loopback хоста не виден).
# Либо пропишите --host 0.0.0.0 в MAYA_SCRIPT, либо задайте
# MAYA_EXTRA_ARGS="--host 0.0.0.0".
set -euo pipefail

MAYA_SCRIPT="${MAYA_SCRIPT:-$HOME/Code/project-maya/run-maya-maya-s-v2-iq2_xxs.sh}"
MAYA_LOG_DIR="${MAYA_LOG_DIR:-/mnt/storage/maya}"
MAYA_EXTRA_ARGS="${MAYA_EXTRA_ARGS:-}"
LOG="$MAYA_LOG_DIR/maya.log"
PIDFILE="$MAYA_LOG_DIR/maya.pid"

running() {
  [ -f "$PIDFILE" ] || return 1
  local pid
  pid=$(cat "$PIDFILE" 2>/dev/null) || return 1
  kill -0 "$pid" 2>/dev/null
}

cmd="${1:-}"
shift || true
case "$cmd" in
  start)
    if running; then
      echo "maya уже запущен (PID $(cat "$PIDFILE"))"
      exit 0
    fi
    [ -x "$MAYA_SCRIPT" ] || {
      echo "ОШИБКА: скрипт не найден или не исполняемый: $MAYA_SCRIPT" >&2
      exit 1
    }
    # Проверка биндинга: --host 0.0.0.0 должен быть в скрипте или в MAYA_EXTRA_ARGS
    HOST_OK=0
    grep -q -- "--host 0.0.0.0" "$MAYA_SCRIPT" 2>/dev/null && HOST_OK=1
    grep -q -- "--host 0.0.0.0" <<<"$MAYA_EXTRA_ARGS" && HOST_OK=1
    if [ "$HOST_OK" = 0 ]; then
      echo "ВНИМАНИЕ: --host 0.0.0.0 не задан (ни в $MAYA_SCRIPT, ни в MAYA_EXTRA_ARGS) —" >&2
      echo "api в docker может не достучаться. Запускайте: MAYA_EXTRA_ARGS=\"--host 0.0.0.0\" $0 start" >&2
    fi
    mkdir -p "$MAYA_LOG_DIR"
    # shellcheck disable=SC2086
    nohup "$MAYA_SCRIPT" $MAYA_EXTRA_ARGS "$@" >>"$LOG" 2>&1 &
    echo $! >"$PIDFILE"
    echo "maya запущен (PID $(cat "$PIDFILE")), лог: $LOG"
    echo "Прогресс: tail -f $LOG"
    ;;
  stop)
    if ! running; then
      echo "maya не запущен"
      rm -f "$PIDFILE"
      exit 0
    fi
    pid=$(cat "$PIDFILE")
    kill "$pid"
    for _ in $(seq 1 30); do
      kill -0 "$pid" 2>/dev/null || break
      sleep 1
    done
    if kill -0 "$pid" 2>/dev/null; then
      echo "не завершился за 30 с — kill -9" >&2
      kill -9 "$pid" 2>/dev/null || true
    fi
    rm -f "$PIDFILE"
    echo "maya остановлен"
    ;;
  status)
    if running; then
      echo "maya запущен (PID $(cat "$PIDFILE"))"
    else
      echo "maya не запущен"
      rm -f "$PIDFILE"
    fi
    [ -f "$LOG" ] && tail -n 3 "$LOG"
    ;;
  *)
    echo "Использование: $0 start|stop|status [аргументы maya.py]" >&2
    exit 2
    ;;
esac
