"""Response normalizer: a consistent envelope plus field accounting.

Values are passed through unchanged. Nothing is rounded, renamed, defaulted or
reinterpreted. This module does no I/O.

EXPECTED_FIELDS were derived from the hpsilab-mcp 0.14.2 probe of 2026-11-22
(schemas/<tool>.shape.json: the top-level keys of ``data`` that are not listed in
``optional_keys``; no shape listed any optional keys). For ai_prediction the shape
is an array of objects, so its expected fields are the keys of one item.

Horizon key per tool (never inferred, defaulted or computed):
    analyze_stock       none in shape
    ai_prediction       none in shape
    iv_radar            none in shape
    option_pressure     none in shape (days_to_expiry is an expiry distance, not a horizon)
    pretrade_risk_scan  none in shape at top level (horizonDays is nested under
                        methodology, so it is not read)
    monte_carlo         horizon_days

ai_prediction: ``get_ai_prediction`` returns a McpToolResult whose ``.data`` is a
list of prediction objects. A list cannot be spread into top-level keys, so it is
kept unchanged under the single key ``"items"``; source_fields are the union of
the item keys, and a field is reported missing if any item lacks it.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from typing import Any

from hpsilab_research_adapter.tools import (
    AI_PREDICTION,
    ANALYZE_STOCK,
    IV_RADAR,
    MONTE_CARLO,
    OPTION_PRESSURE,
    PRETRADE_RISK_SCAN,
    TOOL_NAMES,
)
from hpsilab_research_adapter.types import Result

EXPECTED_FIELDS: dict[str, frozenset[str]] = {
    ANALYZE_STOCK: frozenset(
        {
            "symbol",
            "status",
            "successfulTools",
            "failedTools",
            "warnings",
            "signal",
            "confidence_score",
            "confidence_score_meaning",
            "options_coverage",
            "bullish_factors",
            "bearish_factors",
            "summary",
            "disclaimer",
            "tool_responses",
        }
    ),
    AI_PREDICTION: frozenset(
        {
            "last_date",
            "model_variant",
            "last_close",
            "ensemble_up_probability",
            "rf_up_probability",
            "lr_up_probability",
            "daily_vol_est",
            "suggested_stop_loss_price",
            "suggested_take_profit_price",
            "sentiment_score",
            "basis",
            "model_name",
            "computed_at",
            "latest_history_date",
            "latest_history_close",
            "input_reference_status",
            "model_consensus",
            "sentiment_source",
        }
    ),
    IV_RADAR: frozenset({"status", "count", "results"}),
    OPTION_PRESSURE: frozenset(
        {
            "status",
            "symbol",
            "spot",
            "expiry",
            "days_to_expiry",
            "max_pain",
            "gamma_wall",
            "gamma_wall_net",
            "call_wall",
            "call_wall_gex",
            "put_wall",
            "put_wall_gex",
            "gex_total",
            "atm_iv",
            "expected_high",
            "squeeze_price",
            "expiry_low",
            "expiry_high",
            "weekly_expected_move",
            "avg_iv",
            "avg_call_iv",
            "avg_put_iv",
            "total_oi",
            "total_volume",
            "calls_count",
            "puts_count",
            "open_interest_source",
            "open_interest_as_of",
            "quotes_as_of",
        }
    ),
    PRETRADE_RISK_SCAN: frozenset(
        {
            "symbol",
            "asOf",
            "riskDeltas",
            "regime",
            "regimeConfidence",
            "distribution",
            "range_90",
            "mean",
            "threshold",
            "sizingChecks",
            "exposure",
            "correlation",
            "methodology",
        }
    ),
    MONTE_CARLO: frozenset(
        {
            "ticker",
            "horizon_days",
            "data_as_of",
            "start_price",
            "support",
            "threshold",
            "resistance",
            "prob_below",
            "prob_above",
            "mean_price",
            "median_price",
            "lower_bound",
            "upper_bound",
            "volatility",
            "std_tomorrow",
            "ci",
            "final_prices",
            "distribution",
            "msg",
        }
    ),
}

# Top-level horizon key per tool; tools absent here have none in shape.
_HORIZON_KEYS: dict[str, str] = {MONTE_CARLO: "horizon_days"}

_METADATA_KEY = "_metadata"
_LIST_KEY = "items"


def _plain(value: Any) -> Any:
    """Convert a metadata object to a plain dict where it is not one already."""
    if isinstance(value, Mapping):
        return dict(value)
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        return dump()
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return dataclasses.asdict(value)
    if hasattr(value, "__dict__"):
        return dict(vars(value))
    return value


def _unwrap(raw: Any) -> tuple[Any, Any]:
    """Return (payload, metadata) from a raw response."""
    if raw is None:
        return {}, None
    if hasattr(raw, "data") and hasattr(raw, "metadata"):
        payload = raw.data
        return ({} if payload is None else payload), raw.metadata
    return raw, None


def normalize(tool: str, ticker: str, raw: Any) -> Result:
    """Wrap one raw tool response in the common Result envelope."""
    if tool not in TOOL_NAMES:
        raise ValueError(f"unknown tool: {tool!r}")
    if not isinstance(ticker, str):
        raise ValueError("ticker must be a string")

    wrapped = raw is not None and hasattr(raw, "data") and hasattr(raw, "metadata")
    payload, metadata = _unwrap(raw)
    if isinstance(payload, Mapping):
        data: dict[str, Any] = dict(payload)
        keys = set(data)
        common = keys
    elif isinstance(payload, list) and wrapped:
        if not all(isinstance(item, Mapping) for item in payload):
            raise ValueError("list response items must be objects")
        data = {_LIST_KEY: payload} if payload else {}
        keys = {key for item in payload for key in item}
        # A field is missing if ANY record lacks it; source_fields stays the union.
        common = set.intersection(*(set(item) for item in payload)) if payload else set()
    else:
        raise ValueError(f"unsupported raw response type: {type(raw).__name__}")

    if metadata is not None:
        data[_METADATA_KEY] = _plain(metadata)

    keys.discard(_METADATA_KEY)
    common = common - {_METADATA_KEY}
    horizon = None
    horizon_key = _HORIZON_KEYS.get(tool)
    if horizon_key is not None and isinstance(payload, Mapping):
        value = payload.get(horizon_key)
        horizon = None if value is None else str(value)

    return Result(
        tool=tool,
        ticker=ticker.strip().upper(),
        data=data,
        horizon=horizon,
        source_fields=tuple(sorted(keys)),
        missing_fields=tuple(sorted(EXPECTED_FIELDS[tool] - common)),
        error=None,
    )


__all__ = ["EXPECTED_FIELDS", "normalize"]
