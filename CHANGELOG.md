# Changelog

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
