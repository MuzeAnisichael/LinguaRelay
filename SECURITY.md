# Security Policy

Please report security or privacy issues privately through GitHub's security
advisory feature once it is enabled for the repository. Do not include API keys,
private recordings, or unredacted translation history in a public issue.

The current pre-alpha version is not supported for sensitive or regulated audio.
Raw audio persistence is intentionally disabled by default.

M4 correction is also disabled by default. Local provider URLs are limited to
loopback addresses and are re-checked after name resolution; cloud providers
must use HTTPS. Redirects are not followed. API keys are read from the named
environment variable, never from the TOML file or caption history. Enabling a
cloud provider transmits source text, fast translation, recent text context,
and matching glossary entries to that endpoint; the tray and overlay label
that state as cloud transmission.

M1 diagnostics keep PCM in memory. Stress reports may contain the local audio
device name and performance counters but never audio samples. Review a report
before sharing it if device names are considered sensitive in your environment.
