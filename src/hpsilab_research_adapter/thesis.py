"""Thesis evidence: judge normalized research results against a thesis the USER states.

Research only. The user supplies the ticker, the direction (up, down or range) and
the horizon in days. This module never chooses a thesis, never produces a verdict
and never gives advice. It applies a few documented, deterministic rules to the
six normalized results and reports, per rule, whether the observed value supports,
challenges, is neutral to, or is only context for the stated thesis. Anything
absent, failed or of an unexpected type is listed under ``missing``, never guessed.

Pure functions: no I/O and no network. Only ``main`` (the module entry point)
talks to a client, and it does so through the same factory the CLI uses.
Independent, unverified third-party integration; not an official HPSILab product.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hpsilab_research_adapter import errors, tools
from hpsilab_research_adapter.policy import MAX_ATTEMPTS
from hpsilab_research_adapter.types import Result

DIRECTIONS = ("up", "down", "range")
STANCES = ("supports", "challenges", "neutral", "context")
HORIZON_STATUSES = ("match", "different", "unstated")

REASON_TOOL_FAILED = "tool failed"
REASON_FIELD_MISSING = "field missing"
REASON_UNPARSEABLE = "unparseable"

DISCLAIMER = (
    "Research only. This is not a recommendation and has not been verified by HPSILab. "
    "It applies fixed, documented rules to third-party research output and does not "
    "predict or advise."
)

# The two suggested price-level fields of ai_prediction are never read.
EXCLUDED_FIELDS: tuple[tuple[str, str], ...] = (
    (tools.AI_PREDICTION, "suggested_stop_loss_price"),
    (tools.AI_PREDICTION, "suggested_take_profit_price"),
)

RANGE_LOW = 0.45
RANGE_HIGH = 0.55

_TICKER_RE = re.compile(r"[A-Z][A-Z0-9.\-]{0,9}")

RULE_TEXT: dict[str, str] = {
    "ai_probability": (
        "Latest ai_prediction item (greatest last_date, else last in list), field "
        "ensemble_up_probability (0-1). up: above 0.5 supports, below 0.5 challenges. "
        "down: the inverse. range: from 0.45 to 0.55 inclusive supports, otherwise "
        "challenges. Exactly 0.5 is neutral for up and down. Horizon unstated."
    ),
    "ai_consensus": "model_consensus of the latest ai_prediction item, shown as context only.",
    "signal_word": (
        "analyze_stock signal word: a word starting with bull is bullish, bear is bearish, "
        "neutral is neutral. up: bullish supports, bearish challenges, neutral is neutral. "
        "down: the inverse. range: neutral supports, bullish or bearish challenges. "
        "Any other word is unparseable. Horizon unstated."
    ),
    "factor_count": (
        "analyze_stock count of bullish_factors versus bearish_factors. up: more bullish "
        "supports, more bearish challenges, equal is neutral. down: the inverse. range: "
        "equal counts support, unequal counts challenge. Horizon unstated."
    ),
    "confidence_score": "analyze_stock confidence_score, shown as context only.",
    "mc_median": (
        "monte_carlo median_price versus start_price. up: median above start supports, "
        "below challenges, equal is neutral. down: the inverse. range: start_price inside "
        "[lower_bound, upper_bound] supports, outside challenges. This range rule is weak "
        "because a central interval usually contains the start price. The horizon is the "
        "response's horizon_days; evidence for a different horizon is shown but tallied "
        "separately."
    ),
    "mc_probability": (
        "monte_carlo prob_above and prob_below (0-1), shown as context only. Same horizon "
        "handling as the median rule."
    ),
    "regime_word": (
        "pretrade_risk_scan regime: a word starting with bull or bear maps like the "
        "analyze_stock signal word, neutral is neutral, any other word carries no direction "
        "and is context only. Horizon unstated."
    ),
    "regime_confidence": "pretrade_risk_scan regimeConfidence, shown as context only.",
    "range_90": "pretrade_risk_scan range_90 (lower and upper), shown as context only.",
    "option_context": (
        "option_pressure fields are volatility and options-market context only and carry "
        "no direction. days_to_expiry is not treated as a horizon."
    ),
    "iv_context": (
        "iv_radar fields are volatility context only and carry no direction. Its regime "
        "label is a skew description, not a stance."
    ),
}


# -- dataclasses ----------------------------------------------------------


@dataclass(frozen=True)
class Thesis:
    """The user's stated thesis. Nothing here is ever chosen by this module."""

    ticker: str
    direction: str
    horizon_days: int

    def __post_init__(self) -> None:
        ticker = self.ticker.strip().upper() if isinstance(self.ticker, str) else ""
        if not _TICKER_RE.fullmatch(ticker):
            raise ValueError("ticker must match [A-Z][A-Z0-9.-]{0,9} after upper-casing")
        direction = self.direction.strip().lower() if isinstance(self.direction, str) else ""
        if direction not in DIRECTIONS:
            raise ValueError("direction must be one of: up, down, range")
        days = self.horizon_days
        if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 365:
            raise ValueError("horizon_days must be an integer from 1 to 365")
        object.__setattr__(self, "ticker", ticker)
        object.__setattr__(self, "direction", direction)


