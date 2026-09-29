"""Метка model в metric_hourly/metric_daily (фильтр моделей без 168ч-лимита)

Revision ID: 0004
Revises: 0003

* metric_hourly/metric_daily получают колонку ``model`` (NULL — до этой
  миграции или для не-vLLM-метрик);
* уникальный индекс расширяется: (metric, hour/day, COALESCE(gpu,-1),
  COALESCE(model,'')) — смена модели внутри окна даёт отдельные строки;
* бэкфилл из metric_samples (raw-ретенция ~168ч): более старые окна
  остаются model=NULL (в фильтре модели не видны — ожидаемо, в «Все
  модели» — как были).
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

PAIRS = (
    ("metric_hourly", "hour", "idx_metric_hourly_metric_hour"),
    ("metric_daily", "day", "idx_metric_daily_metric_day"),
)


def _has_model_column(conn, table: str) -> bool:
    cols = {r[1] for r in conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()}
    return "model" in cols


def upgrade() -> None:
    conn = op.get_bind()
    for table, _, _ in PAIRS:
        if not _has_model_column(conn, table):
            op.execute(f"ALTER TABLE {table} ADD COLUMN model TEXT")
    for table, col, idx in PAIRS:
        op.execute(f"DROP INDEX IF EXISTS {idx}")
        op.execute(
            f"CREATE UNIQUE INDEX {idx} ON {table}"
            f"(metric, {col}, COALESCE(gpu, -1), COALESCE(model, ''))"
        )
    _backfill(conn)


def _backfill(conn) -> None:
    # hourly — из сырых данных окна (наличие модели — по первой сырой точке)
    op.execute(
        """UPDATE metric_hourly SET model = (
               SELECT s.model FROM metric_samples s
               WHERE s.metric = metric_hourly.metric
                 AND s.model IS NOT NULL
                 AND (metric_hourly.gpu IS NULL OR s.gpu = metric_hourly.gpu)
                 AND s.ts >= metric_hourly.hour AND s.ts < metric_hourly.hour + 3600
               LIMIT 1)
           WHERE model IS NULL"""
    )
    # daily — из сырых данных суток
    op.execute(
        """UPDATE metric_daily SET model = (
               SELECT s.model FROM metric_samples s
               WHERE s.metric = metric_daily.metric
                 AND s.model IS NOT NULL
                 AND (metric_daily.gpu IS NULL OR s.gpu = metric_daily.gpu)
                 AND s.ts >= metric_daily.day AND s.ts < metric_daily.day + 86400
               LIMIT 1)
           WHERE model IS NULL"""
    )


def downgrade() -> None:
    for table, col, idx in PAIRS:
        op.execute(f"DROP INDEX IF EXISTS {idx}")
        op.execute(f"CREATE UNIQUE INDEX {idx} ON {table}(metric, {col}, COALESCE(gpu, -1))")
    # SQLite: удаление колонок — пересоздание таблиц не стоит; колонка inert.
    pass
