"""SDK error contracts; explicitly blocked until the real implementation exists."""

import time
from unittest.mock import Mock

import pytest
from sdk_contract import SDKContract, prepare

pytestmark = pytest.mark.sdk_contract
SYNTHETIC_CREDENTIAL = "test-only-credential-not-valid"


@pytest.fixture(autouse=True)
def reject_real_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden_sleep(*args: object, **kwargs: object) -> None:
        pytest.fail("Real sleep is forbidden; bind the SDK backoff seam to the sleep mock")

    monkeypatch.setattr(time, "sleep", forbidden_sleep)


def assert_sanitized(error: Exception) -> None:
    """Check user-visible strings and the exception chain without printing secrets."""
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if SYNTHETIC_CREDENTIAL in str(current) or SYNTHETIC_CREDENTIAL in repr(current):
            pytest.fail("Exception chain contains the synthetic credential", pytrace=False)
        current = current.__cause__ or (
            None if current.__suppress_context__ else current.__context__
        )


def test_rate_limit_once_then_success(sdk_contract: SDKContract) -> None:
    failure = sdk_contract.make_failure("rate_limit", SYNTHETIC_CREDENTIAL)
    invoke, request, sleep = prepare(
        sdk_contract, [failure, sdk_contract.success_response], SYNTHETIC_CREDENTIAL
    )
    assert invoke() == sdk_contract.expected_result
    assert request.call_count == 2
    assert sleep.call_count == 1


def test_rate_limit_three_times_stops_after_two_retries(sdk_contract: SDKContract) -> None:
    failures = [sdk_contract.make_failure("rate_limit", SYNTHETIC_CREDENTIAL) for _ in range(3)]
    invoke, request, sleep = prepare(sdk_contract, failures, SYNTHETIC_CREDENTIAL)
    with pytest.raises(sdk_contract.errors["RateLimited"]) as caught:
        invoke()
    assert request.call_count == 3
    assert sleep.call_count == 2
    assert_sanitized(caught.value)


@pytest.mark.parametrize(
    ("kind", "exception_name"),
    [("credits", "CreditsExhausted"), ("auth", "AuthError")],
)
def test_nonretryable_failure_is_immediate(
    sdk_contract: SDKContract, kind: str, exception_name: str
) -> None:
    failure = sdk_contract.make_failure(kind, SYNTHETIC_CREDENTIAL)
    invoke, request, sleep = prepare(sdk_contract, [failure], SYNTHETIC_CREDENTIAL)
    with pytest.raises(sdk_contract.errors[exception_name]) as caught:
        invoke()
    request.assert_called_once()
    sleep.assert_not_called()
    assert_sanitized(caught.value)


def test_timeout_uses_agreed_bounded_policy(sdk_contract: SDKContract) -> None:
    attempts = sdk_contract.timeout_attempts
    assert type(attempts) is int and 1 <= attempts <= 3, "Agree the timeout policy first"
    failures = [sdk_contract.make_failure("timeout", SYNTHETIC_CREDENTIAL) for _ in range(3)]
    invoke, request, sleep = prepare(sdk_contract, failures, SYNTHETIC_CREDENTIAL)
    with pytest.raises(sdk_contract.errors["Timeout"]) as caught:
        invoke()
    assert request.call_count == attempts
    assert sleep.call_count == attempts - 1
    assert_sanitized(caught.value)


@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_repeated_server_error_stops_after_two_retries(
    sdk_contract: SDKContract, status: int
) -> None:
    failures = [
        sdk_contract.make_failure(f"server_{status}", SYNTHETIC_CREDENTIAL) for _ in range(3)
    ]
    invoke, request, sleep = prepare(sdk_contract, failures, SYNTHETIC_CREDENTIAL)
    with pytest.raises(sdk_contract.errors["UpstreamError"]) as caught:
        invoke()
    assert request.call_count == 3
    assert sleep.call_count == 2
    assert_sanitized(caught.value)


def test_missing_api_key_never_requests_or_retries(sdk_contract: SDKContract) -> None:
    invoke, request, sleep = prepare(sdk_contract, [], api_key=None)
    with pytest.raises(sdk_contract.errors["AuthError"]) as caught:
        invoke()
    request.assert_not_called()
    sleep.assert_not_called()
    assert_sanitized(caught.value)


def test_unexpected_error_is_not_retried(sdk_contract: SDKContract) -> None:
    failure = ValueError("synthetic local validation failure")
    invoke, request, sleep = prepare(sdk_contract, [failure], SYNTHETIC_CREDENTIAL)
    with pytest.raises(ValueError) as caught:
        invoke()
    assert caught.value is failure
    request.assert_called_once()
    sleep.assert_not_called()


def test_retry_backoff_occurs_between_requests(sdk_contract: SDKContract) -> None:
    """Assert backoff ordering, without inventing the backoff delay formula."""
    failures = [
        sdk_contract.make_failure("rate_limit", SYNTHETIC_CREDENTIAL),
        sdk_contract.make_failure("rate_limit", SYNTHETIC_CREDENTIAL),
        sdk_contract.success_response,
    ]
    invoke, request, sleep = prepare(sdk_contract, failures, SYNTHETIC_CREDENTIAL)
    sequence = Mock()
    sequence.attach_mock(request, "request")
    sequence.attach_mock(sleep, "sleep")
    assert invoke() == sdk_contract.expected_result
    assert [entry[0] for entry in sequence.mock_calls] == [
        "request",
        "sleep",
        "request",
        "sleep",
        "request",
    ]
    assert len(sequence.mock_calls) == 5
    assert request.call_count == 3
    assert sleep.call_count == 2
