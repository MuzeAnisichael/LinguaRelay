# ADR 0002: Four manually selected languages and routed translation

- Status: accepted
- Date: 2026-08-11

## Context

The initial scaffold fixed the first route to English-to-Simplified-Chinese.
The product requirement now includes Chinese, Japanese, English, and Korean in
both source and target roles while still excluding automatic detection.

## Decision

Use canonical language codes `zh`, `ja`, `en`, and `ko`, with aliases normalized
at configuration boundaries. Expose all 12 ordered source/target combinations.
Pass the selected source code directly to ASR. Resolve translation providers by
the `(source, target)` pair instead of keeping one global model name.

## Consequences

- M2 quality and latency must be verified independently for four ASR languages.
- M3 has 12 translation acceptance cases and may select different providers.
- Direct, pivoted, and remote routes must be visible rather than hidden.
- Automatic language detection remains out of scope and cannot silently run as
  a fallback.
