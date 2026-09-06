from __future__ import annotations

import json
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from lingua_relay.config import CorrectionSettings
from lingua_relay.correction.provider import CorrectionProviderError, OpenAICompatibleProvider
from lingua_relay.correction.types import CorrectionRequest
from lingua_relay.events import CaptionEvent


def _request() -> CorrectionRequest:
    event = CaptionEvent("hello", "你好呀", "en", "zh", "final", 0)
    return CorrectionRequest(event, (), (), "final", event.segment_id, 0, 0)


def _settings(**kwargs) -> CorrectionSettings:
    values = {"provider": "local", "endpoint": "http://127.0.0.1/v1", "model": "test-model"}
    return CorrectionSettings(**(values | kwargs))


def _response_body(text="你好。", **kwargs):
    return {"choices": [{"message": {"content": text}, "finish_reason": "stop"}]} | kwargs


def _fake_response(body, *, status=200, headers=None, settings=None):
    transport = httpx.MockTransport(
        lambda request: httpx.Response(status, json=body, headers=headers)
    )
    return OpenAICompatibleProvider(settings or _settings(), transport=transport)


@contextmanager
def _server(handler):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        thread.join(2)
        server.server_close()


def test_local_request_reuses_http11_connection_and_ignores_proxy(monkeypatch) -> None:
    received = []

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers["Content-Length"])
            received.append(
                {
                    "path": self.path,
                    "authorization": self.headers.get("Authorization"),
                    "body": json.loads(self.rfile.read(length)),
                    "client": self.client_address,
                }
            )
            response = json.dumps(_response_body(), ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)

        def log_message(self, _format: str, *args: object) -> None:
            return

    monkeypatch.delenv("LINGUA_RELAY_API_KEY", raising=False)
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        monkeypatch.setenv(name, "http://127.0.0.1:1")
    monkeypatch.setenv("NO_PROXY", "")
    with _server(Handler) as server:
        settings = _settings(endpoint=f"http://127.0.0.1:{server.server_port}/v1")
        with OpenAICompatibleProvider(settings) as provider:
            first = provider.revise(_request())
            second = provider.revise(_request())
        assert provider._client.is_closed
        provider.close()

    assert first.text == second.text == "你好。"
    assert first.scope == "local"
    assert len(received) == 2
    assert received[0]["client"] == received[1]["client"]
    assert received[0]["path"] == "/v1/chat/completions"
    assert received[0]["authorization"] is None
    assert received[0]["body"]["model"] == "test-model"


def test_cloud_provider_requires_api_key_before_network(monkeypatch) -> None:
    monkeypatch.delenv("MISSING_TEST_KEY", raising=False)

    def no_network(request):
        pytest.fail("missing key must fail before transport")

    settings = _settings(
        provider="openai_compatible",
        endpoint="https://api.example.test/v1",
        api_key_env="MISSING_TEST_KEY",
    )
    with (
        OpenAICompatibleProvider(settings, transport=httpx.MockTransport(no_network)) as provider,
        pytest.raises(CorrectionProviderError, match="MISSING_TEST_KEY"),
    ):
        provider.revise(_request())


def test_provider_rejects_invalid_response() -> None:
    with _fake_response({}) as provider, pytest.raises(CorrectionProviderError, match="invalid"):
        provider.revise(_request())


def test_provider_timeout_is_bounded() -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            time.sleep(0.2)

        def log_message(self, _format: str, *args: object) -> None:
            return

    with _server(Handler) as server:
        settings = _settings(
            endpoint=f"http://127.0.0.1:{server.server_port}", timeout_seconds=0.02
        )
        with OpenAICompatibleProvider(settings) as provider:
            started = time.monotonic()
            with pytest.raises(CorrectionProviderError, match="timeout"):
                provider.revise(_request())
            assert time.monotonic() - started < 0.15


@pytest.mark.parametrize("reason", ["length", "content_filter", "tool_calls", "error", ["bad"]])
def test_provider_rejects_explicit_incomplete_finish_reason(reason) -> None:
    body = {"choices": [{"message": {"content": "被截断的文字"}, "finish_reason": reason}]}
    with (
        _fake_response(body) as provider,
        pytest.raises(CorrectionProviderError, match="incomplete"),
    ):
        provider.revise(_request())


