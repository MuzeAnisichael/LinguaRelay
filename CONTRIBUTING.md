# Contributing to LinguaRelay

Thanks for helping make real-time translation more useful. Small, testable,
evidence-backed changes are easiest to review.

## Before starting

- Search existing issues and the [roadmap](docs/ROADMAP.zh-CN.md).
- Use a structured issue form for bugs, quality/performance reports, and feature
  proposals. Discuss large architecture or dependency changes before coding.
- Never commit model weights, API keys, recordings, generated caption history,
  local configuration, or benchmark data containing sensitive device names.

## Development setup

Python 3.11 is recommended on Windows 10 or 11:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev,audio,asr,translation]"
lingua-relay doctor
```

Run the standard checks before opening a pull request:

```powershell
ruff check .
ruff format --check .
pytest
python -m pip check
```

## Real-time and model changes

The local ASR/MT path owns first-result latency. Optional LLM work must remain
bounded and must not delay or disable fast captions when the provider is slow,
rate-limited, disconnected, or misconfigured.

Changes to capture timing, queues, resampling, device recovery, segmentation, or
model selection should include relevant reproducible evidence. State the Windows
version, CPU/GPU, compute type, model profile, language routes, test duration, and
latency or resource measurements. Performance claims should include before/after
conditions rather than a single best-case number.

Audio reports must contain metrics only, never captured PCM. Use synthetic,
publicly licensed, or explicitly consented text/audio for quality examples.

## Pull requests

- Keep the branch focused and explain the user-visible outcome.
- Add or update tests for changed behavior.
- Update both README languages or the release notes when user-facing behavior
  changes.
- Document new dependencies, model revisions, licenses, network transmission,
  persistent storage, and packaging impact.
- Include sanitized screenshots for UI changes and benchmark evidence for latency,
  stability, accuracy, or resource-use claims.

By participating, you agree to follow the [Code of Conduct](CODE_OF_CONDUCT.md).
