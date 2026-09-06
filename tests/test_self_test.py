from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from lingua_relay import self_test


def _verifier():
    path = Path(__file__).resolve().parents[1] / "scripts" / "verify_windows_bundle.py"
    spec = importlib.util.spec_from_file_location("bundle_self_test_verifier", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_self_test_isolates_data_restores_environment_and_reports_failure(monkeypatch, tmp_path):
    original = str(tmp_path / "real-user-data")
    monkeypatch.setenv("LOCALAPPDATA", original)
    observed = []

    def success(root):
        assert os.environ["LOCALAPPDATA"] == str(root / "local")
        assert os.environ["HF_HUB_OFFLINE"] == "1"
        observed.append(root)
        (root / "disposable.txt").write_text("temporary", encoding="utf-8")
        return {"value": 1}

    def failure(_root):
        raise RuntimeError("controlled failure")

    monkeypatch.setattr(self_test, "CHECKS", (("success", success), ("failure", failure)))
    report = tmp_path / "report.json"
    assert self_test.run_self_test(report) == 1
    assert os.environ["LOCALAPPDATA"] == original
    assert not Path(original).exists()
    assert not observed[0].exists()
    document = json.loads(report.read_text(encoding="utf-8"))
    assert document["status"] == "failed"
    assert document["checks"][0]["status"] == "passed"
    assert document["checks"][1]["error"] == "RuntimeError: controlled failure"


def test_verifier_requires_complete_frozen_report():
    verifier = _verifier()
    report = {
        "schema_version": 1,
        "frozen": True,
        "status": "passed",
        "checks": [{"name": name, "status": "passed"} for name in self_test.REQUIRED_CHECKS],
    }
    assert not verifier.validate_self_test_report(report)
    report["frozen"] = False
    assert verifier.validate_self_test_report(report)
    report["frozen"] = True
    report["checks"].pop()
    assert any("required checks" in issue for issue in verifier.validate_self_test_report(report))
    assert verifier.validate_self_test_report([])
    assert verifier.validate_self_test_report({"checks": ["invalid"]})


@pytest.mark.parametrize("returncode", [0, 1])
def test_executable_gate_checks_exit_code_and_uses_clean_environment(
    monkeypatch, tmp_path, returncode
):
    verifier = _verifier()
    monkeypatch.setattr(verifier.sys, "platform", "win32")
    monkeypatch.setattr(verifier.subprocess, "CREATE_NO_WINDOW", 0, raising=False)
    monkeypatch.setenv("PYTHONPATH", "unrelated-source")
    monkeypatch.setenv("QT_PLUGIN_PATH", "unrelated-plugins")
    monkeypatch.setenv("PATH", "unrelated-dlls")
    bundle = tmp_path / "bundle"
    bundle.mkdir()

    def run(command, **kwargs):
        assert command[0] == str(bundle / "LinguaRelay.exe")
        assert command[1] == "--self-test"
        assert "PYTHONPATH" not in kwargs["env"]
        assert "QT_PLUGIN_PATH" not in kwargs["env"]
        assert "unrelated-dlls" not in kwargs["env"]["PATH"]
        Path(command[2]).write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "frozen": True,
                    "status": "passed",
                    "checks": [
                        {"name": name, "status": "passed"} for name in self_test.REQUIRED_CHECKS
                    ],
                }
            ),
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=returncode)

    monkeypatch.setattr(verifier.subprocess, "run", run)
    saved_report = tmp_path / "saved-report.json"
    if returncode:
        with pytest.raises(RuntimeError, match="exited with code 1"):
            verifier.run_executable_self_test(bundle, report_output=saved_report)
    else:
        assert verifier.run_executable_self_test(bundle, report_output=saved_report)
    assert saved_report.is_file()


def test_executable_gate_rejects_missing_report_and_timeout(monkeypatch, tmp_path):
    verifier = _verifier()
    monkeypatch.setattr(verifier.sys, "platform", "win32")
    monkeypatch.setattr(verifier.subprocess, "CREATE_NO_WINDOW", 0, raising=False)
    monkeypatch.setattr(
        verifier.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0)
    )
    with pytest.raises(RuntimeError, match="without a self-test report"):
        verifier.run_executable_self_test(tmp_path)

    def timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired("LinguaRelay.exe", 1)

    monkeypatch.setattr(verifier.subprocess, "run", timeout)
    with pytest.raises(RuntimeError, match="timed out"):
        verifier.run_executable_self_test(tmp_path, timeout=1)


def test_launcher_self_test_precedes_app_import_and_runs_offline(tmp_path):
    root = Path(__file__).resolve().parents[1]
    report_path = tmp_path / "source-self-test.json"
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(root / "src")
    environment["LOCALAPPDATA"] = str(tmp_path / "untouched-user-data")
    if sys.platform != "win32":
        environment["QT_QPA_PLATFORM"] = "offscreen"
    result = subprocess.run(
        [sys.executable, str(root / "packaging" / "launcher.py"), "--self-test", str(report_path)],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        timeout=60,
        check=False,
    )
    assert report_path.is_file(), result.stderr.decode(errors="replace")
    document = json.loads(report_path.read_text(encoding="utf-8"))
    assert result.returncode == 0, document
    assert document["status"] == "passed", document
    assert {check["name"] for check in document["checks"]} == set(self_test.REQUIRED_CHECKS)
    assert not Path(environment["LOCALAPPDATA"]).exists()
    assert document["checks"][-1]["details"]["audio_played"] is False
    assert document["checks"][-1]["details"]["windows_shown"] is False
