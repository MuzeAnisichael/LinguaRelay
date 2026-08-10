from __future__ import annotations

import argparse
import importlib.util
import platform
import sys
from pathlib import Path

from lingua_relay import __version__
from lingua_relay.config import Settings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lingua-relay",
        description="Low-latency desktop translation captions",
    )
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor = subparsers.add_parser("doctor", help="inspect the local runtime")
    doctor.add_argument("--config", type=Path, help="optional TOML configuration to validate")

    demo = subparsers.add_parser("demo", help="show the overlay with synthetic captions")
    demo.add_argument("--config", type=Path, help="optional TOML configuration")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "doctor":
        return run_doctor(args.config)
    if args.command == "demo":
        settings = Settings.load(args.config)
        from lingua_relay.ui.overlay import run_demo

        return run_demo(settings)
    return 2


def run_doctor(config_path: Path | None) -> int:
    print(f"LinguaRelay {__version__}")
    print(f"OS: {platform.platform()}")
    print(f"Python: {platform.python_version()}")
    print(f"Windows target: {'ok' if sys.platform == 'win32' else 'unsupported'}")

    modules = {
        "PySide6": "overlay UI",
        "pyaudiowpatch": "WASAPI loopback capture",
        "faster_whisper": "speech recognition",
        "transformers": "OPUS-MT translation",
        "sentencepiece": "OPUS-MT tokenizer",
    }
    for module, purpose in modules.items():
        installed = importlib.util.find_spec(module) is not None
        print(f"{module}: {'installed' if installed else 'missing'} ({purpose})")

    try:
        settings = Settings.load(config_path)
    except (OSError, ValueError) as error:
        print(f"Configuration: invalid ({error})")
        return 1

    print(
        "Configuration: valid "
        f"({settings.app.source_language} -> {settings.app.target_language}, "
        f"correction={settings.correction.mode})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