@dataclass(frozen=True)
class Evidence:
    tool: str
    field: str
    observed: Any
    stance: str
    rule: str
    source_horizon: str | None
    horizon_status: str


@dataclass(frozen=True)
class MissingItem:
    tool: str
    field: str | None
    reason: str
    detail: str | None = None


@dataclass(frozen=True)
class ThesisReport:
    thesis: Thesis
    evidence: tuple[Evidence, ...] = ()
    missing: tuple[MissingItem, ...] = ()
    excluded: tuple[tuple[str, str], ...] = EXCLUDED_FIELDS
    disclaimer: str = DISCLAIMER
    tallies: dict[str, dict[str, int]] = field(default_factory=dict)


# -- helpers --------------------------------------------------------------


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value == value


def _is_prob(value: object) -> bool:
    return _is_number(value) and 0 <= value <= 1  # type: ignore[operator]


def _word_class(value: object) -> str | None:
    """bullish / bearish / neutral from a category word, else None."""
    if not isinstance(value, str):
        return None
    word = value.strip().lower()
    if word.startswith("bull"):
        return "bullish"
    if word.startswith("bear"):
        return "bearish"
    if word.startswith("neutral"):
        return "neutral"
    return None


def _directional(direction: str, up_signal: str | None) -> str:
    """Stance for a word class or a three-way comparison result.

    up_signal is one of "up", "down", "flat" (what the observation points to).
    """
    if up_signal == "flat":
        return "supports" if direction == "range" else "neutral"
    if direction == "range":
        return "challenges"
    if direction == up_signal:
        return "supports"
    return "challenges"


def _word_stance(direction: str, word_class: str) -> str:
    mapping = {"bullish": "up", "bearish": "down", "neutral": "flat"}
    return _directional(direction, mapping[word_class])


def _compare_stance(direction: str, left: float, right: float) -> str:
    if left > right:
        return _directional(direction, "up")
    if left < right:
        return _directional(direction, "down")
    return _directional(direction, "flat")


class _Collector:
    def __init__(self, thesis: Thesis) -> None:
        self.thesis = thesis
        self.evidence: list[Evidence] = []
        self.missing: list[MissingItem] = []

    def add(
        self,
        tool: str,
        field_name: str,
        observed: Any,
        stance: str,
        rule_key: str,
        source_horizon: str | None = None,
        horizon_status: str = "unstated",
    ) -> None:
        self.evidence.append(
            Evidence(
                tool=tool,
                field=field_name,
                observed=observed,
                stance=stance,
                rule=RULE_TEXT[rule_key],
                source_horizon=source_horizon,
                horizon_status=horizon_status,
            )
        )

    def miss(
        self, tool: str, field_name: str | None, reason: str, detail: str | None = None
    ) -> None:
        self.missing.append(MissingItem(tool, field_name, reason, detail))

    def get(self, tool: str, data: Mapping[str, Any], key: str) -> Any:
        """Value for key, or None after recording a field-missing entry."""
        value = data.get(key)
        if value is None:
            self.miss(tool, key, REASON_FIELD_MISSING)
        return value


