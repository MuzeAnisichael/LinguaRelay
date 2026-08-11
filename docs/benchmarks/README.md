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
PCM samples. M1 reports contain no text; M2 reports contain only public FLEURS
reference text and ASR hypotheses needed to audit WER/CER.

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

## M2 four-language ASR validation

Date: 2026-08-11 (Asia/Shanghai)

Host additions:

- GPU: NVIDIA GeForce RTX 5070 Laptop GPU, 8 GiB VRAM;
- faster-whisper: `1.2.1`; CTranslate2: `4.8.1`;
- selected model: multilingual `small`, revision
  `536b0662742c02347bc0e980a01041f333bce120`;
- selected runtime: CUDA float16 with cuBLAS 12 and cuDNN 9;
- model load plus CUDA warm-up: about 20 seconds;
- ASR inference queue: capacity 4 with one replaceable partial slot;
- ASR event queue: capacity 16, replace partial before applying final backpressure.

The reproducible test set is the first five test-split samples for each of
`cmn_hans_cn`, `ja_jp`, `en_us`, and `ko_kr` from Google FLEURS revision
`70bb2e84b976b7e960aa89f1c648e09c59f894dd` (CC-BY-4.0). Audio files remain in
ignored `data/fleurs-m2`; `scripts/fetch_fleurs_samples.py` recreates them.

Final quality and latency results from `m2-small-cuda-final.json`:

| Language | Metric | Error rate | First non-empty partial P50 | P95 | RTF |
|---|---:|---:|---:|---:|---:|
| Chinese | CER | 14.87% | 0.71 s | 0.99 s | 0.025 |
| Japanese | CER | 15.60% | 0.72 s | 2.24 s | 0.025 |
| English | WER | 7.69% | 0.91 s | 1.03 s | 0.023 |
| Korean | WER | 33.80% | 1.03 s | 1.04 s | 0.023 |

The aggregate first-partial P50 was 0.79 seconds, aggregate RTF was 0.024, and
the measured resident set after the quality run was about 936 MiB. Each
language then processed at least 30 minutes of repeated fixture audio: 674
inferences, zero inference errors, 214.4 seconds wall time, and 5.84 MiB RSS
growth during the sustained phase. Result: pass.

The CPU/NVIDIA candidate smoke reports are intentionally small and are retained
for selection traceability. `base/CUDA float16` was fastest but less accurate on
Japanese/Korean; `small/CPU int8` missed the latency target; `base/CPU int8` was
the most practical CPU fallback but its four-sample first-partial P50 was 1.35
seconds. A 15-second live WASAPI smoke processed 46 revisions, replaced 17 stale
partials, dropped four completed stale results, emitted a final event, and
reported no inference error; its metrics-only record is
`m2-wasapi-stream-smoke.json`.

## M3 twelve-route translation validation

Date: 2026-08-11 (Asia/Shanghai)

`m3-parallel-corpus.json` is an eight-sentence, project-authored CC0 smoke corpus
with aligned Chinese, Japanese, English, and Korean text. It exists to verify
route coverage, latency, deterministic report generation, and gross quality
regressions; it is not a release-quality translation evaluation set.

`m3-m2m100-cuda-final.json` records all 12 direct routes using M2M100 418M at
revision `55c2e61bbf05dfb8d7abccdc3fae6fc8512fd636` with CTranslate2 CUDA
float16. Every route passed the 1.8-second P50 gate. Per-route P50 was 59–89 ms;
aggregate P50 was 79 ms and aggregate P95 was 104 ms after warm-up.
