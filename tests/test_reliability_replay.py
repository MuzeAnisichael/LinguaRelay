from __future__ import annotations

import importlib.util
import json
import struct
import sys
import wave
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def replay(monkeypatch):
    path = Path(__file__).resolve().parents[1] / "scripts/run_reliability_replay.py"
    monkeypatch.syspath_prepend(str(path.parent))
    spec = importlib.util.spec_from_file_location("reliability_replay", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_replay_uses_real_workers_without_device_model_or_api_access(replay, monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("synthetic replay must not access capture/model/cloud services")

    monkeypatch.setattr("lingua_relay.audio.runtime.create_audio_capture", forbidden)
    monkeypatch.setattr("lingua_relay.service.FasterWhisperRecognizer", forbidden)
    monkeypatch.setattr("lingua_relay.service.M2M100Translator", forbidden)
    monkeypatch.setattr("lingua_relay.service.OpenAICompatibleProvider", forbidden)
    monkeypatch.setattr("lingua_relay.config.Settings.load", forbidden)
    report = replay.run_replay(segments=2, chunk_ms=20)
    assert report["gates"]["functional"]["status"] == "pass", report
    assert report["gates"]["performance"]["status"] == "not_evaluated"
    assert report["gates"]["quality"]["status"] == "not_evaluated"
    assert report["results"]["final_segments"] == 2
    assert report["trace"]["outcomes"]["asr_completed"] > 0
    assert report["trace"]["outcomes"]["mt_completed"] > 0
    assert report["trace"]["outcomes"]["service_adopted"] > 0
    assert report["trace"]["outcomes"]["ui_updated"] == 0
    assert "Synthetic source phrase" not in json.dumps(report)
    assert "Synthetic translated phrase" not in json.dumps(report)
    assert len(report["source"]["implementation_sha256"]) == 64
    assert report["source"]["implementation_files"] > 1
    assert "excludes docs/tests/media" in report["source"]["fingerprint_scope"]


def test_qt_replay_acknowledges_widget_updates_without_claiming_visible_paint(replay):
    report = replay.run_replay(segments=1, chunk_ms=20, qt_ui=True, source="ja", target="ko")
    assert report["gates"]["functional"]["status"] == "pass", report
    assert report["trace"]["outcomes"]["ui_updated"] > 0
    assert report["trace"]["outcomes"]["transcript_ui_updated"] > 0
    assert report["configuration"]["source_language"] == "ja"
    assert report["gates"]["quality"]["status"] == "not_evaluated"


def test_replay_reports_missing_finals_and_does_not_hide_timeout(replay):
    report = replay.run_replay(segments=2, chunk_ms=20, timeout_seconds=0.001)
    assert report["gates"]["functional"]["status"] == "fail"
    assert report["results"]["missing_final_segments"] == 2
    assert report["trace"]["retained_traces"] == 0


def test_replay_fails_when_trace_window_eviction_prevents_complete_accounting(replay):
    report = replay.run_replay(segments=2, chunk_ms=20, trace_capacity=1)
    assert report["gates"]["functional"]["status"] == "fail"
    assert report["trace"]["evicted_trace_entries"] > 0


def test_replay_refuses_to_overwrite_a_report_before_executing(replay, monkeypatch, tmp_path):
    output = tmp_path / "existing.json"
    output.write_text("original evidence", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["replay", "--output", str(output)])
    monkeypatch.setattr(replay, "run_replay", lambda **_: pytest.fail("must not execute"))
    with pytest.raises(SystemExit):
        replay.main()
    assert output.read_text(encoding="utf-8") == "original evidence"


@pytest.mark.parametrize(
    "changes",
    [
        {"segments": 0},
        {"segments": 129},
        {"chunk_ms": 0},
        {"source": "en", "target": "en"},
        {"timeout_seconds": float("inf")},
    ],
)
def test_replay_rejects_invalid_configuration(replay, changes):
    with pytest.raises(ValueError):
        replay.run_replay(**changes)


@pytest.fixture
def local_replay(monkeypatch):
    path = Path(__file__).resolve().parents[1] / "scripts/run_local_pipeline_replay.py"
    monkeypatch.syspath_prepend(str(path.parent))
    spec = importlib.util.spec_from_file_location("local_pipeline_replay", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _manifest(tmp_path):
    samples = []
    for index, language in enumerate(("en", "zh", "ja", "ko")):
        audio = tmp_path / f"{language}.wav"
        with wave.open(str(audio), "wb") as stream:
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(16000)
            stream.writeframes(b"\x00\x00" * 320)
        samples.append(
            {
                "id": str(index),
                "language": language,
                "path": audio.name,
                "reference": "synthetic test reference",
            }
        )
    data = {
        "dataset": "google/fleurs",
        "license": "CC-BY-4.0",
        "revision": "fixture",
        "sampling_rate": 16000,
        "samples": samples,
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path, data


@pytest.mark.parametrize("value", [0.25, float("nan")])
def test_local_replay_decodes_float32_wavs_and_rejects_nonfinite_samples(
    local_replay, tmp_path, value
):
    import numpy as np

    pcm = struct.pack("<320f", *([value] * 320))
    header = b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVEfmt "
    header += struct.pack("<IHHIIHH", 16, 3, 1, 16000, 64000, 4, 32)
    header += b"data" + struct.pack("<I", len(pcm))
    path = tmp_path / "float.wav"
    path.write_bytes(header + pcm)
    if np.isfinite(value):
        decoded = local_replay.read_fixture_wav(path)
        assert decoded.dtype == np.float32
        assert len(decoded) == 320
        assert np.all(decoded == value)
    else:
        with pytest.raises(ValueError, match="invalid PCM"):
            local_replay.read_fixture_wav(path)


def test_local_replay_preflight_does_not_download_missing_models(
    local_replay, monkeypatch, tmp_path
):
    monkeypatch.setattr(
        local_replay,
        "make_local_recognizer",
        lambda *_: pytest.fail("preflight must run before model loading"),
    )
    with pytest.raises(FileNotFoundError):
        local_replay.run_local_replay(
            tmp_path / "manifest.json", tmp_path / "missing_asr", tmp_path / "missing_mt"
        )
    incomplete = tmp_path / "incomplete"
    incomplete.mkdir()
    with pytest.raises(ValueError, match="no download"):
        local_replay.check_model_directory(incomplete, local_replay.ASR_FILES)


def test_local_manifest_requires_licensed_four_language_bounded_wavs(local_replay, tmp_path):
    path, data = _manifest(tmp_path)
    attribution, fixtures = local_replay.load_fixtures(path)
    assert len(fixtures) == 4
    assert attribution["license"] == "CC-BY-4.0"
    assert "reference" not in json.dumps(attribution)
    data["samples"].pop()
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="four source languages"):
        local_replay.load_fixtures(path)
    data["license"] = "unknown"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="licensed"):
        local_replay.load_fixtures(path)


def test_local_whisper_factory_forces_local_only_and_never_retries_download(
    local_replay, monkeypatch, tmp_path
):
    from lingua_relay.config import AsrSettings

    calls = []

    def factory(model, **kwargs):
        calls.append((model, kwargs))
        raise RuntimeError("synthetic incomplete local model")

    monkeypatch.setattr("faster_whisper.WhisperModel", factory)
    monkeypatch.setattr(
        "lingua_relay.asr.faster_whisper.resolve_runtime",
        lambda *_: SimpleNamespace(device="cpu", compute_type="int8"),
    )
    settings = replace(AsrSettings(), model=str(tmp_path))
    with pytest.raises(RuntimeError, match="synthetic incomplete"):
        local_replay.make_local_recognizer(settings)
    assert len(calls) == 1
    assert calls[0][1]["local_files_only"] is True


def test_local_replay_also_preserves_existing_reports(local_replay, monkeypatch, tmp_path):
    output = tmp_path / "existing.json"
    output.write_text("original evidence", encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "replay",
            "--manifest",
            "missing.json",
            "--asr-directory",
            "missing",
            "--mt-directory",
            "missing",
            "--output",
            str(output),
        ],
    )
    monkeypatch.setattr(
        local_replay, "run_local_replay", lambda *_args, **_kwargs: pytest.fail("must not execute")
    )
    with pytest.raises(SystemExit):
        local_replay.main()
    assert output.read_text(encoding="utf-8") == "original evidence"
