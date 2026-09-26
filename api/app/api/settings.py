"""GET/PUT /api/settings/cost — тарифы (версионирование, ТЗ §6/§7).

PUT не редактирует старые версии: добавляет новую (updated_at = now)
на основе текущей; стоимость истории пересчитывается на лету.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from ..cost.rates import add_version, get_settings_payload

router = APIRouter(prefix="/api/settings")


class CostRateUpdate(BaseModel):
    currency: str | None = Field(None, min_length=1, max_length=10)
    rate_per_kwh_usd: float | None = Field(None, ge=0)
    system_baseline_watts: float | None = Field(None, ge=0)
    token_prompt_per_million_usd: float | None = Field(None, ge=0)
    token_completion_per_million_usd: float | None = Field(None, ge=0)

    @field_validator("currency")
    @classmethod
    def _currency(cls, v: str | None) -> str | None:
        return v.strip().upper() if v else None

    def has_fields(self) -> bool:
        return any(
            getattr(self, f) is not None
            for f in (
                "currency",
                "rate_per_kwh_usd",
                "system_baseline_watts",
                "token_prompt_per_million_usd",
                "token_completion_per_million_usd",
            )
        )


@router.get("/cost")
async def get_cost_settings(request: Request):
    """{current, history[]} — history: новые версии первыми."""
    db = request.app.state.db
    return await get_settings_payload(db)


@router.put("/cost")
async def put_cost_settings(request: Request, body: CostRateUpdate):
    """Новая версия тарифа (старые не меняются)."""
    if not body.has_fields():
        raise HTTPException(400, "Не передано ни одно поле тарифа")
    db = request.app.state.db
    new = await add_version(db, body.model_dump())
    payload = await get_settings_payload(db)
    return {"current": new, "history": payload["history"]}
