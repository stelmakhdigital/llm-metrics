"""F4.1: движок алертов, API журнала/настроек, health-сводка, multi-модель.

Детерминизм времени: time.time подменяется синтетическим часами (clock),
движок и seed-данные работают на одном «сейчас».
"""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from app.alerts.engine import AlertEngine
from app.alerts.rules import DEFAULT_RULES, Rule, set_alert_cfg
from app.collectors.base import SourceRegistry

NOW = int(time.time())

KV = "kv_cache_usage"


class Clock:
    def __init__(self, start: int = NOW):
        self.v = float(start)

    def __call__(self) -> float:
        return self.v

    def advance(self, s: float) -> None:
        self.v += s


@pytest.fixture
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr(time, "time", c)
    return c


class FakeHttp:
    def __init__(self):
        self.sent: list[tuple[str, dict]] = []

    async def post(self, url, json=None, timeout=None):
        self.sent.append((url, json))
        return SimpleNamespace(status_code=200)


def make_engine(db, statuses, http, **kw) -> AlertEngine:
    return AlertEngine(
        db,
        statuses,
        http,
        default_enabled=kw.pop("default_enabled", True),
        default_webhook=kw.pop("default_webhook", None),
        check_interval_s=kw.pop("check_interval_s", 30),
    )


async def insert_kv(db, values: list[tuple[int, float]]) -> None:
    await db.executemany(
        "INSERT INTO metric_samples (metric, ts, value, source, gpu, model) "
        "VALUES (?, ?, ?, 'vllm', NULL, 'm1')",
        [(KV, ts, v) for ts, v in values],
    )
    await db.commit()


def kv_rule() -> Rule:
    return next(r for r in DEFAULT_RULES if r.id == "kv_cache_high")


# ------------------------------------------------------------------- engine
async def test_condition_true_and_fresh(db, clock):
    st = SourceRegistry(("vllm", "gpu", "system"))
    eng = make_engine(db, st, FakeHttp())
    now = int(clock())
    await insert_kv(db, [(now - 350, 95.0), (now - 60, 96.0), (now - 10, 97.0)])
    cond, detail = await eng._condition(kv_rule(), now)
    assert cond is True
    assert detail == f"{KV}=97"


async def test_condition_single_spike_does_not_alert(db, clock):
    """issue #6: единичный всплеск (1 полл из окна for_s=300) не алертит;
    устойчивое нарушение (все поллы ≥ for_s) — алертит."""
    st = SourceRegistry(("vllm", "gpu", "system"))
    eng = make_engine(db, st, FakeHttp())
    now = int(clock())
    # 20 поллов по 15 с (окно 300 с), только последний — нарушение
    pts = [(now - 300 + 15 * i, 10.0) for i in range(19)] + [(now - 10, 97.0)]
    await insert_kv(db, pts)
    cond, _ = await eng._condition(kv_rule(), now)
    assert cond is False  # 1/20 < 50%

    # устойчивое: большинство поллов окна — нарушение (свежее включено)
    await insert_kv(db, [(now - 300 + 15 * i, 95.0) for i in range(1, 19)])
    cond, _ = await eng._condition(kv_rule(), now)
    assert cond is True  # 20/21 > 50% + свежее (now-10, 97)


async def test_condition_no_data_and_stale(db, clock):
    st = SourceRegistry(("vllm", "gpu", "system"))
    eng = make_engine(db, st, FakeHttp())
    now = int(clock())
    rule = kv_rule()
    # данных нет
    cond, _ = await eng._condition(rule, now)
    assert cond is False
    # данные есть, но несвежие (старше 180с)
    await insert_kv(db, [(now - 900, 99.0), (now - 600, 99.0)])
    cond, _ = await eng._condition(rule, now)
    assert cond is False


