# Security Policy

Please report security or privacy issues privately through GitHub's security
advisory feature once it is enabled for the repository. Do not include API keys,
private recordings, or unredacted translation history in a public issue.

The current pre-alpha version is not supported for sensitive or regulated audio.
Raw audio persistence is intentionally disabled by default.

M1 diagnostics keep PCM in memory. Stress reports may contain the local audio
device name and performance counters but never audio samples. Review a report
before sharing it if device names are considered sensitive in your environment.
