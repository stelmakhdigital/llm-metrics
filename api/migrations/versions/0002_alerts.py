"""alerts table (F4.1: журнал алертов)

Revision ID: 0002
Revises: 0001
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        rule TEXT    NOT NULL,  -- id правила
        level TEXT   NOT NULL,  -- warning | critical
        status TEXT  NOT NULL,  -- active | resolved
        message TEXT NOT NULL,
        triggered_at INTEGER NOT NULL,  -- epoch-с UTC
        resolved_at INTEGER               -- NULL пока активна
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_alerts_status ON alerts(status, triggered_at)",
]


def upgrade() -> None:
    for stmt in STATEMENTS:
        op.execute(stmt)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS alerts")
