"""Extra ResearchClient cases beyond the 12 error contracts. Offline only."""

from unittest.mock import Mock

import httpx
import pytest
from hpsilab_mcp import (
    HpsiMcpAPIError,
    HpsiMcpConfigError,
    HpsiMcpConnectionError,
    HpsiMcpRateLimitError,
    HpsiMcpResponseError,
    HpsiMcpTimeoutError,
    HpsiMcpValidationError,
)

from hpsilab_research_adapter.client import ResearchClient
from hpsilab_research_adapter.errors import (
    AuthError,
    CreditBudgetExceeded,
    RateLimited,
    Timeout,
    UnsafeConfiguration,
    UpstreamError,
)
from hpsilab_research_adapter.ledger import CreditLedger, RecordingTransport
from hpsilab_research_adapter.policy import BACKOFF_CAP_SECONDS, ENV_X402_WALLET

KEY = "test-only-credential-not-valid"
OK = {"symbol": "TEST", "score": 1}


def make(side_effect, **kw):
    request = Mock(side_effect=side_effect)
    sleep = Mock()
    return ResearchClient(KEY, request=request, sleep=sleep, **kw), request, sleep


def chain_texts(error: BaseException) -> list[str]:
    out, seen, cur = [], set(), error
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        out.append(f"{cur!s} {cur!r}")
        cur = cur.__cause__ or (None if cur.__suppress_context__ else cur.__context__)
    return out


def test_x402_env_refuses_before_any_request(monkeypatch):
    monkeypatch.setenv(ENV_X402_WALLET, "synthetic-wallet-value")
    request = Mock()
    with pytest.raises(UnsafeConfiguration) as caught:
        ResearchClient(KEY, request=request)
    request.assert_not_called()
    assert all("synthetic-wallet-value" not in t for t in chain_texts(caught.value))


def test_connection_error_retried_then_success():
    client, request, sleep = make([HpsiMcpConnectionError("down"), OK])
    assert client.run("analyze_stock", "test").data == OK
    assert request.call_count == 2
    assert sleep.call_count == 1


def test_connection_error_exhausts_as_upstream():
    client, request, sleep = make([HpsiMcpConnectionError("down")] * 3)
    with pytest.raises(UpstreamError) as caught:
        client.run("analyze_stock", "TEST")
    assert (request.call_count, sleep.call_count, caught.value.attempts) == (3, 2, 3)


def test_timeout_is_single_attempt():
    client, request, sleep = make([HpsiMcpTimeoutError("slow")] * 3)
    with pytest.raises(Timeout):
        client.run("analyze_stock", "TEST")
    assert request.call_count == 1
    sleep.assert_not_called()


@pytest.mark.parametrize("status", [400, 404, 422])
def test_other_4xx_not_retried(status):
    client, request, sleep = make([HpsiMcpAPIError("bad", status_code=status)])
    with pytest.raises(UpstreamError) as caught:
        client.run("analyze_stock", "TEST")
    assert caught.value.status_code == status
    request.assert_called_once()
    sleep.assert_not_called()


def test_response_error_not_retried():
    client, request, sleep = make([HpsiMcpResponseError("garbled", status_code=200)])
    with pytest.raises(UpstreamError):
        client.run("analyze_stock", "TEST")
    request.assert_called_once()
    sleep.assert_not_called()


def test_config_error_maps_to_auth_error():
    client, request, sleep = make([HpsiMcpConfigError("breaker open")])
    with pytest.raises(AuthError):
        client.run("analyze_stock", "TEST")
    request.assert_called_once()
    sleep.assert_not_called()


def test_validation_error_propagates_same_object():
    failure = HpsiMcpValidationError("nope", error="bad_input")
    client, request, sleep = make([failure])
    with pytest.raises(HpsiMcpValidationError) as caught:
        client.run("analyze_stock", "TEST")
    assert caught.value is failure
    request.assert_called_once()
    sleep.assert_not_called()


def test_budget_exceeded_propagates_unretried():
    failure = CreditBudgetExceeded("local cap", spent=1, budget=1)
    client, request, sleep = make([failure])
    with pytest.raises(CreditBudgetExceeded) as caught:
        client.run("analyze_stock", "TEST")
    assert caught.value is failure
    request.assert_called_once()
    sleep.assert_not_called()


