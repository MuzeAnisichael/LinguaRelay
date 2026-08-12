# Changelog

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
