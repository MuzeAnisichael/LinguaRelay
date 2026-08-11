# LinguaRelay

Low-latency desktop translation captions for Windows, with an optional LLM
revision layer.

> Status: v0.1.0 is the first public Windows x64 alpha release. It includes
> real-time four-language ASR, all 12 translation routes, the tray/overlay app,
> optional asynchronous local/cloud LLM revision, and verified model setup.

[简体中文](README.zh-CN.md) · [Architecture](docs/ARCHITECTURE.md) ·
[Roadmap](docs/ROADMAP.zh-CN.md) · [v0.1.0 release](docs/releases/v0.1.0.md) ·
[Privacy](docs/PRIVACY.zh-CN.md)

## Install v0.1.0

Download the Windows x64 installer from [GitHub Releases](https://github.com/MuzeAnisichael/LinguaRelay/releases/tag/v0.1.0), verify `SHA256SUMS.txt`, and run it. v0.1.0 shows the upstream model licenses on first launch and SHA-256 verifies every file in the separately downloaded model pack.

The unreleased `main` branch also checks LocalAppData during installation. First launch discovers models beside the executable, in the working directory, at `LINGUA_RELAY_MODEL_DIR`, or at the last manually selected directory. Existing files are SHA-256 verified against the pinned manifest, so a download is needed only when no valid local copy is selected.

The first binaries are not Authenticode-signed, so Windows may show an unknown-publisher warning. See the release notes and threat model before proceeding.

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
- Real-time ASR: multilingual `faster-whisper` with explicit language selection
- Fast translation: pinned M2M100/CTranslate2 direct routes for all 12 pairs
- LLM correction: disabled by default; local and HTTPS OpenAI-compatible
  asynchronous providers are available
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

## M2 real-time ASR

- one warmed, reusable multilingual `faster-whisper-small` model;
- explicit `zh`, `ja`, `en`, or `ko` on every request, with no automatic
  language-detection fallback;
- 320 ms overlapping updates, online energy endpointing, Silero VAD on final
  segments, and stable/unstable partial text; after six seconds a short pause
  ends the caption, while ten seconds is the hard caption limit;
- bounded inference and event queues that replace stale partials while
  preserving final results;
- CPU/CUDA diagnostics, file transcription, live WASAPI transcription, and a
  reproducible CC-BY-4.0 FLEURS benchmark.

## M3 instant translation and desktop UI

- one warmed M2M100 418M CTranslate2 model, pinned to an MIT-licensed revision;
- direct translation for every ordered pair among `zh`, `ja`, `en`, and `ko`;
- bounded MT queues, stale-partial replacement, final preservation, and a
  source-text fallback when translation fails;
- translated-only and bilingual overlay modes, partial fading, whole-window
  dragging, edge/corner resizing with persisted geometry, configurable
  opacity/fonts/click-through, and a global show/hide shortcut;
- tray controls for pause/resume, manual languages, audio device, display mode,
  local history, CSV/JSONL/SRT export, and exit;
- a PyInstaller onedir build, separate model pack, Inno Setup definition, and
  tag/manual GitHub packaging workflow for the first release.

## M4 asynchronous LLM revision

- `off`, completed-sentence `asynchronous`, and experimental partial+final
  `live` modes, selectable from the tray and disabled by default;
- a loopback-only local OpenAI-compatible provider and an HTTPS-only cloud
  OpenAI-compatible provider, with API keys read only from an environment
  variable;
- fixed source/target languages in every correction prompt, recent context, a
  route-filtered JSON glossary, bounded queues, timeouts, rate limiting, and a
  circuit breaker;
- fast captions are emitted before correction submission and survive provider
  timeout, disconnect, rate limiting, or an open circuit;
- each changed result is an append-only `revised` event carrying the parent
  revision, original fast translation, model/provider, and local/cloud scope;
- offline history correction writes to a separate JSONL file and retains all
  original events.

## Quick start

Python 3.11 is recommended.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev,audio,asr,translation]"
# NVIDIA Windows machines additionally need the CUDA 12 runtime DLL wheels:
python -m pip install -e ".[gpu]"
lingua-relay doctor
lingua-relay asr-doctor --load
lingua-relay languages
lingua-relay audio-devices
lingua-relay audio-monitor --seconds 10
lingua-relay mt-prepare
lingua-relay mt-doctor --load
lingua-relay app
```

### Configure optional M4 correction

For a local OpenAI-compatible server such as llama.cpp, copy the example
configuration and set:

```toml
[correction]
mode = "asynchronous"
provider = "local"
endpoint = "http://127.0.0.1:8080/v1"
model = "your-local-model"
```

`local` endpoints are restricted to the loopback interface. For a remote
OpenAI-compatible API, use `provider = "openai_compatible"`, an `https://`
endpoint, and put the key in the configured environment variable:

```powershell
$env:LINGUA_RELAY_API_KEY = "..."
lingua-relay correction-doctor --probe
```

Do not write the key into TOML. The tray and overlay explicitly distinguish
local processing from cloud transmission. Useful M4 commands are:

```powershell
lingua-relay correction-revise "source" "fast translation" --source en --target zh
lingua-relay history-revise data/history.jsonl data/history-revised.jsonl
lingua-relay correction-benchmark --report data/m4-fault-gates.json
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
settings. `asr-doctor --load` downloads and warms the configured model.

The tray app provides both **translated-only** and **bilingual** display modes.
Source and target languages remain manual; automatic detection is intentionally
disabled. `mt-prepare` downloads a pinned source checkpoint and creates the
local CTranslate2 model used by all 12 routes.

Live recognition always requires a manual source language:

```powershell
lingua-relay asr-stream --language ja
lingua-relay asr-transcribe sample.wav --language ko
```

To reproduce the M2 host benchmark, install `.[benchmark]`, fetch the pinned
public fixtures, and run:

```powershell
python scripts/fetch_fleurs_samples.py --samples-per-language 5
lingua-relay asr-benchmark data/fleurs-m2/manifest.json `
  --device cuda --compute-type float16 `
  --sustain-audio-minutes 30 --report data/m2.json
```

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
python -m pip install -e ".[dev,audio,asr,translation]"
ruff check .
pytest
```

Build the CPU application directory with `scripts/build_windows.ps1`; add
`-Runtime cuda` for bundled NVIDIA runtime DLLs and `-Installer` when Inno Setup
6 is installed. See [release packaging](docs/RELEASE.md).

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
