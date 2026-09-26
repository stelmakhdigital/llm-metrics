"""initial schema (ТЗ §4)

Revision ID: 0001
Revises:
Create Date: 2026-07-25

Схема — единый источник истины: app.storage.schema.SCHEMA_STATEMENTS
(используется и bootstrap-ом приложения, и этой миграцией).
"""

from alembic import op

from app.storage.schema import SCHEMA_STATEMENTS

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in SCHEMA_STATEMENTS:
        op.execute(stmt)


def downgrade() -> None:
    # Индексы SQLite удаляются вместе с таблицами
    for table in (
        "gpu_devices",
        "settings",
        "log_entries",
        "tokens",
        "metric_daily",
        "metric_hourly",
        "metric_samples",
    ):
        op.drop_table(table)
