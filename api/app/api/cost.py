"""GET /api/cost?from&to — расчёт стоимости (ТЗ §5.5, §6, §7)."""

from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException, Query, Request

from ..cost.engine import compute_cost

router = APIRouter(prefix="/api")


@router.get("/cost")
async def get_cost(
    request: Request,
    from_: int | None = Query(None, alias="from", ge=0),
    to: int | None = Query(None, ge=0),
):
    """Стоимость за период. По умолчанию — «сегодня» (00:00 UTC → now)."""
    to = to if to is not None else int(time.time())
    if from_ is None:
        from_ = (to // 86400) * 86400  # 00:00 UTC сегодня
    if from_ >= to:
        raise HTTPException(400, "from должен быть раньше to")
    db = request.app.state.db
    return await compute_cost(db, from_, to)
