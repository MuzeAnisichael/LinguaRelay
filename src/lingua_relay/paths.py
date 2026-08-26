from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class AppPaths:
    """Writable and bundled paths that also work in a frozen Windows app."""

    data_dir: Path
    config_path: Path
    history_path: Path
    model_dir: Path
    projects_dir: Path
    resource_dir: Path

    @classmethod
    def discover(cls) -> AppPaths:
        if sys.platform == "win32":
            local_root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
            data_dir = local_root / "LinguaRelay"
        else:
            data_dir = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / (
                "lingua-relay"
            )
        resource_dir = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
        return cls(
            data_dir=data_dir,
            config_path=data_dir / "config.toml",
            history_path=data_dir / "history.jsonl",
            model_dir=data_dir / "models",
            projects_dir=data_dir / "projects",
            resource_dir=resource_dir,
        )


def resolve_user_path(path: Path, *, base: Path | None = None) -> Path:
    if path.is_absolute():
        return path
    return (base or Path.cwd()) / path
