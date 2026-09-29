#!/usr/bin/env bash
# Создаёт лейблы llm-metrics на GitHub (нужен `gh` и авторизация).
# Идемпотент: существующие лейблы пропускает.
set -euo pipefail

# Формат: "name|color|description"
LABELS=(
  "bug|d73a4a|Ошибочное поведение"
  "enhancement|a2eeef|Новая функция/улучшение"
  "docs|0075ca|Документация"
  "refactor|b991d8|Переделка без изменения поведения"
  "perf|0052cc|Производительность"
  "api|1d76db|Бэкенд (FastAPI)"
  "web|6f42c1|UI (Next.js)"
  "cost|fbca04|Вкладка/модуль стоимости"
  "model-tab|fde68a|Вкладка Модель (vLLM)"
  "gpu|2e7d32|GPU/NVML"
  "system|e6e6e6|Система (CPU/RAM/диск/сеть)"
  "logs|9c9279|Логи vLLM"
  "alerts|ff7500|Алерты/Telegram"
  "deploy|8b5cf6|Деплой/инфраструктура"
  "size:S|ededed|< 1 часа работы"
  "size:M|dddddd|< 1 дня"
  "size:L|cccccc|> 1 дня"
  "P0|b60205|Down — чинить сразу"
  "P1|e66105|Важно — ближайшее время"
  "P2|f9d0c4|План"
  "P3|fff5e0|Косметика"
  "agent:ready|0e8a16|Задача готова к автономному исполнению агентом (есть чеклист Приёмки)"
  "agent:in-progress|5319ef|Агент работает"
  "agent:needs-review|d4a70c|PR готов — ждать ревью человека"
  "good-first-issue|705df0|Простая стартовая задача"
)

for l in "${LABELS[@]}"; do
  IFS='|' read -r name color desc <<<"$l"
  if gh label list --json name 2>/dev/null | grep -q "\"$name\""; then
    echo "✓ $name (уже есть)"
  else
    gh label create "$name" --color "$color" --description "$desc" && echo "+ $name"
  fi
done
