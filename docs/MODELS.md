# Model choices and licenses

Model weights are not bundled with LinguaRelay. The downloader must show the
selected model, source, version or revision, download size, and license before
installation.

## Baseline candidates

| Role | Candidate | Intended MVP use | License note |
|---|---|---|---|
| ASR | faster-whisper + Whisper `small` | Multilingual ASR with fixed `en` language and CPU INT8 | Verify both runtime and weight licenses at the selected revision |
| ASR alternative | whisper.cpp | Native packaging and additional hardware backends | Verify runtime and weight licenses separately |
| Fast MT | `Helsinki-NLP/opus-mt-en-zh` | English to Simplified Chinese baseline | Model card currently declares Apache-2.0 |
| Broad MT experiment | NLLB-200 distilled 600M | Research comparison only | CC-BY-NC-4.0; do not make it the distributable default |
| LLM revision | User-selected local model/API | Contextual correction after fast MT | Provider and model dependent |

References:

- faster-whisper: https://github.com/SYSTRAN/faster-whisper
- whisper.cpp: https://github.com/ggml-org/whisper.cpp
- OPUS-MT en-zh model card: https://huggingface.co/Helsinki-NLP/opus-mt-en-zh
- NLLB-200 distilled 600M model card: https://huggingface.co/facebook/nllb-200-distilled-600M

## Benchmark matrix

Do not pick the final default from model size or published benchmarks alone.
Measure on target hardware:

- CPU-only: `base`, `small` with INT8;
- NVIDIA GPU: `small`, `turbo` with FP16/INT8 where supported;
- chunk sizes: 320, 640, and 960 ms;
- quiet speech, music under speech, calls, video, and proper nouns;
- cold start, warm latency, P50/P95, peak memory, and sustained thermals.

The release manifest should pin exact model revisions and include license files.

