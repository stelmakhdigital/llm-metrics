"""Тесты парсера Prometheus text format."""

from app.collectors.prom_parser import parse_prometheus

SAMPLE = """\
# HELP vllm:num_requests_running Number of requests currently running.
# TYPE vllm:num_requests_running gauge
vllm:num_requests_running{engine="0",model_name="qwen3.8-27b-dflash2"} 2
vllm:num_requests_running{engine="1",model_name="qwen3.8-27b-dflash2"} 4
# HELP vllm:prompt_tokens_total Prompt tokens.
# TYPE vllm:prompt_tokens_total counter
vllm:prompt_tokens_total{engine="0"} 119159660
# HELP x_bucket Mock hist
# TYPE x histogram
x_bucket{le="0.5"} 10
x_bucket{le="1"} 25
x_bucket{le="+Inf"} 30
x_count 30
x_sum 17.5
# TYPE untyped_metric untyped
untyped_metric 42
# TYPE nan_metric gauge
nan_metric NaN
garbage line without value
# just a comment
"""


def test_gauge_multiple_series():
    m = parse_prometheus(SAMPLE)
    met = m["vllm:num_requests_running"]
    assert met.type == "gauge"
    assert [s.value for s in met.series] == [2.0, 4.0]
    assert met.series[0].labels == {
        "engine": "0",
        "model_name": "qwen3.8-27b-dflash2",
    }


def test_counter():
    m = parse_prometheus(SAMPLE)
    assert m["vllm:prompt_tokens_total"].type == "counter"
    assert m["vllm:prompt_tokens_total"].series[0].value == 119159660.0


def test_histogram_separate_names():
    m = parse_prometheus(SAMPLE)
    # TYPE относится к базовому имени; *_bucket/*_count/*_sum — подимена
    assert m["x"].type == "histogram"
    assert m["x_bucket"].type is None
    le = [s.labels["le"] for s in m["x_bucket"].series]
    assert le == ["0.5", "1", "+Inf"]
    assert m["x_count"].series[0].value == 30.0
    assert m["x_sum"].series[0].value == 17.5


def test_untyped_and_nan():
    m = parse_prometheus(SAMPLE)
    assert m["untyped_metric"].type == "untyped"
    assert m["untyped_metric"].series[0].value == 42.0
    assert m["nan_metric"].series[0].value is None  # NaN → None


def test_special_labels():
    text = (
        'vllm:cache_config_info{block_size="16",kv_offloading_size="None",'
        'kv_cache_dtype_skip_layers="[]"} 1.0\n'
    )
    m = parse_prometheus(text)
    labels = m["vllm:cache_config_info"].series[0].labels
    assert labels["block_size"] == "16"
    assert labels["kv_offloading_size"] == "None"
    assert labels["kv_cache_dtype_skip_layers"] == "[]"


def test_malformed_lines_skipped():
    # ничего не падает, валидные строки распарсились
    m = parse_prometheus(SAMPLE)
    assert "vllm:num_requests_running" in m
    assert "garbage" not in " ".join(m)