def _horizon_status(thesis: Thesis, source: str | None) -> str:
    if source is None:
        return "unstated"
    try:
        value = float(source)
    except (TypeError, ValueError, OverflowError):
        return "different"
    # Only an exact whole-day horizon equal to the thesis horizon counts as a match;
    # 10.9 is not 10, and inf/nan never match.
    if not value.is_integer():
        return "different"
    return "match" if int(value) == thesis.horizon_days else "different"


# -- per-tool rules -------------------------------------------------------


def _latest_item(items: Any) -> Mapping[str, Any] | None:
    if not isinstance(items, list) or not items:
        return None
    rows = [item for item in items if isinstance(item, Mapping)]
    if len(rows) != len(items):
        return None
    if all(isinstance(row.get("last_date"), str) for row in rows):
        return max(rows, key=lambda row: row["last_date"])
    return rows[-1]


def _rule_ai_prediction(c: _Collector, result: Result) -> None:
    tool = tools.AI_PREDICTION
    latest = _latest_item(result.data.get("items"))
    if latest is None:
        c.miss(tool, "items", REASON_FIELD_MISSING)
        return
    prob = c.get(tool, latest, "ensemble_up_probability")
    if prob is not None:
        if not _is_prob(prob):
            c.miss(tool, "ensemble_up_probability", REASON_UNPARSEABLE, "expected a number 0-1")
        else:
            direction = c.thesis.direction
            if direction == "range":
                stance = "supports" if RANGE_LOW <= prob <= RANGE_HIGH else "challenges"
            else:
                stance = _compare_stance(direction, prob, 0.5)
            c.add(tool, "ensemble_up_probability", prob, stance, "ai_probability")
    consensus = c.get(tool, latest, "model_consensus")
    if consensus is not None:
        c.add(tool, "model_consensus", consensus, "context", "ai_consensus")


def _rule_analyze_stock(c: _Collector, result: Result) -> None:
    tool = tools.ANALYZE_STOCK
    data = result.data
    signal = c.get(tool, data, "signal")
    if signal is not None:
        word_class = _word_class(signal)
        if word_class is None:
            c.miss(tool, "signal", REASON_UNPARSEABLE, "unrecognised signal word")
        else:
            c.add(
                tool, "signal", signal, _word_stance(c.thesis.direction, word_class), "signal_word"
            )

    bull = c.get(tool, data, "bullish_factors")
    bear = c.get(tool, data, "bearish_factors")
    if bull is not None and bear is not None:
        if not isinstance(bull, list) or not isinstance(bear, list):
            c.miss(tool, "bullish_factors", REASON_UNPARSEABLE, "expected lists")
        else:
            observed = {"bullish_factors": len(bull), "bearish_factors": len(bear)}
            direction = c.thesis.direction
            if direction == "range":
                stance = "supports" if len(bull) == len(bear) else "challenges"
            else:
                stance = _compare_stance(direction, len(bull), len(bear))
            c.add(tool, "bullish_factors/bearish_factors", observed, stance, "factor_count")

    score = c.get(tool, data, "confidence_score")
    if score is not None:
        if _is_number(score):
            c.add(tool, "confidence_score", score, "context", "confidence_score")
        else:
            c.miss(tool, "confidence_score", REASON_UNPARSEABLE, "expected a number")