async def test_trigger_resolve_cooldown(db, clock):
    st = SourceRegistry(("vllm", "gpu", "system"))
    http = FakeHttp()
    eng = make_engine(db, st, http)
    now = int(clock())
    await insert_kv(db, [(now - 350, 95.0), (now - 30, 96.0)])

    await eng.check_once()
    assert eng.active_count() == 1
    rows = await db.execute_fetchall("SELECT * FROM alerts")
    assert len(rows) == 1
    assert rows[0]["status"] == "active"
    assert rows[0]["level"] == "warning"
    # webhook не задан — отправлений нет
    assert http.sent == []

    # восстановление: свежее низкое значение
    clock.advance(400)
    now2 = int(clock())
    await insert_kv(db, [(now2 - 300, 20.0), (now2 - 10, 20.0)])
    await eng.check_once()
    assert eng.active_count() == 0
    rows = await db.execute_fetchall("SELECT * FROM alerts ORDER BY id")
    assert rows[0]["status"] == "resolved"
    assert rows[0]["resolved_at"] is not None

    # cooldown (3600с): новое нарушение сразу после recovery не алертит
    clock.advance(400)
    now3 = int(clock())
    await insert_kv(db, [(now3 - 350, 95.0), (now3 - 10, 95.0)])
    await eng.check_once()
    assert eng.active_count() == 0
    assert len(await db.execute_fetchall("SELECT * FROM alerts")) == 1


async def test_retrigger_after_cooldown_zero(db, clock):
    st = SourceRegistry(("vllm", "gpu", "system"))
    eng = make_engine(db, st, FakeHttp())
    rule = Rule(
        id="kv_test",
        title="тест",
        level="critical",
        metric=KV,
        op=">",
        value=90,
        for_s=120,
        cooldown_s=0,
    )
    await set_alert_cfg(db, rules=[rule])
    now = int(clock())
    await insert_kv(db, [(now - 150, 95.0), (now - 10, 96.0)])
    await eng.check_once()
    assert eng.active_count() == 1

    clock.advance(200)
    now2 = int(clock())
    await insert_kv(db, [(now2 - 150, 20.0), (now2 - 10, 20.0)])
    await eng.check_once()
    assert eng.active_count() == 0

    clock.advance(200)
    now3 = int(clock())
    await insert_kv(db, [(now3 - 150, 95.0), (now3 - 10, 96.0)])
    await eng.check_once()
    assert eng.active_count() == 1


async def test_source_offline_rule_and_telegram(db, clock):
    st = SourceRegistry(("vllm", "gpu", "system"))
    st["vllm"].fail("connection refused")
    http = FakeHttp()
    eng = make_engine(db, st, http, default_webhook="https://example.test/hook")
    await eng.check_once()
    assert [a["rule"] for a in eng.active()] == ["src_vllm"]
    # уведомление ушло
    assert len(http.sent) == 1
    assert http.sent[0][0] == "https://example.test/hook"
    assert "vLLM оффлайн" in http.sent[0][1]["text"]

    # recovery
    st["vllm"].ok(int(clock()))
    await eng.check_once()
    assert eng.active_count() == 0
    assert any("восстановлено" in j["text"] for _, j in http.sent)


async def test_disabled_resolves_all(db, clock):
    st = SourceRegistry(("vllm", "gpu", "system"))
    st["vllm"].fail("boom")
    eng = make_engine(db, st, FakeHttp())
    await eng.check_once()
    assert eng.active_count() == 1
    await set_alert_cfg(db, enabled=False)
    await eng.check_once()
    assert eng.active_count() == 0
    rows = await db.execute_fetchall("SELECT status FROM alerts")
    assert all(r["status"] == "resolved" for r in rows)


async def test_restore_from_journal(db, clock):
    st = SourceRegistry(("vllm", "gpu", "system"))
    eng1 = make_engine(db, st, FakeHttp())
    st["gpu"].fail("nvml error")
    await eng1.check_once()
    assert eng1.active_count() == 1
    # «рестарт»: новый экземпляр восстанавливает активные из журнала
    eng2 = make_engine(db, st, FakeHttp())
    await eng2.restore()
    assert [a["rule"] for a in eng2.active()] == ["src_gpu"]


