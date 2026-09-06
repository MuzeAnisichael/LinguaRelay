from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from lingua_relay.correction.types import RevisionResult


@pytest.fixture
def benchmark():
    path = Path(__file__).resolve().parents[1] / "scripts" / "benchmark_openrouter.py"
    spec = importlib.util.spec_from_file_location("linguarelay_openrouter_benchmark", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _configure(monkeypatch, tmp_path, benchmark, *, provenance="project-authored-synthetic-CC0"):
    corpus = tmp_path / "corpus.json"
    corpus.write_text(
        json.dumps(
            {
                "provenance": provenance,
                "cases": [
                    {
                        "id": str(index),
                        "source": "Hello",
                        "fast": "你好",
                        "reference": "你好",
                        "category": "test",
                    }
                    for index in range(5)
                ],
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "report.json"
    arguments = [
        "benchmark_openrouter.py",
        "--corpus",
        str(corpus),
        "--output",
        str(output),
        "--allow-paid-api",
        "--budget-usd",
        "1",
    ]
    monkeypatch.setattr(sys, "argv", arguments)
    monkeypatch.setenv("OPENROUTER_API_KEY", "dummy-test-key-never-sent")
    calls = []

    class Provider:
        def __init__(self, settings, *, openrouter_price_cap):
            assert openrouter_price_cap == benchmark.PRICE_CAP
            self.model = settings.model

        def revise(self, request):
            # A reservation must exist on disk before the simulated paid call.
            saved = json.loads(output.read_text(encoding="utf-8"))
            assert saved["rows"][-1]["case_id"] == request.segment_id
            assert saved["reserved_upper_bound_usd"] > 0
            calls.append(request)
            return RevisionResult("你好", 1, "test", self.model, "cloud", usage={"cost": 0.01})

    monkeypatch.setattr(benchmark, "OpenAICompatibleProvider", Provider)
    return output, arguments, calls


def test_budget_reserves_each_attempt_before_call_and_stops_before_exceeding_limit(
    monkeypatch, tmp_path, benchmark
) -> None:
    output, _arguments, calls = _configure(monkeypatch, tmp_path, benchmark)
    monkeypatch.setattr(benchmark, "reservation_usd", lambda _request: 0.4)

    assert benchmark.main() == 0

    report = json.loads(output.read_text(encoding="utf-8"))
    assert len(calls) == 2
    assert report["reserved_upper_bound_usd"] == pytest.approx(0.8)
    assert sum(item["reported_cost_usd"] for item in report["summary"].values()) == 0.02


@pytest.mark.parametrize("budget", ["0", "-1", "1.01", "nan", "inf"])
def test_invalid_budget_fails_without_any_call(monkeypatch, tmp_path, benchmark, budget) -> None:
    output, arguments, calls = _configure(monkeypatch, tmp_path, benchmark)
    arguments[-1] = budget

    with pytest.raises(SystemExit) as error:
        benchmark.main()

    assert error.value.code == 2
    assert calls == []
    assert not output.exists()


def test_non_synthetic_corpus_is_rejected_before_any_call(monkeypatch, tmp_path, benchmark) -> None:
    output, _arguments, calls = _configure(
        monkeypatch, tmp_path, benchmark, provenance="user-history"
    )

    with pytest.raises(SystemExit) as error:
        benchmark.main()

    assert error.value.code == 2
    assert calls == []
    assert not output.exists()


def test_existing_report_is_never_overwritten(monkeypatch, tmp_path, benchmark) -> None:
    output, _arguments, calls = _configure(monkeypatch, tmp_path, benchmark)
    output.write_text("existing paid-run record", encoding="utf-8")

    with pytest.raises(SystemExit):
        benchmark.main()

    assert calls == []
    assert output.read_text(encoding="utf-8") == "existing paid-run record"


@pytest.mark.parametrize("outcome", ["error", "missing-usage"])
def test_failed_and_unknown_cost_attempts_keep_reservations_and_stop(
    monkeypatch, tmp_path, benchmark, outcome
) -> None:
    output, _arguments, calls = _configure(monkeypatch, tmp_path, benchmark)
    monkeypatch.setattr(benchmark, "reservation_usd", lambda _request: 0.1)

    class Provider:
        def __init__(self, settings, **_kwargs):
            self.model = settings.model

        def revise(self, request):
            calls.append(request)
            if outcome == "error":
                raise TimeoutError("sensitive provider response must not be serialized")
            return RevisionResult("你好", 1, "test", self.model, "cloud", usage=None)

    monkeypatch.setattr(benchmark, "OpenAICompatibleProvider", Provider)
    assert benchmark.main() == 0

    raw = output.read_text(encoding="utf-8")
    report = json.loads(raw)
    count = 3 if outcome == "error" else 1
    assert len(calls) == count
    assert report["reserved_upper_bound_usd"] == pytest.approx(count * 0.1)
    assert sum(item["unknown_cost_attempts"] for item in report["summary"].values()) == count
    assert sum(item["failures"] for item in report["summary"].values()) == (
        3 if outcome == "error" else 0
    )
    assert "sensitive provider response" not in raw


def test_summary_handles_interrupted_reservation_without_assuming_free_success(benchmark) -> None:
    model = benchmark.MODELS[0]
    result = benchmark.summary(
        [
            {"requested_model": model},
            {"requested_model": model, "elapsed_ms": 500, "error_type": "TimeoutError"},
            {
                "requested_model": model,
                "elapsed_ms": 100,
                "result": {"text": "你好", "usage": None},
            },
            {
                "requested_model": model,
                "elapsed_ms": 300,
                "result": {"text": "你好", "usage": {"cost": 0.03}},
            },
        ]
    )[model]

    assert result["attempts"] == 4
    assert result["successes"] == 2
    assert result["failures"] == 1
    assert result["pending_attempts"] == 1
    assert result["unknown_cost_attempts"] == 3
    assert result["reported_cost_usd"] == 0.03
    assert result["p95_complete_response_ms"] == 300
    assert result["first_request_ms"] is None


def test_insufficient_first_reservation_writes_zero_call_report(
    monkeypatch, tmp_path, benchmark
) -> None:
    output, _arguments, calls = _configure(monkeypatch, tmp_path, benchmark)
    monkeypatch.setattr(benchmark, "reservation_usd", lambda _request: 1.01)

    assert benchmark.main() == 0

    report = json.loads(output.read_text(encoding="utf-8"))
    assert calls == []
    assert report["reserved_upper_bound_usd"] == 0
    assert report["rows"] == []
