from __future__ import annotations

import json
import os
import socket
import time
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from lingua_relay.config import CorrectionSettings, _validate_correction_endpoint
from lingua_relay.correction.prompt import build_messages
from lingua_relay.correction.types import CorrectionRequest, RevisionResult


class CorrectionProviderError(RuntimeError):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


class OpenAICompatibleProvider:
    """Minimal chat-completions client for local or HTTPS OpenAI-compatible APIs."""

    def __init__(self, settings: CorrectionSettings) -> None:
        if settings.provider not in {"local", "openai_compatible"}:
            raise ValueError("an OpenAI-compatible correction provider is not configured")
        _validate_correction_endpoint(settings.provider, settings.endpoint)
        if not settings.model.strip():
            raise ValueError("correction model must not be empty")
        self.settings = settings
        self.name = settings.provider
        self.model = settings.model
        self.scope = "local" if settings.provider == "local" else "cloud"
        self.url = _chat_completions_url(settings.endpoint)
        self._opener = urllib.request.build_opener(_NoRedirect())

    def revise(self, request: CorrectionRequest) -> RevisionResult:
        started = time.monotonic_ns()
        if self.scope == "local":
            _ensure_loopback_resolution(self.url)
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "LinguaRelay/0.4",
        }
        api_key = os.environ.get(self.settings.api_key_env, "").strip()
        if self.scope == "cloud" and not api_key:
            raise CorrectionProviderError(
                f"missing cloud API key environment variable: {self.settings.api_key_env}"
            )
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        payload = json.dumps(
            {
                "model": self.model,
                "messages": build_messages(request),
                "temperature": self.settings.temperature,
                "max_tokens": self.settings.max_tokens,
                "stream": False,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        http_request = urllib.request.Request(
            self.url, data=payload, headers=headers, method="POST"
        )
        try:
            with self._opener.open(http_request, timeout=self.settings.timeout_seconds) as response:
                raw = response.read(1_000_001)
        except (OSError, urllib.error.URLError, urllib.error.HTTPError) as error:
            raise CorrectionProviderError(f"provider request failed: {error}") from error
        if len(raw) > 1_000_000:
            raise CorrectionProviderError("provider response exceeded 1 MB")
        try:
            body: Any = json.loads(raw.decode("utf-8"))
            text = body["choices"][0]["message"]["content"]
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, IndexError, TypeError) as error:
            raise CorrectionProviderError("invalid chat-completions response") from error
        if not isinstance(text, str):
            raise CorrectionProviderError("chat-completions content must be text")
        text = _clean_output(text)
        if not text:
            raise CorrectionProviderError("provider returned an empty revision")
        if len(text) > self.settings.max_output_chars:
            raise CorrectionProviderError("provider revision exceeded max_output_chars")
        return RevisionResult(
            text=text,
            inference_ms=(time.monotonic_ns() - started) / 1e6,
            provider=self.name,
            model=self.model,
            scope=self.scope,  # type: ignore[arg-type]
        )


def _chat_completions_url(endpoint: str) -> str:
    parsed = urlsplit(endpoint)
    path = parsed.path.rstrip("/")
    if path.endswith("/chat/completions"):
        final_path = path
    elif path.endswith("/v1"):
        final_path = path + "/chat/completions"
    elif not path:
        final_path = "/v1/chat/completions"
    else:
        final_path = path + "/v1/chat/completions"
    return urlunsplit((parsed.scheme, parsed.netloc, final_path, parsed.query, ""))


def _clean_output(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```") and cleaned.endswith("```"):
        lines = cleaned.splitlines()
        cleaned = "\n".join(lines[1:-1]).strip()
    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in {'"', "'"}:
        cleaned = cleaned[1:-1].strip()
    return cleaned


def _ensure_loopback_resolution(url: str) -> None:
    parsed = urlsplit(url)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        addresses = socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)
    except OSError as error:
        raise CorrectionProviderError(f"cannot resolve local provider: {error}") from error
    from ipaddress import ip_address

    if not addresses or any(not ip_address(item[4][0]).is_loopback for item in addresses):
        raise CorrectionProviderError("local provider resolved outside the loopback interface")
