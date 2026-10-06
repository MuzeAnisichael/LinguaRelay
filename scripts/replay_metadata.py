"""Payload-free source identity for replay reports, independent of Git staging."""

from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path

from lingua_relay import __version__


def source_metadata() -> dict:
    root = Path(__file__).resolve().parents[1]
    files = sorted((root / "src").rglob("*.py")) + [
        root / "scripts" / name
        for name in (
            "replay_metadata.py",
            "run_reliability_replay.py",
            "run_local_pipeline_replay.py",
        )
    ]
    digest = hashlib.sha256()
    for path in files:
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    revision = None
    dirty = None
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        ).stdout.strip()
        if re.fullmatch(r"[0-9a-f]{40}", result):
            revision = result
        dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=root,
                capture_output=True,
                text=True,
                check=True,
                timeout=5,
            ).stdout.strip()
        )
    except (OSError, subprocess.SubprocessError):
        pass
    return {
        "version": __version__,
        "base_revision": revision,
        "worktree_dirty": dirty,
        "implementation_sha256": digest.hexdigest(),
        "implementation_files": len(files),
        "fingerprint_scope": "src/**/*.py and the three replay scripts; excludes docs/tests/media",
    }
