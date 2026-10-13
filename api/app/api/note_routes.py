"""GET/PUT /api/note — файл заметки (вкладка «Note»).

Один markdown-файл в каталоге проекта (рядом с БД; в docker — bind
``./data`` → ``/data/note.md``). Перезаписывается целиком; внешние правки
(например, редактором на хосте) видны через GET. Путь переопределяется
``NOTE_PATH`` (относительный — от рабочей директории api).
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api")

MAX_CONTENT_CHARS = 2_000_000  # защита от случайной записи гигантского текста


def _note_path(request: Request) -> Path:
    """Путь заметки: NOTE_PATH → note.md рядом с БД."""
    cfg = request.app.state.config
    raw = cfg.note.note_path
    if raw:
        return Path(raw)
    return Path(cfg.storage.sqlite_path).parent / "note.md"


@router.get("/note")
async def get_note(request: Request) -> dict:
    path = _note_path(request)
    try:
        content = path.read_text(encoding="utf-8")
        mtime = int(path.stat().st_mtime)
        exists = True
    except FileNotFoundError:
        content, mtime, exists = "", None, False
    except OSError as e:
        raise HTTPException(500, f"не удалось прочитать заметку: {e}") from e
    return {"content": content, "exists": exists, "mtime": mtime, "path": str(path)}


class NoteUpdate(BaseModel):
    content: str = Field(min_length=0, max_length=MAX_CONTENT_CHARS)


@router.put("/note")
async def put_note(request: Request, body: NoteUpdate) -> dict:
    path = _note_path(request)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body.content, encoding="utf-8")
    except OSError as e:
        raise HTTPException(500, f"не удалось сохранить заметку: {e}") from e
    return {"saved": True, "mtime": int(time.time()), "path": str(path)}
