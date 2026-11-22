"""Public adapter exceptions. FROZEN CONTRACT (Phase 1): do not edit in later phases.

Five required errors, from tests/README.md and tests/test_errors.py:
``AuthError``, ``RateLimited``, ``CreditsExhausted``, ``Timeout``, ``UpstreamError``.
Two adapter-local guards are added: ``CreditBudgetExceeded`` (our own spend cap,
raised before any request) and ``UnsafeConfiguration`` (refuse to run when the
environment could make the SDK pay real money).

Mapping from hpsilab-mcp 0.14.2 (``hpsilab_mcp.__all__``), applied in client.py:

    HpsiMcpRateLimitError             -> RateLimited        retryable
    HpsiMcpTimeoutError               -> Timeout            policy: TIMEOUT_ATTEMPTS
    HpsiMcpConnectionError            -> UpstreamError      retryable
    HpsiMcpAPIError, status 5xx       -> UpstreamError      retryable
    HpsiMcpAPIError, other status     -> UpstreamError      not retried
    HpsiMcpResponseError              -> UpstreamError      not retried
    HpsiMcpToolError                  -> UpstreamError      not retried
    HpsiMcpInsufficientCreditsError   -> CreditsExhausted   not retried
    HpsiMcpAllowanceExhaustedError    -> CreditsExhausted   not retried
    HpsiMcpPaymentError               -> CreditsExhausted   not retried (never pay)
    HpsiMcpSettlementUnknownError     -> CreditsExhausted   not retried (never pay twice)
    HpsiMcpAuthError                  -> AuthError          not retried
    HpsiMcpConfigError                -> AuthError          not retried (SDK auth breaker)
    HpsiMcpValidationError, other     -> propagate unchanged, not retried

Sanitization rule: adapter errors are raised ``from None`` and carry only safe,
structured attributes. They must never embed a credential, the SDK message text,
or response bodies, because tests walk ``__cause__``/``__context__`` for leaks.
"""

from __future__ import annotations


class AdapterError(Exception):
    """Base class for every error this adapter raises on purpose."""

    retryable: bool = False

    def __init__(
        self,
        message: str,
        *,
        tool: str | None = None,
        status_code: int | None = None,
        attempts: int | None = None,
    ) -> None:
        super().__init__(message)
        self.tool = tool
        self.status_code = status_code
        self.attempts = attempts


class AuthError(AdapterError):
    """No HPSILAB_API_KEY, or HPSILab rejected it (401/403). Never retried."""


class RateLimited(AdapterError):
    """HTTP 429 persisted after the bounded retries."""

    retryable = True

    def __init__(self, message: str, *, retry_after_seconds: int | None = None, **kw) -> None:
        super().__init__(message, **kw)
        self.retry_after_seconds = retry_after_seconds


class CreditsExhausted(AdapterError):
    """The HPSILab account cannot pay for the call. Never retried, never paid by wallet."""

    def __init__(
        self,
        message: str,
        *,
        credits_required: int | None = None,
        credits_remaining: int | None = None,
        **kw,
    ) -> None:
        super().__init__(message, **kw)
        self.credits_required = credits_required
        self.credits_remaining = credits_remaining


class Timeout(AdapterError):  # noqa: A001 - name fixed by the test contract
    """The request timed out on every allowed attempt."""

    retryable = True


class UpstreamError(AdapterError):
    """HPSILab answered with a server error, a bad response, or the connection failed."""


class CreditBudgetExceeded(AdapterError):
    """Our local credit budget or balance floor would be crossed. Raised before sending."""

    def __init__(
        self,
        message: str,
        *,
        spent: int | None = None,
        budget: int | None = None,
        balance: int | None = None,
        floor: int | None = None,
        **kw,
    ) -> None:
        super().__init__(message, **kw)
        self.spent = spent
        self.budget = budget
        self.balance = balance
        self.floor = floor


class UnsafeConfiguration(AdapterError):
    """The environment could let the SDK pay per call (x402 wallet). Refuse to start."""


__all__ = [
    "AdapterError",
    "AuthError",
    "CreditBudgetExceeded",
    "CreditsExhausted",
    "RateLimited",
    "Timeout",
    "UnsafeConfiguration",
    "UpstreamError",
]
