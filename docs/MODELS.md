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

## M2 ASR selection

The M2 host benchmark selected multilingual `small` with CUDA float16. The
built-in revision pins are:

| Model | Hugging Face repository | Revision |
|---|---|---|
| `small` (default) | `Systran/faster-whisper-small` | `536b0662742c02347bc0e980a01041f333bce120` |
| `base` (CPU comparison) | `Systran/faster-whisper-base` | `ebe41f70d5b6dfa9166e2c581c45c9c0cfc57b66` |

On the RTX 5070 Laptop GPU host, `small/CUDA float16` produced an aggregate
RTF of 0.024 and a first non-empty partial P50 of 0.79 seconds after warm-up.
The measured FLEURS rates were Chinese CER 14.9%, Japanese CER 15.6%, English
WER 7.7%, and Korean WER 33.8%. This 20-sample set is an engineering gate, not
a statistically sufficient release-quality claim. Korean WER is also sensitive
to spacing and numeral formatting.

`base/CPU int8` is a functional fallback, but its four-sample first-partial P50
was 1.35 seconds and therefore missed the M2 1.2-second target on this host.
Automatic runtime selection uses CUDA only when both a device and the required
cuBLAS 12/cuDNN 9 libraries are available; otherwise it selects CPU INT8.

## Baseline candidates

| Role | Candidate | Intended use | License note |
|---|---|---|---|
| ASR | faster-whisper + multilingual Whisper small | Fixed-language `zh/ja/en/ko` ASR | MIT runtime; Whisper weights under the model repository license |
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
- NVIDIA GPU: multilingual `base` and `small` with float16;
- M1 input chunks: 320 ms; partial submission interval: 320 ms;
- quiet speech, music under speech, calls, video, and proper nouns;
- cold start, warm latency, P50/P95, peak memory, and sustained thermals.

The release manifest must pin exact model revisions and include license files.
The M2 fixture downloader pins FLEURS revision
`70bb2e84b976b7e960aa89f1c648e09c59f894dd`.
