from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass
from urllib.parse import urlsplit

RELEASES_API = "https://api.github.com/repos/MuzeAnisichael/LinguaRelay/releases/latest"


@dataclass(frozen=True, slots=True)
class UpdateInfo:
    current_version: str
    latest_version: str
    release_url: str

    @property
    def available(self) -> bool:
        return _version_tuple(self.latest_version) > _version_tuple(self.current_version)


def check_for_update(current_version: str, *, timeout: float = 5.0) -> UpdateInfo:
    request = urllib.request.Request(
        RELEASES_API,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"LinguaRelay/{current_version}",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        if urlsplit(response.geturl()).hostname != "api.github.com":
            raise ValueError("unexpected update service redirect")
        payload = json.load(response)
    tag = str(payload["tag_name"]).removeprefix("v")
    release_url = str(payload["html_url"])
    parsed = urlsplit(release_url)
    if parsed.scheme != "https" or parsed.hostname != "github.com":
        raise ValueError("invalid release URL")
    return UpdateInfo(current_version, tag, release_url)


def _version_tuple(version: str) -> tuple[int, int, int]:
    base = version.removeprefix("v").split("-", 1)[0].split("+", 1)[0]
    parts = base.split(".")
    if len(parts) != 3 or any(not part.isdigit() for part in parts):
        raise ValueError(f"invalid release version: {version}")
    major, minor, patch = (int(part) for part in parts)
    return major, minor, patch