def test_retry_after_is_honoured_and_capped():
    failures = [
        HpsiMcpRateLimitError("slow", status_code=429, retry_after_seconds=7),
        HpsiMcpRateLimitError("slow", status_code=429, retry_after_seconds=10_000),
        OK,
    ]
    client, _, sleep = make(failures)
    client.run("analyze_stock", "TEST")
    assert [c.args[0] for c in sleep.call_args_list] == [7, BACKOFF_CAP_SECONDS]


def test_backoff_without_retry_after_doubles():
    failures = [HpsiMcpRateLimitError("slow", status_code=429)] * 2 + [OK]
    client, _, sleep = make(failures)
    client.run("analyze_stock", "TEST")
    assert [c.args[0] for c in sleep.call_args_list] == [1.0, 2.0]


def test_rate_limit_error_carries_retry_after():
    client, _, _ = make([HpsiMcpRateLimitError("x", status_code=429, retry_after_seconds=3)] * 3)
    with pytest.raises(RateLimited) as caught:
        client.run("analyze_stock", "TEST")
    assert caught.value.retry_after_seconds == 3
    assert caught.value.status_code == 429


@pytest.mark.parametrize("raw", ["", "1BAD", "TOOLONGTICKER1", "A B", "A/B", "A;B", "../X", "$X"])
def test_bad_ticker_rejected_before_request(raw):
    client, request, _ = make([OK])
    with pytest.raises(ValueError):
        client.run("analyze_stock", raw)
    request.assert_not_called()


def test_ticker_is_stripped_and_uppercased():
    client, request, _ = make([OK])
    client.run("analyze_stock", "  brk.b ")
    assert request.call_args.args[1] == "BRK.B"


def test_unknown_tool_rejected():
    client, request, _ = make([OK])
    with pytest.raises(ValueError):
        client.run("generate_report", "TEST")
    request.assert_not_called()


def test_empty_key_raises_auth_error_without_client(monkeypatch):
    monkeypatch.setenv("HPSILAB_API_KEY", KEY)  # __init__ must not read it
    with pytest.raises(AuthError):
        ResearchClient(None)
    with pytest.raises(AuthError):
        ResearchClient("")


def test_from_env_missing_key_is_auth_error():
    with pytest.raises(AuthError):
        ResearchClient.from_env(ledger_path=None)


def test_key_never_in_exception_chain():
    secret_text = f"boom {KEY}"
    failures = [
        HpsiMcpAPIError(secret_text, status_code=503, response_text=secret_text),
        HpsiMcpConnectionError(secret_text),
        HpsiMcpRateLimitError(secret_text, status_code=429, response_text=secret_text),
    ]
    for failure in failures:
        client, _, _ = make([failure] * 3)
        with pytest.raises((UpstreamError, RateLimited)) as caught:
            client.run("analyze_stock", "TEST")
        assert all(KEY not in t for t in chain_texts(caught.value))
        assert caught.value.__cause__ is None


def _recording_client(handler, tmp_path=None):
    ledger = CreditLedger(None)
    inner = httpx.MockTransport(handler)
    recording = RecordingTransport(ledger, "test", budget=100, call_cap=10, inner=inner)
    return ResearchClient(KEY, transport=recording, sleep=Mock()), ledger


def test_ledger_counts_every_retry_attempt():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "down"}, headers={"X-Credits-Remaining": "5000"})

    client, ledger = _recording_client(handler)
    with pytest.raises(UpstreamError):
        client.run("analyze_stock", "TEST")
    assert ledger.calls("test") == 3


def test_ledger_budget_blocks_retry_and_propagates():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={}, headers={"X-Credits-Remaining": "5000"})

    ledger = CreditLedger(None)
    recording = RecordingTransport(
        ledger, "test", budget=100, call_cap=2, inner=httpx.MockTransport(handler)
    )
    client = ResearchClient(KEY, transport=recording, sleep=Mock())
    with pytest.raises(CreditBudgetExceeded):
        client.run("analyze_stock", "TEST")
    assert ledger.calls("test") == 2


def test_real_sdk_success_through_recording_transport():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/api/credits/"):
            return httpx.Response(200, json={"credits_remaining": 5001})
        assert request.url.path.endswith("/TEST")
        return httpx.Response(
            200,
            json=OK,
            headers={"X-Credits-Remaining": "5000", "X-Credits-Charged": "1"},
        )

    client, ledger = _recording_client(handler)
    assert client.run("analyze_stock", "TEST").data == OK
    assert ledger.calls("test") == 1
