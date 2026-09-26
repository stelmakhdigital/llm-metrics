"""Log tailer (F3, ТЗ §3.1): file-tail по offset+inode / ``docker logs -f``.

Источники — ``sources.logs`` конфига (``{name, type: file|docker, path|container}``),
опрос раз в ``poll_seconds`` (default 1 с). Инвариант ТЗ §8.2: сбой одного
источника не роняет остальных — статус каждого источника в
``SourceRegistry`` под ключом ``logs.<name>``.

* file: seek к offset (байты), readline до конца; ротация (смена inode или
  уменьшение размера) — перечитываем новый файл с начала; при исчезновении
  файла — источник offline (``last_error``), дальше опрашиваем до появления.
  Первая встреча файла — старт с конца (backfill всей истории не делаем).
* docker: subprocess ``docker logs -t -f --tail=0 <container>`` (pipe,
  только новые строки). Если docker CLI недоступен — источник offline с
  ``last_error`` (см. README, секция «Логи vLLM»); повтор раз в 60 с.

Хранение: ``log_entries`` (``ts`` — epoch-мс UTC, ``level`` — канонический,
остальное — ``line``). Флеш в БД — батчами: ≥500 строк или ≥1 с в буфере.
Ретенция: раз в час ``DELETE ts < now - retention_days`` батчами.
Скоростной ориентир — 100k строк/день (~1.2 стр/с) запас по пропускной
способности (readline-цикл + batch insert) многократный.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..config import LogSource, LogSources
from ..collectors.base import SourceRegistry, wait_cancelable
from .parse import parse_line

log = logging.getLogger(__name__)

__all__ = ["LogTailer", "LogLineBuffer", "purge_old_logs"]

#: Пороги флеша буфера (строки/возраст)
FLUSH_MAX_LINES = 500
FLUSH_MAX_AGE_S = 1.0
#: Период повторных попыток docker-источника при ошибке
DOCKER_RETRY_S = 60.0
#: Батч удаления ретенцией
PURGE_BATCH = 5_000


def _status_key(name: str) -> str:
    return f"logs.{name}"


class LogLineBuffer:
    """Последние проиндексированные строки (ring ≤maxlen) для SSE /api/logs/live.

    Все обращения — в одном asyncio-loop (tailer + SSE), lock не нужен.
    """

    def __init__(self, maxlen: int = 5_000):
        self._buf: deque[dict[str, Any]] = deque(maxlen=maxlen)

    def add_many(self, entries: list[dict[str, Any]]) -> None:
        self._buf.extend(entries)

    def all(self) -> list[dict[str, Any]]:
        return list(self._buf)

    def __len__(self) -> int:
        return len(self._buf)


@dataclass
class _FileState:
    offset: int = 0
    inode: int | None = None
    initialized: bool = False  # первая встреча — старт с конца файла


@dataclass
class _DockerState:
    name: str  # имя источника (ключ статуса — logs.<name>)
    container: str
    proc: asyncio.subprocess.Process | None = None
    reader: asyncio.Task | None = None
    queue: asyncio.Queue[str] = field(default_factory=asyncio.Queue)
    exit_error: str | None = None
    next_retry: float = 0.0


class LogTailer:
    """Один цикл опроса всех log-источников (запускается как asyncio-task)."""

    def __init__(
        self,
        cfg: LogSources,
        db,  # aiosqlite.Connection
        statuses: SourceRegistry,
        buffer: LogLineBuffer | None = None,
    ) -> None:
        self.cfg = cfg
        self.db = db
        self.statuses = statuses
        self.buffer = buffer if buffer is not None else LogLineBuffer()
        self._files: dict[str, _FileState] = {}
        self._dockers: dict[str, _DockerState] = {}
        self._pending: list[dict[str, Any]] = []
        self._last_flush = time.time()
        self._last_purge_hour: int | None = None

    # ------------------------------------------------------------- цикл
    async def run(self, stop: asyncio.Event) -> None:
        """Цикл опроса раз в ``poll_seconds`` до stop-события."""
        interval = max(0.2, self.cfg.poll_seconds)
        log.info(
            "log tailer started: %s (interval %.1fs, retention %dd)",
            [s.name for s in self.cfg.sources],
            interval,
            self.cfg.retention_days,
        )
        while not stop.is_set():
            t0 = time.monotonic()
            try:
                await self.poll_once()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — сбой цикла не роняет приложение
                log.exception("log tailer cycle failed")
            if stop.is_set():
                break
            await wait_cancelable(stop, interval - (time.monotonic() - t0))
        await self.shutdown()
        log.info("log tailer stopped")

    async def shutdown(self) -> None:
        for st in self._dockers.values():
            await self._stop_docker(st)
        await self.flush(force=True)

    async def poll_once(self) -> None:
        """Опрос всех источников + флеш/ретенция (один шаг цикла)."""
        for src in self.cfg.sources:
            try:
                if src.type == "file":
                    lines = await asyncio.to_thread(
                        self._read_file_lines, src
                    )
                else:
                    lines = await self._poll_docker(src)
            except asyncio.CancelledError:
                raise
            except FileNotFoundError as e:
                self.statuses[_status_key(src.name)].fail(
                    f"файл отсутствует: {src.path} ({e})"
                )
                continue
            except Exception as e:  # noqa: BLE001 — сбой источника изолирован
                self.statuses[_status_key(src.name)].fail(f"{type(e).__name__}: {e}")
                continue
            if lines:
                self.statuses[_status_key(src.name)].ok()
                self._add_lines(src.name, lines)
            else:
                # Нет новых строк — источник жив, но и не ошибался
                st = self.statuses[_status_key(src.name)]
                if st.status != "offline":
                    st.ok()

        now = time.time()
        if self._pending and (
            len(self._pending) >= FLUSH_MAX_LINES or now - self._last_flush >= FLUSH_MAX_AGE_S
        ):
            await self.flush()
        await self._maybe_purge()

    # ------------------------------------------------------------- file
    def _read_file_lines(self, src: LogSource) -> list[str]:
        """Новые строки файла (offset+inode); при ротации — с начала нового.

        FileNotFoundError пробрасывается (→ статус offline).
        """
        st = self._files.setdefault(src.name, _FileState())
        path = src.path
        assert path is not None
        info = os.stat(path)
        if st.inode is not None and (
            info.st_ino != st.inode or info.st_size < st.offset
        ):
            # Ротация (смена inode) или truncate — новый файл читаем с начала
            st.offset, st.inode = 0, info.st_ino
        if not st.initialized:
            # Первая встреча: старт с конца (не индексировать старую историю)
            st.offset, st.inode, st.initialized = info.st_size, info.st_ino, True
            return []
        lines: list[str] = []
        with open(path, "rb") as f:
            f.seek(st.offset)
            while True:
                chunk = f.readline()
                if not chunk:
                    break
                line = chunk.decode("utf-8", "replace").rstrip("\r\n")
                if line.strip():
                    lines.append(line)
                st.offset += len(chunk)
        return lines

    # ----------------------------------------------------------- docker
    async def _poll_docker(self, src: LogSource) -> list[str]:
        st = self._dockers.setdefault(
            src.name,
            _DockerState(name=src.name, container=src.container or ""),
        )
        assert src.container, "container обязателен для источника type=docker"

        if st.proc is None or st.proc.returncode is not None:
            if st.exit_error:
                # процесс завершился с ошибкой — перезапуск по расписанию
                self.statuses[_status_key(st.name)].fail(f"docker logs: {st.exit_error}")
                self._maybe_restart_docker(st)
            elif time.monotonic() >= st.next_retry:
                await self._start_docker(st)
        lines: list[str] = []
        while not st.queue.empty():
            lines.append(st.queue.get_nowait())
        return lines

    async def _start_docker(self, st: _DockerState) -> None:
        if shutil.which("docker") is None:
            st.next_retry = time.monotonic() + DOCKER_RETRY_S
            self.statuses[_status_key(st.name)].fail(
                "docker CLI не найден (нужен в образе api + /var/run/docker.sock)"
            )
            return
        try:
            st.proc = await asyncio.create_subprocess_exec(
                "docker", "logs", "-t", "-f", "--tail=0", st.container,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            st.reader = asyncio.create_task(self._docker_reader(st))
            self.statuses[_status_key(st.name)].ok()
        except (OSError, ValueError) as e:
            st.next_retry = time.monotonic() + DOCKER_RETRY_S
            st.proc = None
            self.statuses[_status_key(st.name)].fail(
                f"docker logs не запущен: {type(e).__name__}: {e}"
            )

    def _maybe_restart_docker(self, st: _DockerState) -> None:
        """Планирует перезапуск упавшего процесса (по расписанию retry)."""
        if time.monotonic() < st.next_retry:
            return
        st.exit_error = None
        asyncio.ensure_future(self._start_docker(st))

    def _restart_docker(self, st: _DockerState) -> _DockerState:
        st.exit_error = None
        if time.monotonic() < st.next_retry:
            return st
        # перезапуск асинхронно (poll_once — async-контекст)
        asyncio.ensure_future(self._start_docker(st))
        return st

    async def _stop_docker(self, st: _DockerState) -> None:
        if st.reader is not None:
            st.reader.cancel()
            try:
                await st.reader
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            st.reader = None
        if st.proc is not None and st.proc.returncode is None:
            st.proc.kill()
            try:
                await st.proc.wait()
            except Exception:  # noqa: BLE001
                pass
        st.proc = None
        st.exit_error = None
        while not st.queue.empty():
            st.queue.get_nowait()

    async def _docker_reader(self, st: _DockerState) -> None:
        """Читает pipe дочернего процесса в очередь (по строкам)."""
        try:
            assert st.proc is not None
            async for raw in st.proc.stdout:  # type: ignore[union-attr]
                line = raw.decode("utf-8", "replace").rstrip("\r\n")
                if line.strip():
                    await st.queue.put(line)
            err = b""
            if st.proc.stderr is not None:
                err = await st.proc.stderr.read()
            code = st.proc.returncode
            st.exit_error = (
                f"процесс завершился (exit={code})"
                + (f": {err.decode('utf-8', 'replace').strip()[:300]}" if err else "")
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            st.exit_error = f"reader: {type(e).__name__}: {e}"

    # ------------------------------------------------------------- flush
    def _add_lines(self, source: str, lines: list[str]) -> None:
        now_ms = int(time.time() * 1000)
        for line in lines:
            ts, level = parse_line(line, now_ms)
            self._pending.append(
                {"ts": ts, "level": level, "line": line, "source": source}
            )

    async def flush(self, force: bool = False) -> int:
        """Запись буфера в log_entries (+ LogLineBuffer для SSE)."""
        if not self._pending:
            return 0
        if not force and len(self._pending) < FLUSH_MAX_LINES and (
            time.time() - self._last_flush < FLUSH_MAX_AGE_S
        ):
            return 0
        entries = self._pending
        self._pending = []
        self._last_flush = time.time()
        await self.db.executemany(
            "INSERT INTO log_entries (ts, level, line, source) VALUES (?, ?, ?, ?)",
            [(e["ts"], e["level"], e["line"], e["source"]) for e in entries],
        )
        # lastrowid через last_insert_rowid() (aiosqlite: надёжнее, чем
        # чтение .lastrowid с другого потока)
        last_id = (await self.db.execute_fetchall("SELECT last_insert_rowid() AS i"))[0]["i"]
        await self.db.commit()
        first_id = last_id - len(entries) + 1
        buffered = [
            {"id": first_id + i, **e} for i, e in enumerate(entries)
        ]
        self.buffer.add_many(buffered)
        return len(entries)

    # ------------------------------------------------------------ ретенция
    async def _maybe_purge(self) -> None:
        hour = int(time.time() // 3600)
        if self._last_purge_hour is None:
            self._last_purge_hour = hour
            return
        if hour == self._last_purge_hour:
            return
        self._last_purge_hour = hour
        try:
            await purge_old_logs(self.db, self.cfg.retention_days)
        except Exception:  # noqa: BLE001 — сбой чистки не роняет tailer
            log.exception("log retention purge failed")


async def purge_old_logs(
    db, retention_days: int, batch: int = PURGE_BATCH
) -> int:
    """Удаляет log_entries старше ``retention_days`` батчами (ТЗ §5.6)."""
    cutoff_ms = (int(time.time()) - retention_days * 86400) * 1000
    deleted = 0
    while True:
        cur = await db.execute(
            """DELETE FROM log_entries
               WHERE id IN (SELECT id FROM log_entries WHERE ts < ? LIMIT ?)""",
            (cutoff_ms, batch),
        )
        n = cur.rowcount or 0
        deleted += n
        if n < batch:
            break
    if deleted:
        await db.commit()
        log.info("log retention: удалено %s строк старше %s дн", deleted, retention_days)
    return deleted
