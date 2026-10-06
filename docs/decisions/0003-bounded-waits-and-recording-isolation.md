# ADR 0003: Bounded waits, recording isolation and evidence boundaries

- Status: accepted for the 0.3.3 source reliability update, 2026-10-06.
- Requirements: R-LIVE-01, R-AUDIO-01, R-REC-01, R-UI-01, R-QUALITY-01.
- Issues: K-001, K-002, K-003, K-004 (counter semantics only).

## Context

A bounded queue can still wait forever. A controlled replay of the original
`af920a5` MT code reproduced final output and input queues being full together:
the worker waited for output space while the service-side producer waited for
input space. The same audio consumer wrote recordings and synchronously submitted
ASR, allowing a slow subtitle submission to delay the next recording block.
This is a deterministic logical reproduction, not a real-device incident.

## Decision

- Record on the capture router; submit realtime audio on a separate worker with
  a four-block handoff. Never wait on ASR admission from the recording router.
- Final engine admission is nonblocking by default. The service drains downstream
  first, in bounded batches, and retries finals in a bounded pending queue
  (translation request capacity, one-second deadline). Output waits at most one
  second. Partials remain replaceable; accepted finals are preserved in normal
  flow and cooperative shutdown.
- Sustained overload visibly pauses subtitles, invalidates old delivery, and
  cancels remaining subtitle work with separate counters. Explicit recording
  continues. Recovery is user-initiated and waits for old native calls before
  constructing fresh worker queues around the existing models.
- Shutdown uses one absolute deadline across audio, ASR, MT and optional LLM.
  Request stop first, drain outputs, then join. Timeout is not success: owners
  remain attached, release/restart is refused while calls are alive, and late
  results cannot update the overlay. No thread is forcibly killed.
- Measurements are bounded, in-memory, hashed segment/revision traces with no
  raw caption or audio payload. UI acknowledgement means widget update, not
  pixels painted. Source preview and translated text acknowledgements differ.
- New evidence reports have independent functional/performance/quality states.
  Empty, nonfinite, duplicate or mixed-configuration evidence is rejected.
  No approved threshold or human quality evidence means `not_evaluated`.

## Consequences and limits

Rejected admission attempts are not unique lost sentences. Queued cancellation,
output rejection, discarded final events and in-flight work are separate
quantities; in-flight cancellation is finalized when its native call returns.
`stale_results_dropped` counts completed work suppressed by abort, not all
outdated partial computation. Counters survive worker replacement.

The system does not save unrequested audio to repair overloaded subtitles.
This policy cannot recover audio that was never explicitly recorded. Disk/device
faults, recorder merge time, native model calls and real hardware throughput
remain independent risks. Callback notifications must remain lightweight; a
blocked callback is not forcibly terminated, and shutdown reports its live owner.
Current paced file/synthetic replays are not WASAPI-to-screen or long-conference
certification. Historical M5/API reports are kept unchanged, with their limitations.
