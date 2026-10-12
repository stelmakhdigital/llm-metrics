#!/usr/bin/env bash
# Обёртка над хост-скриптом vLLM (~/bin/work-fp8.sh): nohup-запуск,
# лог в $VLLM_LOG_DIR/vllm.log (api читает его read-only через bind-маунт),
# pid-файл, stop/status.
#
# Использование: scripts/vllm-host.sh start|stop|status
# Env (можно задать в .env): VLLM_SCRIPT, VLLM_LOG_DIR
set -euo pipefail

VLLM_SCRIPT="${VLLM_SCRIPT:-$HOME/bin/work-fp8.sh}"
VLLM_LOG_DIR="${VLLM_LOG_DIR:-/mnt/storage/vllm}"
LOG="$VLLM_LOG_DIR/vllm.log"
PIDFILE="$VLLM_LOG_DIR/vllm.pid"

running() {
  [ -f "$PIDFILE" ] || return 1
  local pid
  pid=$(cat "$PIDFILE" 2>/dev/null) || return 1
  kill -0 "$pid" 2>/dev/null
}

cmd="${1:-}"
case "$cmd" in
  start)
    if running; then
      echo "vLLM уже запущен (PID $(cat "$PIDFILE"))"
      exit 0
    fi
    [ -x "$VLLM_SCRIPT" ] || {
      echo "ОШИБКА: скрипт не найден или не исполняемый: $VLLM_SCRIPT" >&2
      exit 1
    }
    # api ходит в vLLM через host.docker.internal (IP хоста в docker-мосту) —
    # loopback из контейнеров не виден, нужен --host 0.0.0.0 в work-fp8.sh
    if grep -E -- "--host" "$VLLM_SCRIPT" 2>/dev/null | grep -q "127.0.0.1"; then
      echo "ВНИМАНИЕ: $VLLM_SCRIPT биндится на 127.0.0.1 — api в docker НЕ сможет достучаться. Замените на --host 0.0.0.0" >&2
    fi
    mkdir -p "$VLLM_LOG_DIR"
    nohup "$VLLM_SCRIPT" >>"$LOG" 2>&1 &
    echo $! >"$PIDFILE"
    echo "vLLM запущен (PID $(cat "$PIDFILE")), лог: $LOG"
    echo "Прогресс: tail -f $LOG"
    ;;
  stop)
    if ! running; then
      echo "vLLM не запущен"
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
    echo "vLLM остановлен"
    ;;
  status)
    if running; then
      echo "vLLM запущен (PID $(cat "$PIDFILE"))"
    else
      echo "vLLM не запущен"
      rm -f "$PIDFILE"
    fi
    [ -f "$LOG" ] && tail -n 3 "$LOG"
    ;;
  *)
    echo "Использование: $0 start|stop|status" >&2
    exit 2
    ;;
esac
