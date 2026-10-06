# Contributing to LinguaRelay

Thanks for helping make real-time translation more useful. Small, testable,
evidence-backed changes are easiest to review.

## Before starting

- Read the short [project rules](AGENTS.md) and [current handoff](docs/HANDOFF.zh-CN.md),
  then search existing issues, the [requirement/status baseline](docs/REQUIREMENTS.zh-CN.md),
  [known-issue ledger](docs/KNOWN-ISSUES.zh-CN.md), and [roadmap](docs/ROADMAP.zh-CN.md).
  Start Codex sessions at this repository root; parent-directory sessions must
  explicitly read this project's rules.
- Use a structured issue form for bugs, quality/performance reports, and feature
  proposals. Discuss large architecture or dependency changes before coding.
- For substantial or unclear work, agree on the user problem, scope, design,
  assumptions, and acceptance criteria first. Ask the most important question at
  each step; a proposal in the roadmap is not an implementation or release mandate.
- Never commit model weights, API keys, recordings, generated caption history,
  local configuration, or benchmark data containing sensitive device names.

## Development setup

Python 3.11 is recommended on Windows 10 or 11. The
[developer guide](docs/DEVELOPMENT.zh-CN.md) maps modules to targeted tests and
explains when a change actually requires a frozen build or installer regression.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev,runtime]"
lingua-relay doctor
```

For application-source or configuration/schema changes, run the standard checks
before opening a pull request:

```powershell
ruff check .
ruff format --check .
pytest
python -m pip check
```

For documentation-only changes, check relative links/anchors, requirement/issue
IDs, referenced test paths, template structure, and `git diff --check`; explain
why application tests or builds were not rerun. The
[verification map](docs/VERIFICATION.zh-CN.md) separates existing coverage,
historical runs, and outstanding acceptance evidence.

## Real-time and model changes

The local ASR/MT path owns first-result latency. Optional LLM work must remain
bounded and must not delay or disable fast captions when the provider is slow,
rate-limited, disconnected, or misconfigured.

Changes to capture timing, queues, resampling, device recovery, segmentation, or
model selection should include relevant reproducible evidence. State the Windows
version, CPU/GPU, compute type, model profile, language routes, test duration, and
latency or resource measurements. Performance claims should include before/after
conditions rather than a single best-case number.

Capture/stability reports must contain metrics only, not captured PCM or private
transcripts. Quality reports may include short, sanitized reference text and
recognition/translation examples from synthetic, publicly licensed, or explicitly
consented material; do not commit private recordings.
Distinguish audio-to-visible-caption latency from summed model timings or API
response time. A bounded queue capacity is not proof of bounded waiting; K-001
remains open. Historical quality gates and small LLM samples are not universal
accuracy claims. Paid API tests, model downloads, installation, pushes, and
releases must remain within the current task's authorization; old budgets or
release requests are not reusable permissions.

## Traceability and handoff

- Include affected `R-...` IDs in substantial changes, and `K-...`/`H-...` IDs
  for known risks or regressions; use `N/A` with a reason if none apply. New
  contributors may describe the problem without knowing an ID; maintainers map
  it during triage. Local ledger IDs are not GitHub issue numbers.
- Add new requirements/risks before implementation rather than replacing old
  requirements. Keep confirmed user needs, design proposals, static risks,
  reproductions, and measured results distinct.
- Record the date, commit/worktree, exact checks, conditions, results, and skipped
  checks. Close a ledger item only with reproduction/regression evidence and its
  stated acceptance criteria, not just a code change or green CI.
- Update the relevant requirements, ledger, verification map, and roadmap.
  Write significant design trade-offs in an ADR; preserve dated benchmark reports.
- Before completion or interruption, update the current handoff with the scope,
  completed work, unresolved items, next steps, and task-specific authorization.
  Do not add secrets, private content, or blanket future permissions.

This is a human-maintained review process; current CI does not automatically
enforce requirement coverage or guarantee the absence of context drift.

## Pull requests

- Keep the branch focused and explain the user-visible outcome.
- Add or update tests for changed behavior.
- Update both README languages or the release notes when user-facing behavior
  changes.
- Keep requirement status and boundaries current. Source version 0.3.3 is
  unreleased; successful CI or local artifacts do not change the public v0.3.2
  download until a separate release is published.
- Document new dependencies, model revisions, licenses, network transmission,
  persistent storage, and packaging impact.
- Include sanitized screenshots for UI changes and benchmark evidence for latency,
  stability, accuracy, or resource-use claims.

By participating, you agree to follow the [Code of Conduct](CODE_OF_CONDUCT.md).
