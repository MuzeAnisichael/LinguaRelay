# Contributing

LinguaRelay is in an early design-and-benchmark phase. Small, testable changes
are preferred.

1. Open an issue before large architecture or dependency changes.
2. Create a focused branch and keep secrets, recordings, models, and generated
   history out of Git.
3. Install `.[dev,audio]`, then run `ruff check .`, `ruff format --check .`,
   and `pytest` before opening a pull request.
4. Include measured latency and hardware details for performance claims.

Bug reports involving audio should state the Windows version, output device,
sample rate, CPU/GPU, model, and whether protected media was involved. Do not
attach recordings that contain private conversations without consent.

Changes to capture timing, queues, resampling, or device recovery should include
an `audio-self-test` result and a sustained `audio-stress` report. These reports
must contain metrics only, never captured PCM.