def _rule_monte_carlo(c: _Collector, result: Result) -> None:
    tool = tools.MONTE_CARLO
    data = result.data
    source = result.horizon
    if source is None and data.get("horizon_days") is not None:
        source = str(data["horizon_days"])
    status = _horizon_status(c.thesis, source)
    start = c.get(tool, data, "start_price")
    start_ok = start is not None and _is_number(start)
    if start is not None and not start_ok:
        c.miss(tool, "start_price", REASON_UNPARSEABLE, "expected a number")

    if c.thesis.direction == "range":
        low = c.get(tool, data, "lower_bound")
        high = c.get(tool, data, "upper_bound")
        if start_ok and low is not None and high is not None:
            if not (_is_number(low) and _is_number(high)):
                c.miss(tool, "lower_bound", REASON_UNPARSEABLE, "expected numbers")
            else:
                stance = "supports" if low <= start <= high else "challenges"
                observed = {"start_price": start, "lower_bound": low, "upper_bound": high}
                c.add(
                    tool,
                    "start_price/lower_bound/upper_bound",
                    observed,
                    stance,
                    "mc_median",
                    source,
                    status,
                )
    else:
        median = c.get(tool, data, "median_price")
        if start_ok and median is not None:
            if not _is_number(median):
                c.miss(tool, "median_price", REASON_UNPARSEABLE, "expected a number")
            else:
                stance = _compare_stance(c.thesis.direction, median, start)
                observed = {"median_price": median, "start_price": start}
                c.add(
                    tool, "median_price/start_price", observed, stance, "mc_median", source, status
                )

    for key in ("prob_above", "prob_below"):
        prob = c.get(tool, data, key)
        if prob is None:
            continue
        if _is_prob(prob):
            c.add(tool, key, prob, "context", "mc_probability", source, status)
        else:
            c.miss(tool, key, REASON_UNPARSEABLE, "expected a number 0-1")


def _rule_pretrade(c: _Collector, result: Result) -> None:
    tool = tools.PRETRADE_RISK_SCAN
    data = result.data
    regime = c.get(tool, data, "regime")
    if regime is not None:
        if not isinstance(regime, str):
            c.miss(tool, "regime", REASON_UNPARSEABLE, "expected a word")
        else:
            word_class = _word_class(regime)
            stance = (
                "context" if word_class is None else _word_stance(c.thesis.direction, word_class)
            )
            c.add(tool, "regime", regime, stance, "regime_word")
    confidence = c.get(tool, data, "regimeConfidence")
    if confidence is not None:
        if _is_number(confidence):
            c.add(tool, "regimeConfidence", confidence, "context", "regime_confidence")
        else:
            c.miss(tool, "regimeConfidence", REASON_UNPARSEABLE, "expected a number")
    span = c.get(tool, data, "range_90")
    if span is not None:
        if (
            isinstance(span, Mapping)
            and _is_number(span.get("lower"))
            and _is_number(span.get("upper"))
        ):
            c.add(tool, "range_90", dict(span), "context", "range_90")
        else:
            c.miss(tool, "range_90", REASON_UNPARSEABLE, "expected lower and upper numbers")


def _context_fields(
    c: _Collector,
    tool: str,
    data: Mapping[str, Any],
    keys: Sequence[tuple[str, type | tuple[type, ...]]],
    rule_key: str,
) -> None:
    for key, kind in keys:
        value = c.get(tool, data, key)
        if value is None:
            continue
        good = (
            _is_number(value)
            if kind is float
            else isinstance(value, kind) and not isinstance(value, bool)
        )
        if good:
            c.add(tool, key, value, "context", rule_key)
        else:
            c.miss(tool, key, REASON_UNPARSEABLE, "unexpected type")


def _rule_option_pressure(c: _Collector, result: Result) -> None:
    keys: tuple[tuple[str, type | tuple[type, ...]], ...] = (
        ("atm_iv", float),
        ("gex_total", float),
        ("weekly_expected_move", float),
    )
    _context_fields(c, tools.OPTION_PRESSURE, result.data, keys, "option_context")


def _rule_iv_radar(c: _Collector, result: Result) -> None:
    tool = tools.IV_RADAR
    rows = result.data.get("results")
    if not isinstance(rows, list) or not rows or not isinstance(rows[0], Mapping):
        c.miss(tool, "results", REASON_FIELD_MISSING)
        return
    keys: tuple[tuple[str, type | tuple[type, ...]], ...] = (
        ("iv_rank", float),
        ("iv_percentile", float),
        ("iv_hv_spread", float),
        ("term_structure", str),
    )
    _context_fields(c, tool, rows[0], keys, "iv_context")


