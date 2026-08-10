from __future__ import annotations

import argparse
import importlib.util
import json
import platform
import sys
import time
from dataclasses import asdict, replace
from pathlib import Path

from lingua_relay import __version__
from lingua_relay.config import Settings
from lingua_relay.languages import SUPPORTED_LANGUAGES, translation_routes


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

    subparsers.add_parser("languages", help="list supported manual language routes")

    devices = subparsers.add_parser("audio-devices", help="list WASAPI loopback devices")
    devices.add_argument("--json", action="store_true", help="emit machine-readable JSON")

    select = subparsers.add_parser("audio-select", help="persist a WASAPI loopback selection")
    select.add_argument("device", help="device ID from audio-devices, or 'default'")
    select.add_argument("--config", type=Path, default=Path("config.toml"))

    monitor = subparsers.add_parser("audio-monitor", help="capture audio and show a level meter")
    monitor.add_argument("--config", type=Path, help="optional TOML configuration")
    monitor.add_argument("--seconds", type=float, default=10.0)

    self_test = subparsers.add_parser(
        "audio-self-test", help="play a quiet tone and verify loopback capture"
    )
    self_test.add_argument("--config", type=Path, help="optional TOML configuration")
    self_test.add_argument("--seconds", type=float, default=1.0)

    stress = subparsers.add_parser("audio-stress", help="run a sustained M1 capture check")
    stress.add_argument("--config", type=Path, help="optional TOML configuration")
    stress.add_argument("--minutes", type=float, default=30.0)
    stress.add_argument("--max-memory-growth-mib", type=float, default=64.0)
    stress.add_argument("--report", type=Path)

    asr_doctor = subparsers.add_parser("asr-doctor", help="inspect the M2 ASR runtime")
    asr_doctor.add_argument("--config", type=Path, help="optional TOML configuration")
    asr_doctor.add_argument("--model")
    asr_doctor.add_argument("--device", choices=("auto", "cpu", "cuda"))
    asr_doctor.add_argument("--compute-type")
    asr_doctor.add_argument("--load", action="store_true", help="download and load the model")

    transcribe = subparsers.add_parser("asr-transcribe", help="transcribe one audio file")
    transcribe.add_argument("audio", type=Path)
    transcribe.add_argument("--language", required=True, choices=tuple(SUPPORTED_LANGUAGES))
    transcribe.add_argument("--config", type=Path, help="optional TOML configuration")
    transcribe.add_argument("--model")
    transcribe.add_argument("--device", choices=("auto", "cpu", "cuda"))
    transcribe.add_argument("--compute-type")

    benchmark = subparsers.add_parser(
        "asr-benchmark", help="run the reproducible four-language M2 benchmark"
    )
    benchmark.add_argument("manifest", type=Path)
    benchmark.add_argument("--config", type=Path, help="optional TOML configuration")
    benchmark.add_argument("--model")
    benchmark.add_argument("--device", choices=("auto", "cpu", "cuda"))
    benchmark.add_argument("--compute-type")
    benchmark.add_argument("--limit-per-language", type=int)
    benchmark.add_argument("--sustain-audio-minutes", type=float, default=0)
    benchmark.add_argument("--report", type=Path, required=True)

    asr_stream = subparsers.add_parser(
        "asr-stream", help="stream system audio to partial/final transcript JSON"
    )
    asr_stream.add_argument("--config", type=Path, help="optional TOML configuration")
    asr_stream.add_argument("--language", choices=tuple(SUPPORTED_LANGUAGES))
    asr_stream.add_argument("--model")
    asr_stream.add_argument("--device", choices=("auto", "cpu", "cuda"))
    asr_stream.add_argument("--compute-type")
    asr_stream.add_argument("--seconds", type=float, default=0)
    return parser


