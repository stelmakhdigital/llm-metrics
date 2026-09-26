"""Схема БД (ТЗ §4). Единственный источник истины: используется и при
-bootstrap* приложения (``CREATE TABLE IF NOT EXISTS``), и в alembic-миграции.

Времена — epoch-секунды UTC. Часовые/суточные окна — epoch начала окна UTC.
"""

# Каждая запись — один объект (таблица + индексы), порядок важен.
SCHEMA_STATEMENTS: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS metric_samples (
        metric TEXT    NOT NULL,  -- логическое имя метрики
        ts INTEGER     NOT NULL,  -- epoch-секунды UTC
        value REAL     NOT NULL,
        gpu INTEGER,              -- индекс GPU для gpu-метрик, иначе NULL
        source TEXT    NOT NULL,  -- vllm | gpu | system
        model TEXT                    -- модель vLLM на момент замера (NULL для gpu/system)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_metric_samples_metric_ts ON metric_samples(metric, ts)",
    """
    CREATE TABLE IF NOT EXISTS metric_hourly (
        metric TEXT    NOT NULL,
        hour INTEGER   NOT NULL,  -- epoch начала часа (UTC)
        avg REAL,
        min REAL,
        max REAL,
        p95 REAL,
        count INTEGER
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_metric_hourly_metric_hour ON metric_hourly(metric, hour)",
    """
    CREATE TABLE IF NOT EXISTS metric_daily (
        metric TEXT    NOT NULL,
        day INTEGER    NOT NULL,  -- epoch начала суток (UTC)
        avg REAL,
        min REAL,
        max REAL,
        p95 REAL,
        sum REAL,
        count INTEGER
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_metric_daily_metric_day ON metric_daily(metric, day)",
    """
    CREATE TABLE IF NOT EXISTS tokens (
        ts INTEGER               NOT NULL,  -- epoch начала часа (UTC)
        prompt_tokens INTEGER,
        completion_tokens INTEGER,
        requests_finished INTEGER
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_tokens_ts ON tokens(ts)",
    """
    CREATE TABLE IF NOT EXISTS log_entries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts INTEGER   NOT NULL,  -- epoch-МИЛЛИСекунды UTC (точная до мс, ТЗ §5.6)
        level TEXT   NOT NULL,  -- DEBUG | INFO | WARNING | ERROR | CRITICAL
        line TEXT    NOT NULL,
        source TEXT   NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_log_entries_ts_level ON log_entries(ts, level)",
    "CREATE INDEX IF NOT EXISTS idx_log_entries_source ON log_entries(source)",
    """
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT,              -- JSON
        updated_at INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS gpu_devices (
        id INTEGER PRIMARY KEY,  -- индекс устройства NVML
        name TEXT,
        total_mem_mib INTEGER,
        pci_bus TEXT
    )
    """,
]