_RULES: dict[str, Callable[[_Collector, Result], None]] = {
    tools.AI_PREDICTION: _rule_ai_prediction,
    tools.ANALYZE_STOCK: _rule_analyze_stock,
    tools.MONTE_CARLO: _rule_monte_carlo,
    tools.PRETRADE_RISK_SCAN: _rule_pretrade,
    tools.OPTION_PRESSURE: _rule_option_pressure,
    tools.IV_RADAR: _rule_iv_radar,
}


# -- evaluate -------------------------------------------------------------


def _tally(evidence: Sequence[Evidence]) -> dict[str, dict[str, int]]:
    tallies = {
        "matching_or_unstated_horizon": dict.fromkeys(STANCES, 0),
        "different_horizon": dict.fromkeys(STANCES, 0),
    }
    for item in evidence:
        bucket = (
            "different_horizon"
            if item.horizon_status == "different"
            else ("matching_or_unstated_horizon")
        )
        tallies[bucket][item.stance] += 1
    return tallies


def evaluate(thesis: Thesis, results: Mapping[str, Result | Exception | None]) -> ThesisReport:
    """Apply the documented rules to the results, for the user's thesis only."""
    collector = _Collector(thesis)
    for tool in tools.TOOL_NAMES:
        outcome = results.get(tool)
        if outcome is None:
            collector.miss(tool, None, REASON_TOOL_FAILED, "no result")
            continue
        if isinstance(outcome, Exception):
            collector.miss(tool, None, REASON_TOOL_FAILED, type(outcome).__name__)
            continue
        if not isinstance(outcome, Result):
            collector.miss(tool, None, REASON_UNPARSEABLE, "not a Result")
            continue
        if not outcome.ok:
            collector.miss(tool, None, REASON_TOOL_FAILED, outcome.error)
            continue
        _RULES[tool](collector, outcome)
    return ThesisReport(
        thesis=thesis,
        evidence=tuple(collector.evidence),
        missing=tuple(collector.missing),
        tallies=_tally(collector.evidence),
    )


# -- rendering ------------------------------------------------------------


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, float) and value != value:
        return None
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return str(value)


def to_dict(report: ThesisReport) -> dict[str, Any]:
    return {
        "thesis": {
            "ticker": report.thesis.ticker,
            "direction": report.thesis.direction,
            "horizon_days": report.thesis.horizon_days,
        },
        "evidence": [
            {
                "tool": e.tool,
                "field": e.field,
                "observed": _jsonable(e.observed),
                "stance": e.stance,
                "rule": e.rule,
                "source_horizon": e.source_horizon,
                "horizon_status": e.horizon_status,
            }
            for e in report.evidence
        ],
        "missing": [
            {"tool": m.tool, "field": m.field, "reason": m.reason, "detail": m.detail}
            for m in report.missing
        ],
        "excluded": [{"tool": t, "field": f} for t, f in report.excluded],
        "tallies": _jsonable(report.tallies),
        "disclaimer": report.disclaimer,
    }


def render_markdown(report: ThesisReport) -> str:
    t = report.thesis
    lines = [
        f"# Thesis evidence: {t.ticker}",
        "",
        f"Stated by the user: direction **{t.direction}**, horizon **{t.horizon_days}** days.",
        "",
        f"> {report.disclaimer}",
        "",
        "## Tallies",
        "",
        "| Horizon | " + " | ".join(STANCES) + " |",
        "|---|" + "---|" * len(STANCES),
    ]
    for bucket, label in (
        ("matching_or_unstated_horizon", "matching or unstated"),
        ("different_horizon", "different"),
    ):
        counts = report.tallies.get(bucket, {})
        lines.append(f"| {label} | " + " | ".join(str(counts.get(s, 0)) for s in STANCES) + " |")
    lines += ["", "## Evidence", ""]
    if not report.evidence:
        lines.append("No evidence could be evaluated.")
    for e in report.evidence:
        horizon = e.source_horizon if e.source_horizon is not None else "unstated"
        observed = json.dumps(_jsonable(e.observed), sort_keys=True)
        lines += [
            f"- **{e.tool}** `{e.field}` = {observed}",
            f"  - stance: {e.stance}; horizon: {horizon} ({e.horizon_status})",
            f"  - rule: {e.rule}",
        ]
    lines += ["", "## Missing", ""]
    if not report.missing:
        lines.append("Nothing missing.")
    for m in report.missing:
        target = m.tool if m.field is None else f"{m.tool} `{m.field}`"
        detail = f" ({m.detail})" if m.detail else ""
        lines.append(f"- {target}: {m.reason}{detail}")
    lines += ["", "## Deliberately excluded", ""]
    for tool, name in report.excluded:
        lines.append(f"- {tool} `{name}`: never read or shown by this module")
    lines.append("")
    return "\n".join(lines)


