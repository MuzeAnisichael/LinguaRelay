# M1 host validation

Date: 2026-08-11 (Asia/Shanghai)

Environment reported by the test host:

- Windows kernel: `10.0.26200`
- Python: `3.11.7`
- PyAudioWPatch: `0.2.12.8`
- python-soxr: `1.1.0`
- Capture format: Realtek WASAPI loopback, 48 kHz, stereo, signed 16-bit PCM
- Output format: 16 kHz, mono, float32, 320 ms (5,120 samples)
- Output queue budget: 4 seconds, fresh-first
- Raw audio persistence: disabled

Signal checks:

| Selection | Tone | Peak | Signal chunks | Drops | Result |
|---|---:|---:|---:|---:|---|
| Default Realtek headphones | 523.25 Hz, 1.0 s, 4% | -30.94 dBFS | 3 | 0 | pass |
| Explicit Realtek speakers | 523.25 Hz, 0.25 s, 4% | -35.56 dBFS | 2 | 0 | pass |

The VB-Audio virtual cable endpoint opened and produced correctly formatted
silence, but did not loop the generated test tone back under the host's current
virtual-cable routing. This is recorded as a signal-test failure for that
endpoint, not as evidence of a capture crash.

Reports in this directory contain metrics and device names only. They contain no
PCM samples or translated text.

## Sustained result

The 30-minute host run is recorded in `m1-30min-windows.json`:

- elapsed: 1,800.016 seconds;
- chunks consumed: 5,623;
- sequence gaps and malformed chunks: 0;
- raw packet drops and output queue drops: 0;
- reconnects: 0;
- RSS: 33.93 MiB at start, 41.90 MiB at end, 42.36 MiB peak;
- RSS growth: 7.97 MiB, below the 64 MiB gate;
- Python heap growth: 131.38 KiB;
- result: pass.

The capture code gained an explicit timestamp-regression counter after the long
run started, so `m1-timestamp-smoke.json` supplements it with a 60-second run:
185 chunks, 0 sequence gaps, 0 timestamp regressions, 0 malformed chunks, 0
drops, and 0 reconnects. Result: pass.
