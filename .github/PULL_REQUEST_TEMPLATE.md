## Summary

<!-- What changes for users or contributors? Keep this outcome-focused. -->

## Why

<!-- Link the issue and explain the problem this solves. -->

Closes #

## Requirements and scope

<!-- Reference R-... and applicable K-.../H-... IDs, or explain N/A.
Local ledger IDs are not GitHub issue numbers. New requirements should be
recorded before implementation; distinguish confirmed scope from proposals. -->

Requirement IDs:
Ledger IDs:
Confirmed scope / assumptions:
Not included:

## Validation

<!-- List actual checks with date, commit/worktree, hardware, model profile,
language routes and results. Explain skipped checks. Do not reuse old reports
as current results or model/API latency as audio-to-screen latency.
For docs-only changes, use link/anchor/ID/template checks instead of claiming
full application or installer validation. -->

<!-- Source checks apply to code/configuration changes; leave them unchecked
and state N/A with a reason for docs-only work. -->

- [ ] `ruff check .`
- [ ] `ruff format --check .`
- [ ] `pytest`
- [ ] Relevant manual or benchmark checks are described below
- [ ] Documentation links, IDs, referenced tests and templates were checked where relevant
- [ ] Checks not run and remaining evidence gaps are explicitly listed

## Impact review

- [ ] Changed behavior preserves fast captions with LLM disabled or unavailable (or N/A explained).
- [ ] Queue capacities, waiting/retry deadlines, shutdown and overload behavior were considered separately; unresolved risks remain open.
- [ ] No API keys, recordings, model weights, or generated caption history were committed.
- [ ] Privacy, model-license, packaging, and documentation changes were considered.
- [ ] User-visible text and behavior are documented in both README files or the release notes when applicable.
- [ ] Requirements, known issues, verification mapping and current handoff were updated (or N/A explained).
- [ ] No proposal, historical API budget, or old release request was treated as new authorization.

<!-- This checklist is a review mechanism, not an automatic CI requirement
coverage gate. Closing a ledger item needs its reproduction/regression and
acceptance evidence, not only passing source tests. -->

## Screenshots or measurements

<!-- Add sanitized UI screenshots, latency evidence, or before/after results when useful. -->
