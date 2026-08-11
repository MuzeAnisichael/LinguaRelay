from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from lingua_relay.config import CorrectionSettings
from lingua_relay.correction.provider import CorrectionProviderError, OpenAICompatibleProvider
from lingua_relay.correction.types import CorrectionRequest
from lingua_relay.events import CaptionEvent


def _request() -> CorrectionRequest:
    event = CaptionEvent("hello", "你好呀", "en", "zh", "final", 0)
    return CorrectionRequest(event, (), (), "final", event.segment_id, 0, 0)


def test_local_openai_compatible_request_and_response(monkeypatch) -> None:
    received: dict[str, object] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers["Content-Length"])
            received["path"] = self.path
            received["authorization"] = self.headers.get("Authorization")
            received["body"] = json.loads(self.rfile.read(length))
            response = json.dumps(
                {"choices": [{"message": {"content": "你好。"}}]}, ensure_ascii=False
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)

        def log_message(self, _format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.delenv("LINGUA_RELAY_API_KEY", raising=False)
    try:
        provider = OpenAICompatibleProvider(
            CorrectionSettings(
                provider="local",
                endpoint=f"http://127.0.0.1:{server.server_port}/v1",
                model="mock-model",
            )
        )
        result = provider.revise(_request())
    finally:
        server.shutdown()
        thread.join(2)
        server.server_close()

    assert result.text == "你好。"
    assert result.scope == "local"
    assert received["path"] == "/v1/chat/completions"
    assert received["authorization"] is None
    assert received["body"]["model"] == "mock-model"  # type: ignore[index]


def test_cloud_provider_requires_api_key_before_network(monkeypatch) -> None:
    monkeypatch.delenv("MISSING_TEST_KEY", raising=False)
    provider = OpenAICompatibleProvider(
        CorrectionSettings(
            provider="openai_compatible",
            endpoint="https://api.example.test/v1",
            api_key_env="MISSING_TEST_KEY",
            model="cloud-model",
        )
    )

    with pytest.raises(CorrectionProviderError, match="MISSING_TEST_KEY"):
        provider.revise(_request())


def test_provider_rejects_invalid_response() -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            response = b"{}"
            self.send_response(200)
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)

        def log_message(self, _format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        provider = OpenAICompatibleProvider(
            CorrectionSettings(
                provider="local",
                endpoint=f"http://127.0.0.1:{server.server_port}",
                model="mock-model",
            )
        )
        with pytest.raises(CorrectionProviderError, match="invalid"):
            provider.revise(_request())
    finally:
        server.shutdown()
        thread.join(2)
        server.server_close()


def test_provider_timeout_is_bounded() -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            time.sleep(0.2)

        def log_message(self, _format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        provider = OpenAICompatibleProvider(
            CorrectionSettings(
                provider="local",
                endpoint=f"http://127.0.0.1:{server.server_port}",
                model="mock-model",
                timeout_seconds=0.02,
            )
        )
        started = time.monotonic()
        with pytest.raises(CorrectionProviderError, match="failed"):
            provider.revise(_request())
        assert time.monotonic() - started < 0.15
    finally:
        server.shutdown()
        thread.join(2)
        server.server_close()
