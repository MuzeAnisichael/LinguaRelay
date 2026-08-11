# Changelog

## 0.1.0 - 2026-08-11

- First public Windows x64 release with background WASAPI output capture and a compact overlay.
- Manual mutual translation between Simplified Chinese, Japanese, English, and Korean (12 routes).
- Translation-only and bilingual display modes, local caption history/export, tray controls, and global show/hide shortcut.
- Optional asynchronous local or OpenAI-compatible LLM correction with traceable revisions and fail-open fast translation.
- On-demand, license-disclosed, SHA-256-verified local ASR/MT model installation.
- Unclean-exit detection, bounded local crash reports, advisory-only update checking, privacy notice, threat model, SBOM, and release checksums.

Known limitation: on the measured CPU configuration, first-caption latency was 2.98 s P50 and 11.77 s P95 across the M5 corpus; GPU performance depends on local CUDA compatibility. v0.1.0 binaries are not Authenticode-signed.
