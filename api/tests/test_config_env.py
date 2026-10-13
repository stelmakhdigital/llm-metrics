"""config.py: env-значения с inline-комментариями.

Docker compose ``env_file`` не режет `` #коммент`` после значения —
``_env`` должен; иначе ``int('30 # коммент')`` роняет api на старте.
"""

import pytest

from app.config import load_config

KEYS = (
    "VLLM_URL", "RETENTION_DAILY_DAYS", "LOG_SOURCE_PATH", "GPU_VISIBLE",
)


@pytest.fixture
def clean_env(monkeypatch):
    for k in KEYS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("VLLM_URL", "http://host.docker.internal:8000")
    yield


def test_int_env_with_inline_comment(clean_env, monkeypatch):
    monkeypatch.setenv("RETENTION_DAILY_DAYS", "30 # в днях")
    cfg = load_config()
    assert cfg.storage.retention.daily_days == 30


def test_empty_env_with_inline_comment(clean_env, monkeypatch):
    # дефолт .env.example: RETENTION_DAILY_DAYS=          # пусто — безлимит
    monkeypatch.setenv("RETENTION_DAILY_DAYS", "          # пусто — безлимит")
    cfg = load_config()
    assert cfg.storage.retention.daily_days is None


def test_url_env_with_inline_comment(clean_env, monkeypatch):
    monkeypatch.setenv("VLLM_URL", "http://host.docker.internal:8000 # host vllm")
    cfg = load_config()
    assert cfg.sources.vllm.url == "http://host.docker.internal:8000"


def test_source_type_default_and_maya(clean_env, monkeypatch):
    # дефолт — vllm
    cfg = load_config()
    assert cfg.sources.vllm.source_type == "vllm"
    monkeypatch.setenv("VLLM_SOURCE_TYPE", "maya")
    cfg = load_config()
    assert cfg.sources.vllm.source_type == "maya"


def test_source_type_invalid(clean_env, monkeypatch):
    monkeypatch.setenv("VLLM_SOURCE_TYPE", "prometheus")
    with pytest.raises(RuntimeError, match="VLLM_SOURCE_TYPE"):
        load_config()
