"""Production client: bounded retries, credit accounting and sanitized errors.

Wraps hpsilab-mcp 0.14.2 in credits-only mode. The SDK does not retry, so the
retry loop lives here. Every attempt, retries included, goes through the SDK
and therefore through ``ledger.RecordingTransport`` when one is installed.

Adapter errors are raised ``from None`` with fixed messages and safe attributes
only. SDK messages, response bodies and the API key never enter an adapter error.
"""

from __future__ import annotations

import os
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
from hpsilab_mcp import (
    CREDITS_ONLY,
    HpsiMcpAllowanceExhaustedError,
    HpsiMcpAPIError,
    HpsiMcpAuthError,
    HpsiMcpClient,
    HpsiMcpConfigError,
    HpsiMcpConnectionError,
    HpsiMcpError,
    HpsiMcpInsufficientCreditsError,
    HpsiMcpPaymentError,
    HpsiMcpRateLimitError,
    HpsiMcpResponseError,
    HpsiMcpSettlementUnknownError,
    HpsiMcpTimeoutError,
    HpsiMcpToolError,
)
from hpsilab_mcp.client import DEFAULT_BASE_URL

from hpsilab_research_adapter.errors import (
    AdapterError,
    AuthError,
    CreditBudgetExceeded,
    CreditsExhausted,
    RateLimited,
    Timeout,
    UnsafeConfiguration,
    UpstreamError,
)
from hpsilab_research_adapter.ledger import (
    DEFAULT_LEDGER_PATH,
    CreditLedger,
    RecordingTransport,
    make_template,
)
from hpsilab_research_adapter.policy import (
    BACKOFF_BASE_SECONDS,
    BACKOFF_CAP_SECONDS,
    ENV_API_KEY,
    ENV_X402_WALLET,
    MAX_ATTEMPTS,
    TIMEOUT_ATTEMPTS,
)
from hpsilab_research_adapter.tools import ALLOWED_SDK_METHODS, TOOLS, ToolSpec
from hpsilab_research_adapter.types import Result

_TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")
DEFAULT_MAX_CREDITS = 50  # one full six-tool pass cost 38 credits on 2026-11-22
DEFAULT_CALL_CAP = 150
_TOOL_NAMES = {s.name for s in TOOLS.values()} | {s.sdk_method for s in TOOLS.values()}

# (retryable, max_attempts, builder) decided per SDK exception by _classify.
_Builder = Callable[[str, int], AdapterError]


def _normalize_ticker(ticker: object) -> str:
    cleaned = str(ticker).strip().upper() if isinstance(ticker, str) else ""
    if not _TICKER_RE.fullmatch(cleaned):
        raise ValueError("Ticker must match ^[A-Z][A-Z0-9.\\-]{0,9}$ after upper-casing.")
    return cleaned