def main(argv: list[str] | None = None) -> int:
    _configure_stdio()
    args = build_parser().parse_args(argv)
    if args.command == "doctor":
        return run_doctor(args.config)
    if args.command == "demo":
        settings = Settings.load(args.config)
        from lingua_relay.ui.overlay import run_demo

        return run_demo(settings)
    if args.command == "languages":
        for code, language in SUPPORTED_LANGUAGES.items():
            print(f"{code}: {language.native_name} / {language.english_name}")
        print(f"routes: {len(translation_routes())}")
        return 0
    if args.command == "audio-devices":
        from dataclasses import asdict

        from lingua_relay.audio import WasapiDeviceManager

        devices = WasapiDeviceManager().list_devices()
        if args.json:
            print(json.dumps([asdict(device) for device in devices], ensure_ascii=False, indent=2))
        else:
            for device in devices:
                marker = "*" if device.is_default else " "
                print(
                    f"{marker} {device.device_id} | {device.sample_rate} Hz | "
                    f"{device.channels} ch | index:{device.index}"
                )
        return 0
    if args.command == "audio-select":
        from lingua_relay.audio import WasapiDeviceManager
        from lingua_relay.settings_io import persist_audio_device

        device = WasapiDeviceManager().resolve(args.device)
        selector = "default" if args.device.strip().casefold() == "default" else device.device_id
        path = persist_audio_device(selector, args.config)
        print(f"saved {selector} to {path}")
        return 0
    if args.command == "audio-monitor":
        from lingua_relay.audio.diagnostics import monitor_audio

        return monitor_audio(Settings.load(args.config).audio, args.seconds)
    if args.command == "audio-self-test":
        from lingua_relay.audio.diagnostics import loopback_signal_test

        result = loopback_signal_test(
            Settings.load(args.config).audio,
            duration_seconds=args.seconds,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["passed"] else 1
    if args.command == "audio-stress":
        from lingua_relay.audio.diagnostics import stress_audio

        report = stress_audio(
            Settings.load(args.config).audio,
            seconds=args.minutes * 60,
            max_memory_growth_mib=args.max_memory_growth_mib,
            report_path=args.report,
        )
        print(json.dumps(asdict(report), ensure_ascii=False, indent=2))
        return 0 if report.passed else 1
    if args.command == "asr-doctor":
        return run_asr_doctor(args)
    if args.command == "asr-transcribe":
        return run_asr_transcribe(args)
    if args.command == "asr-benchmark":
        return run_asr_benchmark(args)
    if args.command == "asr-stream":
        return run_asr_stream(args)
    return 2


def _configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def run_doctor(config_path: Path | None) -> int:
    print(f"LinguaRelay {__version__}")
    print(f"OS: {platform.platform()}")
    print(f"Python: {platform.python_version()}")
    print(f"Windows target: {'ok' if sys.platform == 'win32' else 'unsupported'}")

    modules = {
        "PySide6": "overlay UI",
        "pyaudiowpatch": "WASAPI loopback capture",
        "soxr": "streaming sample-rate conversion",
        "faster_whisper": "speech recognition",
        "transformers": "candidate translation runtime",
        "sentencepiece": "candidate translation tokenizer",
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


def run_asr_doctor(args: argparse.Namespace) -> int:
    from lingua_relay.asr import FasterWhisperRecognizer, resolve_runtime

    settings = Settings.load(args.config)
    asr_settings = _override_asr(settings, args)
    runtime = resolve_runtime(asr_settings.device, asr_settings.compute_type)
    result: dict[str, object] = {
        "model": asr_settings.model,
        "runtime": asdict(runtime),
        "loaded": False,
    }
    if args.load:
        recognizer = FasterWhisperRecognizer(asr_settings, download_root="models")
        recognizer.load()
        result["model_revision"] = recognizer.revision
        result["loaded"] = True
        result["load_ms"] = recognizer.load_ms
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def run_asr_transcribe(args: argparse.Namespace) -> int:
    import numpy as np
    from faster_whisper.audio import decode_audio

    from lingua_relay.asr import FasterWhisperRecognizer

    settings = Settings.load(args.config)
    recognizer = FasterWhisperRecognizer(_override_asr(settings, args), download_root="models")
    audio = np.asarray(decode_audio(str(args.audio), sampling_rate=16_000), dtype=np.float32)
    result = recognizer.transcribe(audio, language=args.language)
    print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
    return 0


def run_asr_benchmark(args: argparse.Namespace) -> int:
    from lingua_relay.asr.benchmark import run_benchmark, write_report

    settings = Settings.load(args.config)
    report = run_benchmark(
        _override_asr(settings, args),
        args.manifest,
        limit_per_language=args.limit_per_language,
        sustain_audio_minutes=args.sustain_audio_minutes,
        download_root=Path("models"),
    )
    write_report(report, args.report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def run_asr_stream(args: argparse.Namespace) -> int:
    import queue

    from lingua_relay.asr import FasterWhisperRecognizer, StreamingAsrEngine
    from lingua_relay.audio import WasapiLoopbackCapture

    settings = Settings.load(args.config)
    language = args.language or settings.app.source_language
    recognizer = FasterWhisperRecognizer(_override_asr(settings, args), download_root="models")
    print("Loading ASR model...", file=sys.stderr)
    recognizer.load()
    engine = StreamingAsrEngine(recognizer, _override_asr(settings, args))
    capture = WasapiLoopbackCapture(settings.audio)
    deadline = None if args.seconds <= 0 else time.monotonic() + args.seconds
    engine.start()
    capture.start()
    if not capture.wait_until_running(10):
        capture.stop()
        engine.stop()
        raise RuntimeError(f"audio capture did not start: {capture.snapshot().last_error}")
    print(f"Streaming {language}; press Ctrl+C to stop.", file=sys.stderr)
    try:
        while deadline is None or time.monotonic() < deadline:
            try:
                chunk = capture.get_chunk(timeout=0.1)
            except queue.Empty:
                pass
            else:
                engine.submit_chunk(chunk, language=language)
            _print_ready_events(engine)
    except KeyboardInterrupt:
        pass
    finally:
        capture.stop()
        engine.stop()
        _print_ready_events(engine)
    print(json.dumps(asdict(engine.snapshot()), ensure_ascii=False), file=sys.stderr)
    return 0 if engine.snapshot().inference_errors == 0 else 1


def _print_ready_events(engine: object) -> None:
    import queue

    while True:
        try:
            event = engine.get_event(timeout=0)  # type: ignore[attr-defined]
        except queue.Empty:
            return
        print(json.dumps(event.to_dict(), ensure_ascii=False), flush=True)


def _override_asr(settings: Settings, args: argparse.Namespace):
    overrides = {
        name: getattr(args, name)
        for name in ("model", "device", "compute_type")
        if hasattr(args, name) and getattr(args, name) is not None
    }
    return replace(settings.asr, **overrides)


if __name__ == "__main__":
    raise SystemExit(main())
