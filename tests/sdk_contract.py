"""Test-only handoff specification, not an SDK or production client.

Faisal and the test owner must agree this seam before enabling error contracts.
Callbacks adapt the existing client and SDK; they must not implement retry,
normalization, exception translation, authentication, or another fake client.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any
from unittest.mock import Mock


@dataclass(frozen=True)
class SDKContract:
    """Values supplied by a future binding in conftest.py.

    make_invocation(api_key=..., request=Mock, sleep=Mock) returns a zero-argument
    callable that constructs/uses the REAL client and calls one approved research
    method. Construction belongs inside that callable so AuthError is observable.
    request is patched into the lowest SDK request seam, beneath retry logic;
    caches must be disabled by the binding. sleep replaces the actual backoff seam.

    make_failure(kind, synthetic_credential) creates a REAL SDK/transport failure,
    not an adapter exception. Supported kinds: rate_limit, credits, timeout, auth,
    server_500, server_502, server_503, server_504.
    Include the supplied synthetic credential in the upstream message/metadata.
    errors maps the required public exception names to the REAL exception classes.
    success_response and expected_result require documented shapes, all synthetic.
    timeout_attempts is an agreed policy of 1, 2 or 3, not inferred from the run.
    None api_key must force the missing-key path without environment fallbacks.
    """

    make_invocation: Callable[..., Callable[[], Any]]
    make_failure: Callable[[str, str], Exception]
    errors: Mapping[str, type[Exception]]
    success_response: Any
    expected_result: Any
    timeout_attempts: int


def prepare(contract: SDKContract, failures: list[object], api_key: str | None):
    """Create mocks only; all adapter behavior must come from the actual client."""
    request = Mock(name="sdk_request", side_effect=failures)
    sleep = Mock(name="backoff_sleep")
    invoke = contract.make_invocation(api_key=api_key, request=request, sleep=sleep)
    return invoke, request, sleep