# --------------------------------------------------------------------- api
def test_alerts_api_list_and_settings(client, db_path):
    body = client.get("/api/alerts").json()
    assert body == {"active": [], "recent": []}

    got = client.get("/api/settings/alerts").json()
    assert got["enabled"] is True
    assert got["webhook_configured"] is False
    assert {r["id"] for r in got["rules"]} == {r.id for r in DEFAULT_RULES}

    r = client.put(
        "/api/settings/alerts",
        json={"enabled": False, "telegram_webhook": "  "},
    )
    assert r.status_code == 200
    got = client.get("/api/settings/alerts").json()
    assert got["enabled"] is False
    assert got["telegram_webhook"] == ""

    r = client.put("/api/settings/alerts", json={"reset_rules": True})
    assert r.status_code == 200
    got = client.get("/api/settings/alerts").json()
    assert [r_["id"] for r_ in got["rules"]] == [r_.id for r_ in DEFAULT_RULES]

    # валидация
    r = client.put(
        "/api/settings/alerts", json={"rules": [{"id": "x", "title": "t", "level": "nope"}]}
    )
    assert r.status_code == 422
    r = client.put(
        "/api/settings/alerts",
        json={"rules": [{"id": "x", "title": "t", "op": "~"}]},
    )
    assert r.status_code == 422


def test_alerts_test_endpoint_no_webhook(client):
    r = client.post("/api/alerts/test")
    assert r.status_code == 400
    assert "Webhook" in r.json()["detail"]


def test_health_summary(client):
    body = client.get("/api/health/summary").json()
    assert set(body) == {
        "service", "sources", "model", "gpus", "system", "logs", "alerts_active",
    }
    assert body["service"]["version"]
    assert body["service"]["counts"]["metric_samples"] == 0
    assert body["model"] is None
    assert body["gpus"] == []
    assert body["system"]["disks"] == []
    assert body["logs"] == {"errors_24h": 0, "critical_24h": 0, "warnings_24h": 0}
    assert body["alerts_active"] == 0
    assert set(body["sources"]) >= {"vllm", "gpu", "system", "last_sample_ts"}


# ------------------------------------------------------------- multi-model
def test_model_filter_api(client, db_path):
    from util import seed_samples

    base = NOW - 3600
    rows = []
    for i in range(4):
        ts = base + i * 60
        rows.append(("num_requests_running", ts, 1.0, "vllm", None, "model-a"))
        rows.append(("num_requests_running", ts, 9.0, "vllm", None, "model-b"))
    seed_samples(db_path, rows)
    to = base + 300

    all_body = client.get(
        f"/api/metrics/num_requests_running?from={base}&to={to}"
    ).json()
    assert all_body["count"] == 8

    for name, val in (("model-a", 1.0), ("model-b", 9.0)):
        body = client.get(
            f"/api/metrics/num_requests_running?from={base}&to={to}&model={name}"
        ).json()
        assert body["count"] == 4
        assert all(v == val for _, v in body["points"])

    # неизвестная модель — пусто
    body = client.get(
        f"/api/metrics/num_requests_running?from={base}&to={to}&model=zzz"
    ).json()
    assert body["count"] == 0 and body["points"] == []

    # список моделей
    models = client.get("/api/model/models").json()["models"]
    assert {m["name"] for m in models} == {"model-a", "model-b"}
    for m in models:
        assert m["from"] == base and m["to"] == base + 180 and m["count"] == 4

    # KPI с фильтром: только значения model-a
    body = client.get(
        f"/api/model?from={base}&to={to}&model=model-a"
    ).json()
    assert body["kpi"]["running"] == 1.0
    assert [m["name"] for m in body["models"]] == ["model-a"]


async def test_model_filter_kpi_values(db):
    from util import seed_samples_aio

    base = NOW - 3600
    rows = []
    for i in range(4):
        ts = base + i * 60
        rows.append(("kv_cache_usage", ts, 10.0 + i, "vllm", None, "ma"))
        rows.append(("kv_cache_usage", ts, 90.0, "vllm", None, "mb"))
    await seed_samples_aio(db, rows)
    to = base + 300

    from app.model_api import build_model_response

    # без фильтра «последнее» неоднозначно (одинаковые ts) — принимаем оба
    resp_all = await build_model_response(db, base, to)
    assert resp_all["kpi"]["kv_cache"] in (13.0, 90.0)
    resp_b = await build_model_response(db, base, to, model="mb")
    assert resp_b["kpi"]["kv_cache"] == 90.0
    assert [m["name"] for m in resp_b["models"]] == ["mb"]
    resp_a = await build_model_response(db, base, to, model="ma")
    assert resp_a["kpi"]["kv_cache"] == 13.0
