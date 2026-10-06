# Changelog

## Unreleased

Source version remains **0.3.3**; the latest public release is **v0.3.2**. This maintenance work does not create a new version, tag, or GitHub Release.

- Updated the problem-linked roadmap: 0.3.3 reliability/measurement, followed by candidate 0.3.4 realtime readability, 0.3.5 offline resource/workbench, and 0.4.0 language expansion stages. Only the 0.3.3 scope is confirmed.
- Made ASR/MT final admission nonblocking, output waits deadline-bound, and service retries bounded; drain downstream before upstream admission to avoid full-final queue cycles.
- Isolated realtime audio submission from recording consumption. Sustained overload visibly pauses subtitles, counts rejected/cancelled work, and leaves explicit recording running; recovery waits for old native calls and creates fresh worker queues.
- Added two-phase shutdown with a shared total deadline, retained ownership after timeout, restart/removal guards, and rejection of late Qt/LLM deliveries across stop or overload recovery.
- Kept translation running after history-write OS errors, with a separate failure counter and visible warning rather than killing the worker or duplicating captions.
- Added bounded payload-free pipeline traces, distinct source/translation widget acknowledgements, synthetic and existing-local-model replay tools, and independent functional/performance/quality evidence states. Widget updates are not paint measurements; absent approved thresholds or human quality evidence remain not evaluated.

- Added concise project-level agent rules, historical requirement/decision context, a current handoff checkpoint, a known-issue ledger, and a 17-requirement verification map to support recovery across sessions and context compaction.
- Backfilled historical user needs, task-specific API/release authorization boundaries, 12 open risk/gap records and 7 historical problem records; registration does not constitute new functional fixes.
- Connected traceability and evidence checks to the developer/contributor guides, PR template and issue forms; documented parent-directory rule-loading limits and the absence of an automatic requirement-coverage CI gate.
- Qualified queue-capacity vs waiting bounds, recording/ASR overload coupling, model/API vs audio-to-screen timings, and historical quality-gate/sample limitations without rewriting dated benchmark reports.

- Added a unified requirement/status baseline and a developer guide with module ownership, directory navigation, targeted tests, and explicit build/release boundaries.
- Corrected both READMEs to link to the actual public v0.3.2 assets and distinguish unreleased features from downloadable functionality.
- Updated architecture and roadmap descriptions for partial translation, existing punctuation endpointing, explicit recording/import persistence, and the limits of historical performance evidence.
- Extracted audio capture/recording lifecycle into an independent runtime so recording can continue without loaded ASR/MT models, through model errors, or while live captions are paused; locked source changes for both active and paused recordings.
- Extracted offline task coordination from the desktop controller; recording-end and import workflows share the workbench ASR/quality/LLM options. Added cooperative cancellation, task-cleanup gating, preservation of saved cues on cancellation, and restoration of the prior live-caption pause state.
- Made cue replacement and completed-project state one SQLite transaction, so cancellation before commit preserves prior edits; cancellation after commit does not retract successful results.
- Streamed WAV fragment merging in 64K-frame blocks instead of loading whole fragments. Recording start/resume now isolates pre-boundary buffered audio, and recording failures clear active UI controls.

## 0.3.3 — unreleased development snapshot

The following work was locally validated on **2026-09-07**, but v0.3.3 has not been publicly released. Historical validation applies to that snapshot, not automatically to later changes under the same source version.

- Hardened LLM revision against stale results, unbounded zero-context requests, shutdown races, rate-limit/circuit-breaker failures, and invalid or truncated responses; preserved fast translation on correction failures.
- Added pooled HTTP connections, an OpenRouter preset, and optional latency/price routing; API credentials remain environment-only.
- Isolated the release environment with committed version locks, generated the SBOM from actual bundled metadata, and pruned nonessential Qt dependencies with retained-library dependency checks.
- Added final-EXE runtime/media/UI self-tests and isolated installer regression tests; stopped recursively deleting the application directory during uninstall so unregistered user files survive.
- Clarified installer model-directory discovery versus application-level integrity verification.
- Recorded 206 passing regressions, frozen-EXE and isolated installation checks, and 204 synthetic-caption OpenRouter calls. See the [local validation scope](docs/benchmarks/v0.3.3-local-validation.json) and [LLM latency/quality report](docs/benchmarks/OPENROUTER-v0.3.3.zh-CN.md); these are not clean-machine, real-device long-run, or universal accuracy certifications.

## 0.3.2 - 2026-08-27

- Added installer migration cleanup for incompatible ICU/OpenSSL DLLs left by v0.3.0, so the QtCore startup fix also applies to in-place upgrades without touching models or user data.
- Documented safe portable upgrades through a fresh extraction directory.

## 0.3.1 - 2026-08-27

- Fixed a Windows startup failure where the release build could bundle a foreign ICU runtime and prevent `PySide6.QtCore` from loading with WinError 127.
- Isolated PyInstaller dependency discovery from workspace toolchains, added frozen QtCore load verification, and rejected contaminated ICU DLLs before an installer can be produced.