# -- entry point ----------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    from hpsilab_research_adapter import cli

    parser = argparse.ArgumentParser(
        prog="python -m hpsilab_research_adapter.thesis",
        description=(
            "Judge research evidence against a thesis YOU state. Research only; "
            "not a recommendation and not verified by HPSILab."
        ),
    )
    parser.add_argument("ticker", type=cli._ticker, metavar="TICKER")
    parser.add_argument("--direction", required=True, choices=DIRECTIONS)
    parser.add_argument("--horizon", required=True, type=int, metavar="DAYS")
    parser.add_argument("--json", action="store_true", help="print JSON, not Markdown")
    parser.add_argument(
        "--max-credits", type=cli._non_negative_int, default=cli.DEFAULT_MAX_CREDITS, metavar="N"
    )
    parser.add_argument("--min-balance", type=cli._non_negative_int, default=None, metavar="N")
    parser.add_argument("--total-credits", type=cli._non_negative_int, default=None, metavar="N")
    ledger = parser.add_mutually_exclusive_group()
    ledger.add_argument("--ledger", default=cli.DEFAULT_LEDGER, metavar="PATH")
    ledger.add_argument("--no-ledger", action="store_true")
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    client_factory: Callable[..., Any] | None = None,
) -> int:
    """Run the six tools once, then print the thesis evidence for the stated thesis."""
    from hpsilab_research_adapter import cli

    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        thesis = Thesis(args.ticker, args.direction, args.horizon)
    except ValueError as exc:
        parser.error(str(exc))
    if args.no_ledger and args.total_credits is not None:
        parser.error(
            "--total-credits needs the persisted ledger; it cannot be used with --no-ledger"
        )

    ledger_path = None if args.no_ledger else Path(args.ledger)
    factory = client_factory if client_factory is not None else cli._load_client_factory()
    results: dict[str, Result | Exception | None] = {}
    failed_calls = 0
    stopping: errors.AdapterError | None = None
    try:
        run_phase = f"thesis-{datetime.now(UTC):%Y%m%dT%H%M%S}-{id(args) % 100000}"
        client = factory(
            phase=run_phase,
            ledger_path=ledger_path,
            max_credits=args.max_credits,
            call_cap=len(tools.TOOL_NAMES) * MAX_ATTEMPTS,
            total_budget=args.total_credits,
            min_balance=args.min_balance,
        )
        try:
            for tool in tools.TOOL_NAMES:
                try:
                    results[tool] = client.run(tool, thesis.ticker)
                except cli._PER_CALL_ERRORS as exc:
                    failed_calls += 1
                    results[tool] = exc
                    print(
                        f"error: {type(exc).__name__}: {exc} ({thesis.ticker} {tool})",
                        file=sys.stderr,
                    )
        finally:
            client.close()
    except errors.AdapterError as exc:
        stopping = exc
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        for tool in tools.TOOL_NAMES:
            results.setdefault(tool, exc)

    report = evaluate(thesis, results)
    if args.json:
        print(json.dumps(to_dict(report), indent=2))
    else:
        print(render_markdown(report))
    if stopping is not None:
        return cli._exit_code_for(stopping)
    return cli.EXIT_UPSTREAM if failed_calls else cli.EXIT_OK


__all__ = [
    "DISCLAIMER",
    "Evidence",
    "MissingItem",
    "Thesis",
    "ThesisReport",
    "evaluate",
    "main",
    "render_markdown",
    "to_dict",
]

if __name__ == "__main__":
    sys.exit(main())
