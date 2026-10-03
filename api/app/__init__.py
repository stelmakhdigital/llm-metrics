"""llm-metrics API — FastAPI-бэкенд мониторинга vLLM-сервера (roadmap F0)."""

import os

# версия вшивается при docker build (git describe --tags); dev-режим — dev
__version__ = os.environ.get("APP_VERSION", "dev")
