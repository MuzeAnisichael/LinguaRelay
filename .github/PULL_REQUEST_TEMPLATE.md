## Summary

<!-- What changes for users or contributors? Keep this outcome-focused. -->

## Why

<!-- Link the issue and explain the problem this solves. -->

Closes #

## Validation

<!-- List the exact checks, hardware, model profile, and language routes tested. -->

- [ ] `ruff check .`
- [ ] `ruff format --check .`
- [ ] `pytest`
- [ ] Relevant manual or benchmark checks are described below

## Impact review

- [ ] The fast caption path still works when LLM revision is disabled or unavailable.
- [ ] New queues, retries, or background work are bounded.
- [ ] No API keys, recordings, model weights, or generated caption history were committed.
- [ ] Privacy, model-license, packaging, and documentation changes were considered.
- [ ] User-visible text and behavior are documented in both README files or the release notes when applicable.

## Screenshots or measurements

<!-- Add sanitized UI screenshots, latency evidence, or before/after results when useful. -->
