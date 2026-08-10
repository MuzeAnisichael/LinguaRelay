# Model choices and licenses

Model weights are not bundled with LinguaRelay. The downloader must show the
selected model, source, exact revision, download size, and license before
installation.

## Language scope

The initial manually selected languages are:

| Code | Language | ASR code |
|---|---|---|
| `zh` | Simplified Chinese | `zh` |
| `ja` | Japanese | `ja` |
| `en` | English | `en` |
| `ko` | Korean | `ko` |

All 12 ordered source/target pairs must be supported. Automatic language
detection stays disabled. The internal translation configuration uses a route
registry rather than a single hard-coded English-to-Chinese model.

## Baseline candidates

| Role | Candidate | Intended use | License note |
|---|---|---|---|
| ASR | faster-whisper + multilingual Whisper | Fixed-language `zh/ja/en/ko` ASR | Verify runtime and weight licenses at the pinned revision |
| ASR alternative | whisper.cpp | Native packaging and additional hardware backends | Verify runtime and weight licenses separately |
| Pair-specific MT | OPUS-MT/Marian language-pair models | Low-latency routes that pass quality tests | License varies by checkpoint |
| Broad MT experiment | NLLB-200 distilled 600M | Research comparison and route coverage only | CC-BY-NC-4.0; not a distributable default |
| LLM revision | User-selected local model/API | Contextual correction after fast MT | Provider and model dependent |

References:

- faster-whisper: https://github.com/SYSTRAN/faster-whisper
- whisper.cpp: https://github.com/ggml-org/whisper.cpp
- OPUS model index: https://opus.nlpl.eu/opusapi/
- NLLB-200 distilled 600M: https://huggingface.co/facebook/nllb-200-distilled-600M

## Translation route selection

M3 must benchmark every ordered pair independently. A route is eligible only if
it records:

- model revision and license;
- cold-start and warm P50/P95 latency;
- peak memory on the target CPU/GPU profile;
- language-appropriate automatic quality metrics;
- terminology and human review scores;
- whether the route is direct, pivoted, or remote.

Direct local models are preferred. A pivot through another language must be
visible in diagnostics because it can compound errors. If no redistributable
local route meets the quality and latency gates, the provider registry may offer
an opt-in translation API instead of silently lowering quality.

## ASR benchmark matrix

- Languages: `zh`, `ja`, `en`, `ko`, always supplied explicitly;
- CPU-only: multilingual `base` and `small` with INT8;
- NVIDIA GPU: multilingual `small` and `turbo` with supported compute types;
- chunk sizes: 320, 640, and 960 ms;
- quiet speech, music under speech, calls, video, and proper nouns;
- cold start, warm latency, P50/P95, peak memory, and sustained thermals.

The release manifest must pin exact model revisions and include license files.

