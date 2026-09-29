"""Почасовые дельты счётчиков vLLM по модели (model-фильтр >168ч, issue #5)

Revision ID: 0005
Revises: 0004

Новая таблица ``model_tokens``: дельты сырых счётчиков vLLM за закрытый
час, раздельно по метке ``model`` (prompt/completion токены, завершённые
запросы + finish reasons (JSON), preemptions, Δprefix hits/queries,
Δbucket-счётчиков длин (JSON)).

Пополняется агрегатором (catch-up, ``MAX_HOURS_PER_CYCLE``=96 ч за цикл)
из raw-выборок — бэкап последних 168 ч набирается в первые циклы после
деплоя. Для ``GET /api/model?model=...`` на периодах глубже
raw-ретенции — те же KPI, что по сырым данным, но из агрегата
(паттерн metric_hourly + model, 0004).
"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """CREATE TABLE IF NOT EXISTS model_tokens (
            ts INTEGER              NOT NULL,  -- epoch начала часа (UTC)
            model TEXT              NOT NULL,
            prompt_tokens INTEGER,
            completion_tokens INTEGER,
            requests_finished INTEGER,
            finish_reasons TEXT,     -- JSON {reason: n}
            preemptions INTEGER,
            prefix_hits INTEGER,
            prefix_queries INTEGER,
            prompt_dist TEXT,        -- JSON {le: delta}
            generation_dist TEXT,    -- JSON {le: delta}
            PRIMARY KEY (ts, model)
        )"""
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS model_tokens")
