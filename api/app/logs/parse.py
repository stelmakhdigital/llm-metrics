"""Парсинг строк лога: таймстамп (первые 1–3 токена) и уровень (F3).

Форматы ts:
* ISO 8601: ``2026-07-25T12:34:56.789``, ``...+03:00``, ``Z``,
  дата и время в разных токенах: ``2026-07-25 12:34:56,789`` (uvicorn,
  дробная часть через запятую);
* epoch: секунды (``1756200000`` / ``1756200000.123``) и миллисекунды;
* syslog: ``Sep 25 12:34:56``;
* vLLM-короткий: ``07-10 12:34:56`` (без года).

Нативные таймстампы без timezone — время локальное сервера (ТЗ §10.4);
при неудаче парсинга — время приёма строки. Уровень: DEBUG/INFO/
(WARNING|WARN)/(ERROR|ERR)/(CRITICAL|FATAL); не нашлось → INFO
(строки без уровня, например stdout-мусор — тоже INFO).
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

#: Канонические уровни (таблицы log_entries.level, stats, фильтры).
LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")

#: Псевдонимы → канонический уровень (upper-case ключи).
LEVEL_ALIASES: dict[str, str] = {
    "DEBUG": "DEBUG",
    "INFO": "INFO",
    "WARNING": "WARNING",
    "WARN": "WARNING",
    "ERROR": "ERROR",
    "ERR": "ERROR",
    "CRITICAL": "CRITICAL",
    "FATAL": "CRITICAL",
}

_MONTHS = {
    m: i
    for i, m in enumerate(
        ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
         "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"),
        start=1,
    )
}

_RE_EPOCH_S = re.compile(r"^(\d{10})(?:\.(\d{1,9}))?$")
_RE_EPOCH_MS = re.compile(r"^(\d{13})(?:\.(\d{1,9}))?$")
_RE_ISO_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_RE_MD = re.compile(r"^(\d{2})-(\d{2})$")  # MM-DD (vLLM)
_RE_TIME = re.compile(r"^(\d{2}):(\d{2}):(\d{2})(?:[.,](\d{1,9}))?$")


def normalize_level(raw: str) -> str:
    """«WARN»/«err»/«FATAL» → канонический уровень; неизвестный → INFO."""
    return LEVEL_ALIASES.get(raw.strip("[](){}<>,:'\"").upper(), "INFO")


def _dt_to_ms(dt: datetime) -> int:
    """datetime (tz-aware или local) → epoch-мс UTC."""
    if dt.tzinfo is None:
        dt = dt.astimezone()  # интерпретировать в TZ сервера
    return int(dt.timestamp() * 1000)


def _ymd_to_ms(mo: int, day: int, time_str: str, year: int) -> int | None:
    """(месяц, день, «HH:MM:SS[.,fff]», год) → epoch-мс (локальное время)."""
    m = _RE_TIME.match(time_str)
    if not m:
        return None
    hh, mm, ss = int(m[1]), int(m[2]), int(m[3])
    frac = m[4]
    ms = int(frac.ljust(3, "0")[:3]) if frac else 0
    try:
        dt = datetime(year, mo, day, hh, mm, ss, tzinfo=None)
    except ValueError:
        return None
    ts = _dt_to_ms(dt)
    # «Dec 31» из прошлого года для января: если дата «в будущем» более чем
    # на 2 дня — считаем предшествующий год (syslog без года)
    now_ms = _dt_to_ms(datetime.now())
    if ts > now_ms + 2 * 86400 * 1000:
        try:
            dt = dt.replace(year=year - 1)
            ts = _dt_to_ms(dt)
        except ValueError:
            pass
    return ts + ms


def parse_ts_ms(line: str) -> int | None:
    """Таймстамп строки из первых 1–3 токенов → epoch-мс UTC или None."""
    parts = line.lstrip()[:32].split(" ", 3)
    if not parts:
        return None
    t0 = parts[0]

    m = _RE_EPOCH_S.match(t0)
    if m:
        ts = int(m[1])
        ms = int(m[2].ljust(3, "0")[:3]) if m[2] else 0  # дробные секунды → мс
        return ts * 1000 + ms
    m = _RE_EPOCH_MS.match(t0)
    if m:
        return int(m[1])

    if "T" in t0 and len(t0) > 8:  # ISO в одном токене
        try:
            return _dt_to_ms(
                datetime.fromisoformat(t0.replace(",", ".").replace("Z", "+00:00"))
            )
        except ValueError:
            pass

    if len(parts) < 2:
        return None
    t1 = parts[1]
    now_year = datetime.now().year
    if _RE_ISO_DATE.match(t0):  # «2026-07-25 12:34:56[.789]»
        mo, day = int(t0[5:7]), int(t0[8:10])
        m = _RE_TIME.match(t1)
        if not m:
            return None
        frac = m[4]
        try:
            dt = datetime(
                int(t0[:4]), mo, day, int(m[1]), int(m[2]), int(m[3]), tzinfo=None
            )
        except ValueError:
            return None
        ms = int(frac.ljust(3, "0")[:3]) if frac else 0
        return _dt_to_ms(dt) + ms
    if _RE_MD.match(t0):  # «07-10 12:34:56» (vLLM, без года)
        return _ymd_to_ms(int(t0[:2]), int(t0[3:5]), t1, now_year)
    if t0[:3] in _MONTHS:  # syslog: «Sep 25 12:34:56» (день/время могут быть
        rest = t0[3:].strip()  # в следующих токенах)
        toks = line.lstrip().split()
        if rest:
            day_s, time_s = rest, (toks[1] if len(toks) > 1 else "")
        elif len(toks) >= 3:
            day_s, time_s = toks[1], toks[2]
        else:
            day_s, time_s = "", ""
        if day_s.isdigit():
            return _ymd_to_ms(_MONTHS[t0[:3]], int(day_s), time_s, now_year)
    return None


def parse_level(line: str) -> str:
    """Уровень из первых токенов (``[INFO]``, ``WARN:`` и т.п.); иначе INFO."""
    for tok in line.lstrip().split(" ", 8)[:8]:
        lvl = LEVEL_ALIASES.get(tok.strip("[](){}<>,:'\"").upper())
        if lvl is not None:
            return lvl
    return "INFO"


def parse_line(line: str, received_ts_ms: int) -> tuple[int, str]:
    """(ts-мс, уровень) строки; ts — из строки или время приёма."""
    ts = parse_ts_ms(line)
    return (ts if ts is not None else received_ts_ms), parse_level(line)
