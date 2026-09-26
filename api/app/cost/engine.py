"""Cost engine (ТЗ §5.5, §6): стоимость = токены + электричество.

Формулы (ТЗ §6):
    kWh(t) = Σ (Σ_gpu P_gpu,i + P_base) * Δt / 3600 / 1000
    C_tok  = (prompt_tokens * rate_in + completion_tokens * rate_out) / 1_000_000
    C_elec = kWh * rate_per_kwh
    C_total = C_elec + C_tok

Источники (инвариант: пропуски — разрыв, не 0):
* Электричество — часы с сырыми выборками ``gpu_power`` (metric_samples):
  трапеции по соседним точкам + baseline (тариф часа) на покрытый интервал;
  более старые часы — ``avg`` из metric_hourly × длительность часа;
  часы без данных обеих таблиц не засчитываются.
* Токены — часы с сырыми счётчиками vLLM (metric_samples): сумма
  положительных приростов ``prompt_tokens_total`` / ``generation_tokens_total``
  / ``request_success_total_{reason}`` (устойчиво к рестартам счётчиков);
  более старые часы — таблица ``tokens``.
* Тарифы — версия, действовавшая на начало каждого часа (версионирование, §6).

Выборки — батчами по периоду (не по каждому часу): 4 запроса на источники
+ тарифы, остальное — Python.
"""

from __future__ import annotations

from collections import defaultdict

from .rates import get_versions, rate_for_ts

HOUR_S = 3600
DAY_S = 86_400
W_S_PER_KWH = 3_600_000

TOKEN_COUNTERS = ("prompt_tokens_total", "generation_tokens_total")
FINISH_REASON_PREFIX = "request_success_total_"


def _trapezoids(points: list[tuple[int, float]]) -> tuple[float, int]:
    """(энергия Вт·с, покрытые секунды) по отсортированным (ts, Вт)."""
    energy = 0.0
    for (t0, v0), (t1, v1) in zip(points, points[1:]):
        dt = t1 - t0
        if dt > 0:
            energy += 0.5 * (v0 + v1) * dt
    covered = points[-1][0] - points[0][0] if len(points) > 1 else 0
    return energy, max(0, covered)


def _positive_delta(prev: float | None, samples: list[tuple[int, float]]) -> float:
    """Сумма положительных приростов счётчика: от prev (до окна) по точкам."""
    delta = 0.0
    last = prev
    for _, v in samples:
        if last is not None and v > last:
            delta += v - last
        last = v
    return delta