def test_provider_reports_actual_model_and_sanitized_usage() -> None:
    body = _response_body(
        id="test-response",
        model="actual-model",
        usage={
            "cost": 0.0001,
            "prompt_tokens": 33,
            "total_tokens": "invalid",
            "completion_tokens": -1,
            "secret": "must not survive",
        },
    )
    with _fake_response(body) as provider:
        result = provider.revise(_request())
    assert result.model == "actual-model"
    assert result.response_id == "test-response"
    assert result.usage == {"cost": 0.0001, "prompt_tokens": 33}


def test_openrouter_routing_is_scoped_to_official_host(monkeypatch) -> None:
    monkeypatch.setenv("TEST_ROUTER_KEY", "test-not-a-real-key")
    received = []

    def capture(request):
        received.append(json.loads(request.content))
        return httpx.Response(200, json=_response_body())

    for endpoint in ("https://openrouter.ai/api/v1", "https://api.example.test/v1"):
        settings = _settings(
            provider="openai_compatible",
            endpoint=endpoint,
            api_key_env="TEST_ROUTER_KEY",
            openrouter_provider_sort="latency",
        )
        with OpenAICompatibleProvider(settings, transport=httpx.MockTransport(capture)) as provider:
            provider.revise(_request())
    assert received[0]["provider"] == {"sort": "latency"}
    assert "provider" not in received[1]


def test_openrouter_budget_enforces_server_price_cap(monkeypatch) -> None:
    monkeypatch.setenv("TEST_ROUTER_KEY", "test-not-a-real-key")
    received = []

    def capture(request):
        received.append(json.loads(request.content))
        return httpx.Response(200, json=_response_body())

    settings = _settings(
        provider="openai_compatible",
        endpoint="https://openrouter.ai/api/v1",
        api_key_env="TEST_ROUTER_KEY",
    )
    with OpenAICompatibleProvider(
        settings, openrouter_price_cap=1, transport=httpx.MockTransport(capture)
    ) as provider:
        provider.revise(_request())
    assert received[0]["provider"]["max_price"] == {"prompt": 1, "completion": 1}


def test_redirect_is_not_followed_or_exposed(monkeypatch) -> None:
    received = []
    monkeypatch.setenv("TEST_ROUTER_KEY", "private-test-key")

    def redirect(request):
        received.append(request)
        return httpx.Response(
            307,
            headers={"location": "https://another.example.test/private-data"},
            content=b"private-service-body",
        )

    settings = _settings(
        provider="openai_compatible",
        endpoint="https://api.example.test/v1",
        api_key_env="TEST_ROUTER_KEY",
    )
    with (
        OpenAICompatibleProvider(settings, transport=httpx.MockTransport(redirect)) as provider,
        pytest.raises(CorrectionProviderError) as captured,
    ):
        provider.revise(_request())
    assert str(captured.value) == "provider request failed: HTTP 307"
    assert len(received) == 1


def test_provider_rejects_oversized_response():
    class OversizedStream(httpx.SyncByteStream):
        def __iter__(self):
            yield b"x" * 600_000
            yield b"y" * 600_000

    transport = httpx.MockTransport(lambda request: httpx.Response(200, stream=OversizedStream()))
    with (
        OpenAICompatibleProvider(_settings(), transport=transport) as provider,
        pytest.raises(CorrectionProviderError, match="exceeded 1 MB"),
    ):
        provider.revise(_request())


def test_provider_suppresses_transport_exception_details():
    def fail(request):
        raise httpx.ConnectError("secret-header: private-test-key", request=request)

    with (
        OpenAICompatibleProvider(_settings(), transport=httpx.MockTransport(fail)) as provider,
        pytest.raises(CorrectionProviderError) as captured,
    ):
        provider.revise(_request())
    assert str(captured.value) == "provider request failed: network transport error"
    assert captured.value.__suppress_context__


def test_provider_rejects_responses_that_cross_elapsed_deadline():
    class SlowStream(httpx.SyncByteStream):
        def __iter__(self):
            time.sleep(0.03)
            yield json.dumps(_response_body()).encode()

    transport = httpx.MockTransport(lambda request: httpx.Response(200, stream=SlowStream()))
    with (
        OpenAICompatibleProvider(_settings(timeout_seconds=0.01), transport=transport) as provider,
        pytest.raises(CorrectionProviderError, match="deadline exceeded"),
    ):
        provider.revise(_request())


def test_closed_provider_rejects_new_request():
    provider = _fake_response(_response_body())
    provider.close()
    with pytest.raises(CorrectionProviderError, match="client is closed"):
        provider.revise(_request())
