"""REST-роуты логов (F3, ТЗ §5.6/§7): /api/logs, stats, export, live, sources.

Времена в запросах — epoch-секунды UTC; ``ts`` в строках ответа —
epoch-миллисекунды (точность до мс, ТЗ §5.6). Направление — ts desc
(новые сверху). ``query`` — LIKE по line (``%``/``_`` экранируются).
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import time
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from ..logs.parse import LEVELS, LEVEL_ALIASES, normalize_level
from ..logs.patterns import parse_vllm_stat
from ..storage.db import rows_to_dicts

router = APIRouter(prefix="/api")

#: Допустимые размеры страниц (ТЗ §5.6: 100/250/500)
PAGE_SIZES = (100, 250, 500)
#: Лимит экспорта
EXPORT_MAX_LIMIT = 100_000
#: Батч чтения экспорта (чтобы не держать в памяти весь выбор)
EXPORT_BATCH = 5_000

LIVE_FLUSH_S = 0.5   # период опроса буфера в SSE (≤2с — «не реже»)
LIVE_HEARTBEAT_S = 15.0


def _window(from_: int | None, to: int | None) -> tuple[int, int]:
    now = int(time.time())
    to = to if to is not None else now
    from_ = from_ if from_ is not None else to - 86400
    if from_ < 0 or to <= from_:
        raise HTTPException(400, "Некорректный период: нужно from < to")
    return from_, to


def _like_escape(q: str) -> str:
    """Экранирует LIKE-спецсимволы (\\, %, _)."""
    return q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _filters(
    level: str, query: str, source: str
) -> tuple[list[str], list[Any]]:
    """Фильтры (кроме периода) → список SQL-условий + параметры."""
    conds: list[str] = []
    params: list[Any] = []
    if level:
        raw = [t.strip() for t in level.split(",") if t.strip()]
        unknown = [x for x in raw if x.upper() not in LEVEL_ALIASES]
        if unknown:
            raise HTTPException(400, f"Неизвестный уровень: {', '.join(unknown)}")
        lvls = [normalize_level(x) for x in raw]
        if lvls:
            conds.append(f"level IN ({','.join('?' * len(lvls))})")
            params.extend(lvls)
    if query:
        conds.append(r"line LIKE ? ESCAPE '\'")
        params.append(f"%{_like_escape(query)}%")
    if source:
        conds.append("source = ?")
        params.append(source)
    return conds, params


def _where(conds: list[str]) -> str:
    """` WHERE c1 AND c2` или `''`."""
    return (" WHERE " if conds else "") + " AND ".join(conds)


def _resolve_limit(limit: int) -> int:
    if limit not in PAGE_SIZES:
        raise HTTPException(400, f"limit должен быть одним из {PAGE_SIZES}")
    return limit


# ------------------------------------------------------------------------ logs
@router.get("/logs")
async def logs_page(
    request: Request,
    from_: int | None = Query(None, alias="from"),
    to: int | None = None,
    level: str = "",
    query: str = "",
    source: str = "",
    offset: int = Query(0, ge=0),
    limit: int = Query(100),
) -> dict[str, Any]:
    """Страница логов: {rows: [{id, ts(мс), level, source, line, stats}],
    total (по всем отфильтрованным), has_more} — ts desc."""
    from_, to = _window(from_, to)
    limit = _resolve_limit(limit)
    conds, params = _filters(level, query, source)
    conds += ["ts >= ?", "ts <= ?"]
    params += [from_ * 1000, to * 1000]
    where = _where(conds)
    db = request.app.state.db
    total = (
        await db.execute_fetchall(f"SELECT COUNT(*) AS n FROM log_entries{where}", params)
    )[0]["n"]
    rows = rows_to_dicts(
        await db.execute_fetchall(
            f"""SELECT id, ts, level, source, line FROM log_entries{where}
                ORDER BY ts DESC, id DESC LIMIT ? OFFSET ?""",
            [*params, limit, offset],
        )
    )
    out = [
        {
            "id": r["id"],
            "ts": r["ts"],
            "level": r["level"],
            "source": r["source"],
            "line": r["line"],
            "stats": parse_vllm_stat(r["line"]),
        }
        for r in rows
    ]
    return {
        "rows": out,
        "total": total,
        "has_more": offset + len(out) < total,
        "from": from_,
        "to": to,
    }


# ------------------------------------------------------------------------ stats
@router.get("/logs/stats")
async def logs_stats(
    request: Request,
    from_: int | None = Query(None, alias="from"),
    to: int | None = None,
) -> dict[str, Any]:
    """Подсчёт по дням/уровням (дни — календарные по TZ сервера):
    {by_day: [{day (epoch-с начала суток локально), levels {...}, total}]}.
    Окно ограничено 400 днями (ретенция логов ≤ 365) — старее
    данных нет, а by_day на огромном окне бессмысленно велик."""
    from_, to = _window(from_, to)
    max_span = 400 * 86400
    if to - from_ > max_span:
        from_ = to - max_span
    off = int(datetime.now().astimezone().utcoffset().total_seconds())
    db = request.app.state.db
    rows = rows_to_dicts(
        await db.execute_fetchall(
            """SELECT (ts/1000 + ?) / 86400 AS day, level, COUNT(*) AS n
               FROM log_entries
               WHERE ts >= ? AND ts <= ?
               GROUP BY day, level""",
            (off, from_ * 1000, to * 1000),
        )
    )
    counts: dict[int, dict[str, int]] = {}
    for r in rows:
        counts.setdefault(r["day"], {})[r["level"]] = r["n"]
    first_day = (from_ + off) // 86400
    last_day = (to + off) // 86400
    by_day = []
    for day in range(first_day, last_day + 1):
        levels = counts.get(day, {})
        by_day.append(
            {
                "day": day * 86400 - off,  # epoch-с: локальная полночь
                "levels": {k: levels.get(k, 0) for k in LEVELS},
                "total": sum(levels.values()),
            }
        )
    return {"from": from_, "to": to, "by_day": by_day}


# ----------------------------------------------------------------------- export
@router.get("/logs/export")
async def logs_export(
    request: Request,
    from_: int | None = Query(None, alias="from"),
    to: int | None = None,
    level: str = "",
    query: str = "",
    source: str = "",
    format: Literal["txt", "csv"] = "txt",
    limit: int = Query(EXPORT_MAX_LIMIT, ge=1),
) -> StreamingResponse:
    """Экспорт отфильтрованного диапазона файлом (txt: человекочитаемо,
    csv: ts,level,source,line) — потоково, не более ``limit`` строк."""
    from_, to = _window(from_, to)
    if limit > EXPORT_MAX_LIMIT:
        raise HTTPException(400, f"limit не больше {EXPORT_MAX_LIMIT}")
    conds, params = _filters(level, query, source)
    conds += ["ts >= ?", "ts <= ?"]
    params += [from_ * 1000, to * 1000]
    where = _where(conds)
    db = request.app.state.db

    def fmt_ts(ts_ms: int) -> str:
        return datetime.fromtimestamp(ts_ms / 1000).strftime("%Y-%m-%d %H:%M:%S.") + (
            f"{ts_ms % 1000:03d}"
        )

    async def gen():
        if format == "csv":
            yield b"ts,level,source,line\n"
        last_id = None
        emitted = 0
        while emitted < limit:
            chunk_limit = min(EXPORT_BATCH, limit - emitted)
            sql = (
                f"SELECT id, ts, level, source, line FROM log_entries{where}"
                + (" AND id < ?" if last_id is not None else "")
                + " ORDER BY id DESC LIMIT ?"
            )
            sql_params = [*params, last_id, chunk_limit] if last_id is not None else [*params, chunk_limit]
            rows = rows_to_dicts(await db.execute_fetchall(sql, sql_params))
            if not rows:
                break
            buf = io.StringIO()
            if format == "csv":
                w = csv.writer(buf, lineterminator="\n")
                for r in rows:
                    w.writerow([fmt_ts(r["ts"]), r["level"], r["source"], r["line"]])
            else:
                for r in rows:
                    buf.write(f"{fmt_ts(r['ts'])} {r['level']:<8} [{r['source']}] {r['line']}\n")
            yield buf.getvalue().encode("utf-8")
            emitted += len(rows)
            last_id = rows[-1]["id"]
            if len(rows) < chunk_limit:
                break

    filename = f"llm-logs-{from_}-{to}.{format}"
    media = (
        "text/csv; charset=utf-8" if format == "csv" else "text/plain; charset=utf-8"
    )
    return StreamingResponse(
        gen(),
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# -------------------------------------------------------------------- sources
@router.get("/logs/sources")
async def logs_sources(request: Request) -> dict[str, Any]:
    """Список log-источников + их статус (offline/last_error) для UI."""
    cfg = request.app.state.config
    statuses = request.app.state.statuses
    out = [
        {
            "name": s.name,
            "type": s.type,
            "path": s.path,
            "container": s.container,
            **statuses[f"logs.{s.name}"].to_dict(),
        }
        for s in cfg.sources.logs.sources
    ]
    return {"sources": out, "poll_seconds": cfg.sources.logs.poll_seconds}


# ------------------------------------------------------------------------ live
@router.get("/logs/live")
async def logs_live(request: Request) -> StreamingResponse:
    """SSE-хвост: ``data: {"ts","source","level","line"}`` на строку, из
    ring-буфера tailer'а (обновления не реже чем раз в 2 с; дублей по id нет).

    При подключении отдаётся текущий буфер (последние ≤5000 строк) — клиент
    дедуплицирует по id/ts+line.
    """
    buffer = request.app.state.log_buffer

    async def gen():
        yield "retry: 2000\n\n"
        last_id = 0
        last_ping = time.monotonic()
        while True:
            sent = False
            for e in buffer.all():
                eid = e.get("id", 0)
                if eid <= last_id:
                    continue
                last_id = eid
                sent = True
                payload = json.dumps(
                    {
                        "ts": e["ts"],
                        "source": e["source"],
                        "level": e["level"],
                        "line": e["line"],
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                yield f"data: {payload}\n\n"
            if not sent and time.monotonic() - last_ping >= LIVE_HEARTBEAT_S:
                yield ": ping\n\n"
                last_ping = time.monotonic()
            await asyncio.sleep(LIVE_FLUSH_S)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
