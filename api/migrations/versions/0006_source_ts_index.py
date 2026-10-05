"""0006: индекс (source, ts) — запросы «последние выборки» (perf).

SELECT ... WHERE source='X' ORDER BY ts / MAX(ts) GROUP BY source (health/summary,
last_values, latest_model) до этого делали полный скан metric_samples
(10M+ строк: 1–6 c на запрос).
"""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_ms_source_ts "
        "ON metric_samples(source, ts)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_ms_source_ts")
