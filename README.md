# LinguaRelay

Low-latency desktop translation captions for Windows, with an optional LLM
revision layer.

> Status: architecture and runnable UI scaffold. Audio-to-translation wiring is
> the next milestone; the repository is not production-ready yet.

[简体中文](README.zh-CN.md) · [Architecture](docs/ARCHITECTURE.md) ·
[Roadmap](docs/ROADMAP.zh-CN.md)

## Product goal

LinguaRelay runs quietly in the background, captures the selected Windows
speaker output, and displays translated speech in a small always-on-top overlay.
The real-time path stays fast and deterministic. An optional local model or API
can revise completed captions without delaying the first translation.

The first supported route is deliberately narrow:

- Platform: Windows 10/11
- Audio source: default output device through WASAPI loopback
- Source language: English (selected manually)
- Target language: Simplified Chinese (selected manually)
- Real-time ASR: `faster-whisper` (`small`, INT8 on CPU by default)
- Fast translation: OPUS-MT English-to-Chinese
- LLM correction: disabled by default; asynchronous provider interface planned
- Storage: local JSONL history; raw audio is not saved by default

## Why two translation passes?

```text
system audio -> ASR -> fast machine translation -> overlay
                                  |
                                  +-> optional LLM revision -> overlay/history
```

The fast path owns latency. The LLM path owns context, terminology, punctuation,
and retrospective cleanup. If a local model or API is slow or unavailable, live
captions keep working.

## Quick start (UI demo)

Python 3.11 is recommended.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
lingua-relay doctor
lingua-relay demo
```

The demo only exercises the overlay; it does not capture audio or download
models. Copy `config.example.toml` to `config.toml` before experimenting with the
real pipeline.

## Repository layout

```text
src/lingua_relay/       application and domain code
tests/                  fast unit tests
docs/                   architecture, decisions, and roadmap
config.example.toml     safe local configuration template
```

## Development

```powershell
python -m pip install -e ".[dev]"
pytest
ruff check .
```

Runtime model and Windows audio dependencies will be installed through the
`runtime` extra once the capture/inference milestone lands:

```powershell
python -m pip install -e ".[runtime]"
```

## Privacy and security

- Loopback capture can include notifications, calls, and any other sound played
  through the selected output device.
- Audio is processed in memory and is not persisted by default.
- Caption history is local and can be disabled.
- Enabling an API correction provider will transmit caption text to that
  provider; the UI must show this state clearly.
- Never commit API keys. Use environment variables or the OS credential store.

## License

Application source is released under the [MIT License](LICENSE). Downloaded
model weights keep their own licenses; see [model choices](docs/MODELS.md).

