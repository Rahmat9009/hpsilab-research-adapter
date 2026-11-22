"""Offline defaults and the explicitly blocked SDK integration seam."""

import os
import socket
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from sdk_contract import SDKContract


@pytest.fixture(autouse=True)
def offline_only(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Reject Python socket traffic/DNS and remove ambient HPSILab credentials."""

    def forbidden_network(*args: object, **kwargs: object) -> None:
        pytest.fail("Network access is forbidden in this offline test suite")

    for name in ("create_connection", "getaddrinfo", "gethostbyname", "gethostbyname_ex"):
        monkeypatch.setattr(socket, name, forbidden_network)
    for name in ("connect", "connect_ex", "sendto", "sendmsg"):
        if hasattr(socket.socket, name):
            monkeypatch.setattr(socket.socket, name, forbidden_network)
    for name in tuple(os.environ):
        if "HPSILAB" in name.upper():
            monkeypatch.delenv(name, raising=False)
    yield


@pytest.fixture
def sdk_contract() -> SDKContract:
    """Bind the contract to the real ResearchClient and real hpsilab_mcp exceptions."""
    from hpsilab_mcp import (
        HpsiMcpAPIError,
        HpsiMcpAuthError,
        HpsiMcpInsufficientCreditsError,
        HpsiMcpRateLimitError,
        HpsiMcpTimeoutError,
    )

    from hpsilab_research_adapter import errors as adapter_errors
    from hpsilab_research_adapter.client import ResearchClient
    from hpsilab_research_adapter.normalize import normalize

    def make_invocation(api_key: str | None, request: Any, sleep: Any) -> Callable[[], Any]:
        def invoke() -> Any:
            client = ResearchClient(api_key, request=request, sleep=sleep)
            try:
                return client.run("analyze_stock", "TEST")
            finally:
                client.close()

        return invoke

    def make_failure(kind: str, synthetic_credential: str) -> Exception:
        text = f"synthetic upstream failure api_key={synthetic_credential}"
        body = {"detail": synthetic_credential}
        if kind == "rate_limit":
            return HpsiMcpRateLimitError(
                text, status_code=429, response_text=text, body=body, retry_after_seconds=1
            )
        if kind == "credits":
            return HpsiMcpInsufficientCreditsError(
                text,
                status_code=402,
                response_text=text,
                body=body,
                credits_required=5,
                credits_remaining=0,
            )
        if kind == "timeout":
            return HpsiMcpTimeoutError(text)
        if kind == "auth":
            return HpsiMcpAuthError(text, status_code=401, response_text=text, body=body)
        if kind.startswith("server_"):
            return HpsiMcpAPIError(
                text, status_code=int(kind.removeprefix("server_")), response_text=text, body=body
            )
        raise ValueError(f"unsupported failure kind: {kind}")

    success_response = {"symbol": "TEST", "summary": "synthetic-only", "score": 0.5}
    return SDKContract(
        make_invocation=make_invocation,
        make_failure=make_failure,
        errors={
            "RateLimited": adapter_errors.RateLimited,
            "CreditsExhausted": adapter_errors.CreditsExhausted,
            "Timeout": adapter_errors.Timeout,
            "UpstreamError": adapter_errors.UpstreamError,
            "AuthError": adapter_errors.AuthError,
        },
        success_response=success_response,
        expected_result=normalize("analyze_stock", "TEST", success_response),
        timeout_attempts=1,
    )
