from __future__ import annotations

import json
import math
import os
import socket
import time
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from lingua_relay import __version__
from lingua_relay.config import CorrectionSettings, _validate_correction_endpoint
from lingua_relay.correction.prompt import build_messages
from lingua_relay.correction.types import CorrectionRequest, RevisionResult


class CorrectionProviderError(RuntimeError):
    pass


class OpenAICompatibleProvider:
    """Reusable chat-completions client for local or HTTPS compatible APIs.

    One client retains pooled connections between subtitle revisions. Owners
    must close it after their worker finishes, not while a request is active.
    """

    def __init__(
        self,
        settings: CorrectionSettings,
        *,
        openrouter_price_cap: float | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
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
        if openrouter_price_cap is not None and (
            not math.isfinite(openrouter_price_cap) or openrouter_price_cap <= 0
        ):
            raise ValueError("OpenRouter price cap must be positive USD per million tokens")
        self._price_cap = openrouter_price_cap
        self._client = httpx.Client(
            timeout=httpx.Timeout(settings.timeout_seconds),
            limits=httpx.Limits(
                max_connections=2, max_keepalive_connections=2, keepalive_expiry=60
            ),
            follow_redirects=False,
            # A local-only provider must never be rerouted through a proxy
            # supplied by HTTP_PROXY/HTTPS_PROXY/ALL_PROXY environment variables.
            trust_env=self.scope != "local",
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> OpenAICompatibleProvider:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def revise(self, request: CorrectionRequest) -> RevisionResult:
        started = time.monotonic_ns()
        deadline = started + int(self.settings.timeout_seconds * 1e9)
        if self._client.is_closed:
            raise CorrectionProviderError("provider request failed: client is closed")
        if self.scope == "local":
            _ensure_loopback_resolution(self.url)
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": f"LinguaRelay/{__version__}",
        }
        api_key = os.environ.get(self.settings.api_key_env, "").strip()
        if self.scope == "cloud" and not api_key:
            raise CorrectionProviderError(
                f"missing cloud API key environment variable: {self.settings.api_key_env}"
            )
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        body_request: dict[str, Any] = {
            "model": self.model,
            "messages": build_messages(request),
            "temperature": self.settings.temperature,
            "max_tokens": self.settings.max_tokens,
            "stream": False,
        }
        if urlsplit(self.url).hostname == "openrouter.ai":
            routing: dict[str, Any] = {}
            if self.settings.openrouter_provider_sort:
                routing["sort"] = self.settings.openrouter_provider_sort
            if self._price_cap is not None:
                routing["max_price"] = {
                    "prompt": self._price_cap,
                    "completion": self._price_cap,
                }
            if routing:
                body_request["provider"] = routing
        elif self._price_cap is not None:
            raise ValueError("OpenRouter price cap requires the official OpenRouter endpoint")
        payload = json.dumps(
            body_request,
            ensure_ascii=False,
        ).encode("utf-8")
        try:
            with self._client.stream(
                "POST", self.url, content=payload, headers=headers
            ) as response:
                if not 200 <= response.status_code < 300:
                    # Never echo a service body, redirect URL, headers, or API
                    # credentials in application errors/history.
                    raise CorrectionProviderError(
                        f"provider request failed: HTTP {response.status_code}"
                    )
                raw = bytearray()
                # HTTP chunk iteration bounds memory and checks elapsed time;
                # API streaming remains disabled so only complete revisions are
                # displayed. The socket read timeout also bounds idle periods.
                for chunk in response.iter_bytes():
                    if time.monotonic_ns() > deadline:
                        raise CorrectionProviderError("provider request failed: deadline exceeded")
                    if len(raw) + len(chunk) > 1_000_000:
                        raise CorrectionProviderError("provider response exceeded 1 MB")
                    raw.extend(chunk)
                if time.monotonic_ns() > deadline:
                    raise CorrectionProviderError("provider request failed: deadline exceeded")
        except httpx.TimeoutException:
            raise CorrectionProviderError("provider request failed: timeout") from None
        except (httpx.HTTPError, OSError):
            raise CorrectionProviderError(
                "provider request failed: network transport error"
            ) from None
        try:
            body: Any = json.loads(raw.decode("utf-8"))
            choice = body["choices"][0]
            text = choice["message"]["content"]
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, IndexError, TypeError):
            raise CorrectionProviderError("invalid chat-completions response") from None
        if not isinstance(text, str):
            raise CorrectionProviderError("chat-completions content must be text")
        # Some local compatible servers omit finish_reason. Explicit non-success
        # reasons must never replace a usable fast translation with a fragment.
        finish_reason = choice.get("finish_reason")
        if finish_reason is not None and finish_reason != "stop":
            raise CorrectionProviderError("incomplete provider revision")
        text = _clean_output(text)
        if not text:
            raise CorrectionProviderError("provider returned an empty revision")
        if len(text) > self.settings.max_output_chars:
            raise CorrectionProviderError("provider revision exceeded max_output_chars")
        return RevisionResult(
            text=text,
            inference_ms=(time.monotonic_ns() - started) / 1e6,
            provider=self.name,
            model=body.get("model") if isinstance(body.get("model"), str) else self.model,
            scope=self.scope,  # type: ignore[arg-type]
            usage=_usage(body.get("usage")),
            response_id=body.get("id") if isinstance(body.get("id"), str) else None,
        )


def _usage(raw: Any) -> dict[str, int | float] | None:
    if not isinstance(raw, dict):
        return None
    return {
        key: raw[key]
        for key in ("prompt_tokens", "completion_tokens", "total_tokens", "cost")
        if isinstance(raw.get(key), (int, float))
        and not isinstance(raw[key], bool)
        and math.isfinite(raw[key])
        and raw[key] >= 0
    }


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