## 0.3.0 - 2026-08-26

- Added start, pause, resume, and stop recording for the current system, process, or microphone source, with crash-recoverable WAV fragments and pause gaps removed from the media timeline.
- Added an offline project workbench with persistent SQLite metadata, playback, waveform seeking, time-aligned editable source/translation cues, and task progress.
- Added audio import and video audio-track extraction through PyAV, followed by a shared high-quality offline recognition and translation pipeline.
- Added faster-whisper word timestamps, punctuation-aware readable cue splitting, accuracy profiles, optional per-cue LLM revision, and the opt-in Large-v3 model.
- Added WAV, FLAC, MP3, WebVTT, SRT, ASS, TXT, CSV, and JSONL export.
- Updated the overlay with compact recording and workbench controls; updated installer, privacy, model, uninstaller, packaging, and release documentation for persisted recordings.

## 0.2.0 - 2026-08-13

- Added native Windows per-process audio capture, including the selected process tree, automatic PID recovery after app restarts, and runtime tray/settings switching.
- Added independent WASAPI microphone capture with default/explicit input selection and automatic reconnect.
- Added Base, Small, Medium, and Large-v3 Turbo recognition choices plus fast, balanced, and accurate decoding profiles with explicit CPU/GPU precision controls.
- Added M2M100 418M/1.2B translation choices and three beam-search quality profiles; advanced downloads are explicit, resumable, and preceded by size/hardware guidance.
- Improved recognition stability with repetition suppression, no-repeat n-grams, Whisper confidence filters, and endpoint-aligned Silero VAD parameters.
- Bundled a self-contained NAudio process-capture helper and extended packaging, installer detection, model removal, documentation, and release validation for the new runtime.

## 0.1.5 - 2026-08-12

- Added balanced, real-time, and resource-saving caption profiles; long speech now adapts partial inference cadence from 320 ms to 640/960 ms and defaults to a six-second caption cap.
- Added optional ASR context hints for meeting topics, participant names, product names, and specialist terminology, plus stable semicolon endpointing.
- Added a complete graphical LLM settings tab with local/cloud OpenAI-compatible providers, Ollama and LM Studio presets, safe environment-variable credentials, and correction limits.
- Added compact overlay controls for pause/resume, translated/bilingual display, history, settings, and hide while preserving drag, resize, and click-through behavior.
- Added recommended Small and lightweight Base model profiles, first-launch guidance, existing-model adoption, offline ZIP installation, and separate verified release packs.
- Rewrote the installer introduction, model detection messages, privacy/LLM explanation, model-selection guidance, and uninstall wording.
- Prevented an older partial translation from replacing a newer recognition revision in the overlay.

## 0.1.2 - 2026-08-12

- Added a persistent user settings dialog for language route, subtitle retention, fonts, colors, opacity, status visibility, history, and live recognition cadence.
- Added automatic subtitle clearing with a configurable 0–120 second retention period; zero keeps the latest subtitle indefinitely.
- Added optional filtering for short template-like Whisper hallucinations such as “字幕制作人 Zither Harp” and “Subtitles by”.
- Added in-app model removal and application-uninstall entry points; the Windows uninstaller can optionally remove the 1.36 GiB local model pack while preserving configuration and caption history.
- Changed the producer, package author, Windows publisher, and copyright owner to Leeleelee.

## 0.1.1 - 2026-08-12

- Added drag, edge/corner resize, geometry persistence, and tray reset for the overlay.
- Added installer-time model detection plus first-launch discovery and SHA-256 verification of existing local model directories.
- Split long speech at a short pause after six seconds and enforce a ten-second caption cap, including for existing v0.1.0 configuration files.
- Added explicit model-ready feedback in the overlay and Windows notification area.
- Show recognition before translation completes, preserve useful in-flight partials, and finalize captions on stable sentence punctuation.
- Replaced the plain history text box with a searchable, filterable latest-revision browser and improved SRT revision handling.
- Added a simpler speech-relay application, taskbar, shortcut, and installer icon.

## 0.1.0 - 2026-08-11

- First public Windows x64 release with background WASAPI output capture and a compact overlay.
- Manual mutual translation between Simplified Chinese, Japanese, English, and Korean (12 routes).
- Translation-only and bilingual display modes, local caption history/export, tray controls, and global show/hide shortcut.
- Optional asynchronous local or OpenAI-compatible LLM correction with traceable revisions and fail-open fast translation.
- On-demand, license-disclosed, SHA-256-verified local ASR/MT model installation.
- Unclean-exit detection, bounded local crash reports, advisory-only update checking, privacy notice, threat model, SBOM, and release checksums.

Known limitation: on the measured CPU configuration, first-caption latency was 2.98 s P50 and 11.77 s P95 across the M5 corpus; GPU performance depends on local CUDA compatibility. v0.1.0 binaries are not Authenticode-signed.