async def compute_cost(db, from_s: int, to_s: int) -> dict:
    """GET /api/cost?from&to — расчёт стоимости за период [from, to]."""
    versions = await get_versions(db)
    if not versions:  # seed ещё не прошёл — нулевой тариф из конфига
        version = {
            "updated_at": 0, "currency": "USD", "rate_per_kwh_usd": 0.0,
            "system_baseline_watts": 0.0,
            "token_prompt_per_million_usd": 0.0,
            "token_completion_per_million_usd": 0.0,
        }

    # ------------------------------------------- батчевые выборки источников
    power_rows = await db.execute_fetchall(
        """SELECT ts, value FROM metric_samples
           WHERE metric = 'gpu_power' AND ts >= ? AND ts <= ? ORDER BY ts""",
        (from_s, to_s),
    )
    power_by_hour: dict[int, list[tuple[int, float]]] = defaultdict(list)
    for r in power_rows:
        power_by_hour[(r["ts"] // HOUR_S) * HOUR_S].append((r["ts"], float(r["value"])))

    hourly_rows = await db.execute_fetchall(
        """SELECT hour, avg FROM metric_hourly
           WHERE metric = 'gpu_power' AND hour >= ? AND hour <= ?""",
        ((from_s // HOUR_S) * HOUR_S, to_s),
    )
    hourly_avg: dict[int, float] = {
        r["hour"]: float(r["avg"]) for r in hourly_rows if r["avg"] is not None
    }

    fnames = await db.execute_fetchall(
        """SELECT DISTINCT metric FROM metric_samples
           WHERE (metric IN (?, ?) OR metric LIKE ?) AND ts >= ? AND ts <= ?""",
        (*TOKEN_COUNTERS, FINISH_REASON_PREFIX + "%", from_s, to_s),
    )
    names = [r["metric"] for r in fnames]
    counter_by_hour: dict[int, dict[str, list[tuple[int, float]]]] = defaultdict(dict)
    if names:
        # С запасом 1 ч назад — для базового значения счётчика на старте часа.
        ph = ",".join("?" * len(names))
        crows = await db.execute_fetchall(
            f"""SELECT metric, ts, value FROM metric_samples
                WHERE metric IN ({ph}) AND ts >= ? AND ts <= ?
                ORDER BY metric, ts""",
            [*names, from_s - HOUR_S, to_s],
        )
        for r in crows:
            h = (r["ts"] // HOUR_S) * HOUR_S
            counter_by_hour[h].setdefault(r["metric"], []).append(
                (r["ts"], float(r["value"]))
            )

    tokens_rows = await db.execute_fetchall(
        "SELECT ts, prompt_tokens, completion_tokens, requests_finished "
        "FROM tokens WHERE ts >= ? AND ts <= ?",
        ((from_s // HOUR_S) * HOUR_S, to_s),
    )
    tokens_by_hour: dict[int, tuple[int, int, int]] = {
        r["ts"]: (int(r["prompt_tokens"] or 0), int(r["completion_tokens"] or 0),
                  int(r["requests_finished"] or 0))
        for r in tokens_rows
    }

    # ------------------------------------------------------------- итерация по часам
    cur = {
        "currency": (versions[-1] if versions else version)["currency"],
        "total": 0.0,
        "tokens_cost": 0.0,
        "elec_cost": 0.0,
        "kwh": 0.0,
        "avg_power_w": None,
        "per_1k_out_tok": None,
        "per_request": None,
        "requests": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "by_day": [],
        "cumulative": [],
        "power_by_day": [],
    }

    days: dict[int, dict] = {}
    cum = 0.0
    energy_ws = 0.0
    covered_s = 0

    def _window(buckets: dict[int, list], hour: int) -> list:
        """Точки [eff_from, eff_to]: свой бакет + граничные точки следующего."""
        out = [p for p in buckets.get(hour, ()) if p[0] >= eff_from]
        out += [p for p in buckets.get(hour + HOUR_S, ()) if p[0] <= eff_to]
        return out

    h = (from_s // HOUR_S) * HOUR_S
    while h < to_s:
        eff_from = max(from_s, h)
        eff_to = min(to_s, h + HOUR_S)
        rate = rate_for_ts(versions, h) if versions else version
        day_of_hour = (h // DAY_S) * DAY_S
        dd = days.setdefault(
            day_of_hour,
            {"day": day_of_hour, "total": 0.0, "tokens": 0.0,
             "electricity": 0.0, "kwh": 0.0, "energy_ws": 0.0, "covered_s": 0},
        )
        hour_had_data = False

        # ------------------------------------------------------ электричество
        pts = _window(power_by_hour, h)
        if pts:
            gpu_ws, covered = _trapezoids(pts)
            base_ws = float(rate["system_baseline_watts"]) * covered
            energy = gpu_ws + base_ws
            if covered > 0:
                kwh = energy / W_S_PER_KWH
                elec = kwh * float(rate["rate_per_kwh_usd"])
                cur["elec_cost"] += elec
                cur["kwh"] += kwh
                dd["electricity"] += elec
                dd["kwh"] += kwh
                dd["energy_ws"] += energy
                dd["covered_s"] += covered
                energy_ws += energy
                covered_s += covered
                hour_had_data = True
        elif h in hourly_avg:
            span = eff_to - eff_from  # длительность часа (UTC)
            energy = (hourly_avg[h] + float(rate["system_baseline_watts"])) * span
            kwh = energy / W_S_PER_KWH
            elec = kwh * float(rate["rate_per_kwh_usd"])
            cur["elec_cost"] += elec
            cur["kwh"] += kwh
            dd["electricity"] += elec
            dd["kwh"] += kwh
            dd["energy_ws"] += energy
            dd["covered_s"] += span
            energy_ws += energy
            covered_s += span
            hour_had_data = True

        # ------------------------------------------------------------ токены
        raw_h = counter_by_hour.get(h, {})
        raw_n = counter_by_hour.get(h + HOUR_S, {})
        m_in_window = {
            m: [p for p in raw_h.get(m, ()) if p[0] >= eff_from]
            + [p for p in raw_n.get(m, ()) if p[0] <= eff_to]
            for m in set(raw_h) | set(raw_n)
        }
        if any(m_in_window.values()):
            p_delta = 0.0
            c_delta = 0.0
            for m in TOKEN_COUNTERS:
                samples = m_in_window.get(m)
                if not samples:
                    continue
                prev_rows = [p for p in raw_h.get(m, ()) if p[0] < eff_from]
                prev = prev_rows[-1][1] if prev_rows else None
                if m == "prompt_tokens_total":
                    p_delta = _positive_delta(prev, samples)
                else:
                    c_delta = _positive_delta(prev, samples)
            req_delta = 0.0
            for m in (m for m in m_in_window if m.startswith(FINISH_REASON_PREFIX)):
                req_delta += _positive_delta(None, m_in_window[m])
            tok_cost = (
                p_delta * float(rate["token_prompt_per_million_usd"])
                + c_delta * float(rate["token_completion_per_million_usd"])
            ) / 1_000_000
            cur["tokens_cost"] += tok_cost
            cur["prompt_tokens"] += int(p_delta)
            cur["completion_tokens"] += int(c_delta)
            cur["requests"] += int(req_delta)
            dd["tokens"] += tok_cost
            hour_had_data = True
        elif h in tokens_by_hour:
            p, c, req = tokens_by_hour[h]
            tok_cost = (
                p * float(rate["token_prompt_per_million_usd"])
                + c * float(rate["token_completion_per_million_usd"])
            ) / 1_000_000
            cur["tokens_cost"] += tok_cost
            cur["prompt_tokens"] += p
            cur["completion_tokens"] += c
            cur["requests"] += req
            dd["tokens"] += tok_cost
            hour_had_data = True

        if hour_had_data:
            dd["total"] = dd["tokens"] + dd["electricity"]
            cum += dd["total"]
            cur["total"] += dd["total"]
            cur["cumulative"].append([eff_to, round(cum, 6)])
        h += HOUR_S

    if covered_s > 0:
        cur["avg_power_w"] = round(energy_ws / covered_s, 1)
    cur["tokens_cost"] = round(cur["tokens_cost"], 6)
    cur["elec_cost"] = round(cur["elec_cost"], 6)
    cur["kwh"] = round(cur["kwh"], 6)
    cur["total"] = round(cur["total"], 6)
    if cur["completion_tokens"] > 0:
        cur["per_1k_out_tok"] = round(cur["total"] * 1000 / cur["completion_tokens"], 6)
    if cur["requests"] > 0:
        cur["per_request"] = round(cur["total"] / cur["requests"], 6)

    by_day: list[dict] = []
    for d in sorted(days):
        dd = days[d]
        if dd["total"] <= 0 and dd["kwh"] <= 0:
            continue
        by_day.append(
            {
                "day": d,
                "total": round(dd["total"], 6),
                "tokens": round(dd["tokens"], 6),
                "electricity": round(dd["electricity"], 6),
                "kwh": round(dd["kwh"], 6),
                "avg_power_w": (round(dd["energy_ws"] / dd["covered_s"], 1)
                                if dd["covered_s"] > 0 else None),
            }
        )
    cur["by_day"] = by_day
    cur["power_by_day"] = [
        {"day": dd["day"], "avg_power_w": dd["avg_power_w"]}
        for dd in by_day
        if dd["avg_power_w"] is not None
    ]
    return cur
