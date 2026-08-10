# LinguaRelay

Low-latency desktop translation captions for Windows, with an optional LLM
revision layer.

> Status: M1 audio capture is implemented. Real-time ASR and translation are the
> next milestones; the repository is not production-ready yet.

[简体中文](README.zh-CN.md) · [Architecture](docs/ARCHITECTURE.md) ·
[Roadmap](docs/ROADMAP.zh-CN.md)

## Product goal

LinguaRelay runs quietly in the background, captures the selected Windows
speaker output, and displays translated speech in a small always-on-top overlay.
The real-time path stays fast and deterministic. An optional local model or API
can revise completed captions without delaying the first translation.

The initial product scope is:

- Platform: Windows 10/11
- Audio: default or explicitly selected WASAPI loopback output
- Languages: Simplified Chinese (`zh`), Japanese (`ja`), English (`en`), and
  Korean (`ko`), selected manually
- Routes: all 12 source/target combinations among those four languages
- Automatic language detection: intentionally disabled
- Real-time ASR: planned `faster-whisper` multilingual benchmark in M2
- Fast translation: per-route model registry planned in M3
- LLM correction: disabled by default; asynchronous revision planned in M4
- Storage: local JSONL history; raw audio is not saved by default

## M1 audio capture

The current capture path provides:

- WASAPI loopback device discovery, a stable name-based selector, and a command
  that persists the selected device in `config.toml`;
- automatic following of the default output device, or reconnection to an
  explicitly selected device after interruption;
- callback-based 16-bit PCM capture, streaming stereo-to-mono conversion, and
  SoXR resampling to 16 kHz `float32`;
- fixed 320 ms chunks, monotonic timestamps, a bounded fresh-first queue, silence
  continuity, an RMS/peak meter, and drop/reconnect counters;
- quiet-tone loopback self-test and a sustained memory/continuity stress command.

## Quick start

Python 3.11 is recommended.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev,audio]"
lingua-relay doctor
lingua-relay languages
lingua-relay audio-devices
lingua-relay audio-monitor --seconds 10
```

To remember a non-default endpoint:

```powershell
lingua-relay audio-select "wasapi:Your device name"
```

The self-test plays a quiet one-second tone through the default output:

```powershell
lingua-relay audio-self-test
```

For the full M1 stability gate:

```powershell
lingua-relay audio-stress --minutes 30 --report data/m1-stress.json
```

The UI-only scaffold remains available with `lingua-relay demo`. Copy
`config.example.toml` to `config.toml` before changing languages or audio
settings. Model downloads are not part of M1.

## Why two translation passes?

```text
system audio -> ASR -> fast machine translation -> overlay
                                  |
                                  +-> optional LLM revision -> overlay/history
```

The fast path owns latency. The LLM path owns context, terminology, punctuation,
and retrospective cleanup. If a local model or API is slow or unavailable, live
captions keep working.

## Development

```powershell
python -m pip install -e ".[dev,audio]"
ruff check .
pytest
```

Install `.[runtime]` only when working on ASR/translation models.

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
model weights keep their own licenses; see [model choices](docs/MODELS.md) and
[third-party components](THIRD_PARTY.md).