def _int_or_none(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _retry_after(exc: BaseException) -> int | None:
    value = getattr(exc, "retry_after_seconds", None)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        return None
    return int(value)


def _classify(exc: HpsiMcpError) -> tuple[int, _Builder] | None:
    """Return (max_attempts, error builder) for a known SDK error, else None.

    Order matters: several classes subclass ``HpsiMcpAPIError``. A ``None`` result
    means "propagate unchanged" (e.g. ``HpsiMcpValidationError``).
    """
    status = _int_or_none(getattr(exc, "status_code", None))

    if isinstance(exc, HpsiMcpRateLimitError):
        retry_after = _retry_after(exc)

        def rate_limited(tool: str, attempts: int) -> AdapterError:
            return RateLimited(
                f"HPSILab rate limit persisted after {attempts} attempt(s).",
                retry_after_seconds=retry_after,
                tool=tool,
                status_code=status or 429,
                attempts=attempts,
            )

        return MAX_ATTEMPTS, rate_limited

    if isinstance(exc, HpsiMcpTimeoutError):
        return TIMEOUT_ATTEMPTS, lambda tool, attempts: Timeout(
            f"HPSILab request timed out after {attempts} attempt(s).",
            tool=tool,
            attempts=attempts,
        )

    if isinstance(exc, HpsiMcpConnectionError):
        return MAX_ATTEMPTS, lambda tool, attempts: UpstreamError(
            f"HPSILab connection failed after {attempts} attempt(s).",
            tool=tool,
            attempts=attempts,
        )

    if isinstance(
        exc,
        (
            HpsiMcpInsufficientCreditsError,
            HpsiMcpAllowanceExhaustedError,
            HpsiMcpPaymentError,
            HpsiMcpSettlementUnknownError,
        ),
    ):
        required = _int_or_none(getattr(exc, "credits_required", None))
        remaining = _int_or_none(getattr(exc, "credits_remaining", None))
        return 1, lambda tool, attempts: CreditsExhausted(
            "HPSILab account cannot pay for this call.",
            credits_required=required,
            credits_remaining=remaining,
            tool=tool,
            status_code=status,
            attempts=attempts,
        )

    if isinstance(exc, (HpsiMcpAuthError, HpsiMcpConfigError)):
        return 1, lambda tool, attempts: AuthError(
            "HPSILab rejected the credentials or the client is not authenticated.",
            tool=tool,
            status_code=status,
            attempts=attempts,
        )

    if isinstance(exc, HpsiMcpAPIError):
        if status is not None and 500 <= status <= 599:
            return MAX_ATTEMPTS, lambda tool, attempts: UpstreamError(
                f"HPSILab server error persisted after {attempts} attempt(s).",
                tool=tool,
                status_code=status,
                attempts=attempts,
            )
        label = "unreadable response" if isinstance(exc, HpsiMcpResponseError) else "request error"
        return 1, lambda tool, attempts: UpstreamError(
            f"HPSILab returned a {label}.",
            tool=tool,
            status_code=status,
            attempts=attempts,
        )

    if isinstance(exc, HpsiMcpToolError):
        return 1, lambda tool, attempts: UpstreamError(
            "HPSILab tool reported a failure.", tool=tool, attempts=attempts
        )

    return None


def _default_normalizer(tool: str, ticker: str, raw: Any) -> Result:
    from hpsilab_research_adapter.normalize import normalize

    return normalize(tool, ticker, raw)


class ResearchClient:
    """Read-only HPSILab research client (six approved tools, credits only)."""

    def __init__(
        self,
        api_key: str | None,
        *,
        request: Callable[[ToolSpec, str], Any] | None = None,
        sleep: Callable[[float], Any] = time.sleep,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 30.0,
        normalizer: Callable[[str, str, Any], Result] | None = None,
    ) -> None:
        if not api_key or not isinstance(api_key, str) or not api_key.strip():
            raise AuthError("HPSILab API key is missing.", attempts=0)
        if os.environ.get(ENV_X402_WALLET):
            raise UnsafeConfiguration(
                f"{ENV_X402_WALLET} is set; refusing to run because the SDK could pay per call."
            )
        self._api_key = api_key
        self._sleep = sleep
        self._normalizer = normalizer or _default_normalizer
        if transport is None and request is None:
            # Library use without from_env still gets an (in-memory) credit guard.
            transport = RecordingTransport(
                CreditLedger(None),
                "library",
                budget=DEFAULT_MAX_CREDITS,
                call_cap=DEFAULT_CALL_CAP,
            )
        self._transport = transport
        self._started = False
        self._sdk = HpsiMcpClient(
            api_key=api_key,
            transport=transport,
            timeout=timeout,
            payment_mode=CREDITS_ONLY,
        )
        if self._sdk.payment_policy.pays:
            self._sdk.close()
            raise UnsafeConfiguration("SDK payment policy allows paying; refusing to run.")
        self._request = request or self._sdk_request

    @classmethod
    def from_env(
        cls,
        *,
        phase: str = "cli",
        ledger_path: Path | None = DEFAULT_LEDGER_PATH,
        max_credits: int = DEFAULT_MAX_CREDITS,
        call_cap: int = DEFAULT_CALL_CAP,
        total_budget: int | None = None,
        min_balance: int | None = None,
    ) -> ResearchClient:
        api_key = os.environ.get(ENV_API_KEY)
        if not api_key or not api_key.strip():
            raise AuthError("HPSILab API key is missing.", attempts=0)
        if os.environ.get(ENV_X402_WALLET):
            raise UnsafeConfiguration(
                f"{ENV_X402_WALLET} is set; refusing to run because the SDK could pay per call."
            )
        ledger = CreditLedger(ledger_path)
        recording = RecordingTransport(
            ledger,
            phase,
            budget=max_credits,
            call_cap=call_cap,
            total_budget=total_budget,
            floor=min_balance,
        )
        return cls(api_key, transport=recording)

    # -- internals --------------------------------------------------------
    def _sdk_request(self, spec: ToolSpec, ticker: str) -> Any:
        if spec.sdk_method not in ALLOWED_SDK_METHODS:  # defence in depth
            raise ValueError("SDK method is not one of the six approved research tools.")
        kwargs: dict[str, Any] = {"include_metadata": True} if spec.supports_metadata else {}
        return getattr(self._sdk, spec.sdk_method)(ticker, **kwargs)

    def _start_once(self) -> None:
        """Once per client: prove credit endpoints free (first use of a ledger), load
        catalog prices, and read a fresh balance (which also clears a blind ledger)."""
        transport = self._transport
        if self._started or not isinstance(transport, RecordingTransport):
            return
        self._started = True
        transport.start(make_template(DEFAULT_BASE_URL, self._api_key), _TOOL_NAMES)
        for spec in TOOLS.values():
            if spec.name in transport.prices:
                transport.prices.setdefault(spec.sdk_method, transport.prices[spec.name])

    def _delay(self, exc: HpsiMcpError, attempt: int) -> float:
        delay = BACKOFF_BASE_SECONDS * 2 ** (attempt - 1)
        if isinstance(exc, HpsiMcpRateLimitError):
            retry_after = _retry_after(exc)
            if retry_after is not None:
                delay = float(retry_after)
        return min(delay, BACKOFF_CAP_SECONDS)

    # -- public API -------------------------------------------------------
    def run(self, tool: str, ticker: str) -> Result:
        spec = TOOLS.get(tool) if isinstance(tool, str) else None
        if spec is None:
            raise ValueError("Unknown tool; choose one of the six approved research tools.")
        symbol = _normalize_ticker(ticker)
        self._start_once()

        attempt = 0
        while True:
            attempt += 1
            if isinstance(self._transport, RecordingTransport):
                self._transport.context = {"tool": spec.sdk_method, "ticker": symbol}
            failure: AdapterError | None = None
            try:
                raw = self._request(spec, symbol)
            except CreditBudgetExceeded:
                raise
            except HpsiMcpError as exc:
                verdict = _classify(exc)
                if verdict is None:
                    raise
                limit, builder = verdict
                if attempt < limit:
                    self._sleep(self._delay(exc, attempt))
                    continue
                failure = builder(spec.name, attempt)
            if failure is not None:
                raise failure from None
            try:
                return self._normalizer(spec.name, symbol, raw)
            except Exception:
                # The call was billed; an unexpected response shape must not crash
                # the caller or leak the body. Report it as an upstream problem.
                raise UpstreamError(
                    "HPSILab response did not match the expected shape.",
                    tool=spec.name,
                    attempts=attempt,
                ) from None

    def close(self) -> None:
        self._sdk.close()

    def __enter__(self) -> ResearchClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


__all__ = ["ResearchClient"]
