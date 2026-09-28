"""per-GPU колонка в metric_hourly/metric_daily (ТЗ §4/§6: P_total = Σ_gpu + P_base)

Revision ID: 0003
Revises: 0002

* metric_hourly/metric_daily получают колонку ``gpu`` (NULL для не-GPU-метрик);
  уникальность — (metric, hour/day, COALESCE(gpu, -1)), т.е. для gpu=NULL
  по-прежнему одна строка на окно, для gpu-метрик — строка на gpu;
* бэкфилл (одноразово): старые gpu-строки (gpu IS NULL, метрики gpu_*) были
  плоской смесью карт — удаляются и пересчитываются per-gpu из
  metric_samples (raw-ретенция ~7дн); более старые окна — разрыв (не 0),
  daily — пересчёт из пересчитанных hourly.

Свежие БД (созданные обновлённым schema.py): колонка уже есть — шаги
идемпотентны.
"""

from collections import defaultdict

from alembic import op

from app.aggregator import MIN_HOURLY_PER_DAY, p95_of_sorted

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

# (таблица, колонка окна, имя уникального индекса)
PAIRS = (
    ("metric_hourly", "hour", "idx_metric_hourly_metric_hour"),
    ("metric_daily", "day", "idx_metric_daily_metric_day"),
)


def _has_gpu_column(conn, table: str) -> bool:
    cols = {r[1] for r in conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()}
    return "gpu" in cols


def upgrade() -> None:
    conn = op.get_bind()
    # 1) gpu-колонка (в свежей БД уже есть из schema.py — пропуск)
    for table, _, _ in PAIRS:
        if not _has_gpu_column(conn, table):
            op.execute(f"ALTER TABLE {table} ADD COLUMN gpu INTEGER")
    # 2) уникальный индекс (metric, окно, COALESCE(gpu, -1))
    for table, col, idx in PAIRS:
        op.execute(f"DROP INDEX IF EXISTS {idx}")
        op.execute(
            f"CREATE UNIQUE INDEX {idx} ON {table}(metric, {col}, COALESCE(gpu, -1))"
        )
    _backfill(conn)


def _backfill(conn) -> None:
    # 0) старые смешанные gpu-строки (gpu NULL) — удаляем, пересчитываем per-gpu
    for table, _, _ in PAIRS:
        op.execute(f"DELETE FROM {table} WHERE metric LIKE 'gpu_%' AND gpu IS NULL")

    # --- hourly из metric_samples (raw-ретенция): группировка (metric, час, gpu)
    groups: dict[tuple[str, int, int], list[float]] = defaultdict(list)
    for metric, h, g, value in conn.exec_driver_sql(
        """SELECT metric, (ts/3600)*3600, COALESCE(gpu, -1), value
           FROM metric_samples WHERE metric LIKE 'gpu_%'"""
    ).fetchall():
        groups[(metric, h, g)].append(value)
    for (metric, h, g), values in groups.items():
        values.sort()
        n = len(values)
        conn.exec_driver_sql(
            """INSERT INTO metric_hourly (metric, hour, gpu, avg, min, max, p95, count)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT DO NOTHING""",
            (metric, h, g if g >= 0 else None, sum(values) / n,
             values[0], values[-1], p95_of_sorted(values), n),
        )

    # --- daily из (пересчитанных) per-gpu hourly-строк, ≥ MIN_HOURLY_PER_DAY часов
    day_groups: dict[tuple[str, int, int], list[tuple]] = defaultdict(list)
    for metric, d, g, av, mn, mx, p95v, cnt in conn.exec_driver_sql(
        """SELECT metric, (hour/86400)*86400, COALESCE(gpu, -1),
                  avg, min, max, p95, count
           FROM metric_hourly WHERE metric LIKE 'gpu_%'"""
    ).fetchall():
        day_groups[(metric, d, g)].append((av, mn, mx, p95v, cnt))
    for (metric, d, g), hs in day_groups.items():
        if len(hs) < MIN_HOURLY_PER_DAY:
            continue
        ct = sum(r[4] for r in hs)
        if not ct:
            continue
        conn.exec_driver_sql(
            """INSERT INTO metric_daily (metric, day, gpu, avg, min, max, p95, sum, count)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT DO NOTHING""",
            (metric, d, g if g >= 0 else None,
             sum(r[0] for r in hs) / len(hs),
             min(r[1] for r in hs), max(r[2] for r in hs),
             sum(r[3] for r in hs) / len(hs),
             sum(r[0] * r[4] for r in hs), ct),
        )
    conn.commit()


def downgrade() -> None:
    for table, _, idx in PAIRS:
        op.execute(f"DROP INDEX IF EXISTS {idx}")
        with op.batch_alter_table(table) as b:
            b.drop_column("gpu")
    op.execute(
        "CREATE UNIQUE INDEX idx_metric_hourly_metric_hour "
        "ON metric_hourly(metric, hour)"
    )
    op.execute(
        "CREATE UNIQUE INDEX idx_metric_daily_metric_day "
        "ON metric_daily(metric, day)"
    )
