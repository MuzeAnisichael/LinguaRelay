# LinguaRelay v0.2.0 Threat Model

## Overview

LinguaRelay is a per-user Windows desktop application that captures system output, a selected process tree, or a microphone, performs four-language speech recognition and translation locally, renders an overlay, and optionally submits caption text to a configured LLM correction endpoint. It stores configuration and optional text history in the current user's LocalAppData. The protected assets are private spoken content, caption history, API credentials, model/executable integrity, and availability of the caption fast path.

Security policy scope is defined by `SECURITY.md`. v0.2.0 is not approved for sensitive or regulated audio. The binaries remain unsigned because the project does not yet possess a code-signing certificate; published SHA-256 checksums reduce accidental corruption risk but are not a substitute for Authenticode publisher identity.

## Threat Model, Trust Boundaries, and Assumptions

Trust boundaries are:

1. Windows audio and device APIs to native PyAudio/PortAudio and decoding code;
2. untrusted audio samples to ASR inference and untrusted recognized text to translation/UI/history;
3. GitHub/Hugging Face HTTPS model delivery to the LocalAppData model directory;
4. local configuration/environment variables to optional correction providers;
5. the process to local history, crash reports, model cache, and installed files;
6. GitHub's releases API to the update-notification UI.

Assumptions: Windows and the current user account are not already compromised; GitHub TLS and repository controls remain trustworthy; an attacker able to replace the unsigned installed executable can control the process; model licenses and exact revisions are disclosed; cloud correction is an explicit opt-in; raw PCM is not persisted by application code.

## Attack Surface, Mitigations, and Attacker Stories

| Surface | Attacker story | Existing mitigation | Residual risk |
|---|---|---|---|
| WASAPI/native audio stack | Crafted or malformed device/audio data triggers memory corruption or denial of service in PyAudio, NAudio, or the .NET helper. | Fixed PCM formats, 16 kHz normalization, bounded queues, a narrow PID-only helper interface, supported dependency ranges, crash recovery. | Native dependency flaws remain possible; update dependencies promptly. |
| Model download/install | A network or archive attacker installs arbitrary files or corrupted weights. | Fixed approved GitHub HTTPS hosts, archive size cap, exact allowlisted paths, traversal/symlink rejection, embedded per-file SHA-256, staging and transactional replacement. | A compromised release account or replaced unsigned app can also replace the trusted manifest. |
| Caption/history files | Another local process reads private text or plants malformed configuration/history. | Per-user LocalAppData, strict configuration schema and bounded readers/outputs; no raw audio files. | Processes under the same user can normally read or modify these files. |
| Cloud correction | Captions, context, or glossary data are disclosed to an unintended service; prompt text attempts instruction injection. | Off by default, explicit local/cloud status, cloud requires HTTPS, local endpoints must resolve to loopback, no redirects, API key from environment, prompt treats captions as untrusted data, output/time/rate limits and circuit breaker. | The chosen cloud operator receives submitted text and can return misleading revisions. |
| Local correction server | DNS rebinding or URL tricks escape loopback. | URL validation, no credentials/fragments, loopback-only resolution checked at request time, no redirects. | A malicious process already listening locally can impersonate the configured service. |
| Update check | Remote response causes silent code execution or downgrade. | JSON is treated as notification metadata; versions are strictly parsed; only a GitHub HTTPS page is opened; no automatic installer execution. | Users must authenticate releases themselves; v0.2.0 is unsigned. |
| Overlay/hotkey | Spoofed captions mislead the user or a global shortcut leaks content. | Overlay is visibly associated with LinguaRelay; manual language selection; original fast translation retained when correction fails. | ASR/MT/LLM outputs are probabilistic and must not drive safety-critical decisions. |
| Resource exhaustion | Long audio, slow APIs, or rapid partials consume memory/CPU and stall captions. | Bounded newest-first queues, partial replacement, fixed windows, LRU caches, timeouts, rate limiting and circuit breaking. | Heavy CPU use and caption delay remain possible on low-end systems. |

## Severity Calibration

- Critical: reliable arbitrary code execution in the default path, or silent compromise of distributed release/model integrity at scale.
- High: default-path extraction of private audio/caption data across user boundaries, credential theft, or sandbox escape from parsed content.
- Medium: opt-in cloud disclosure beyond the documented scope, persistent local tampering requiring same-user access, or repeatable denial of service requiring crafted input.
- Low: limited metadata exposure, transient local crashes with recovery, UI confusion, or issues requiring an already-compromised user account.

Reports should include the reachable boundary, required configuration, affected asset, and whether the behavior occurs with default settings. Do not attach private recordings, API keys, or unredacted histories.
