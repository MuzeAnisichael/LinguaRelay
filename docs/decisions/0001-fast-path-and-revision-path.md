# ADR 0001: Separate fast translation and LLM revision paths

- Status: accepted
- Date: 2026-08-11

## Context

Large language models can improve consistency and context handling, but local
models vary greatly by hardware and API latency is outside the application's
control. Blocking live captions on correction would make the main feature
unreliable.

## Decision

The ASR and fast machine-translation path publishes the first usable caption.
LLM correction consumes completed segments independently and publishes a
revision with the same segment identifier. The correction path is optional,
bounded, timed out, and protected by a circuit breaker.

## Consequences

- Users may briefly see a translation that is later updated.
- History needs immutable revisions rather than destructive replacement.
- The app remains useful when offline or when a provider fails.
- Latency and quality can be benchmarked independently.

