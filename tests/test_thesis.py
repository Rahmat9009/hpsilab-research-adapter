"""Thesis evidence rules. Synthetic data only; no network, no real HPSILab values."""

from __future__ import annotations

import json
from typing import Any

import pytest

from hpsilab_research_adapter import errors, thesis, tools
from hpsilab_research_adapter.thesis import (
    DISCLAIMER,
    Thesis,
    evaluate,
    render_markdown,
    to_dict,
)
from hpsilab_research_adapter.types import Result

FORBIDDEN = (
    "buy",
    "sell",
    "entry",
    "exit",
    "stop loss",
    "stop-loss",
    "take profit",
    "take-profit",
    "position",
    "trade signal",
    "recommendation",
)


def res(tool: str, data: dict[str, Any], horizon: str | None = None) -> Result:
    return Result(tool=tool, ticker="TEST", data=data, horizon=horizon)


def ai(prob: Any = 0.7, **extra: Any) -> Result:
    item = {
        "last_date": "2000-01-01",
        "ensemble_up_probability": prob,
        "model_consensus": "synthetic-consensus",
        "suggested_stop_loss_price": 1.0,
        "suggested_take_profit_price": 2.0,
    }
    item.update(extra)
    return res(tools.AI_PREDICTION, {"items": [item]})


def analyze(signal: Any = "Bullish", bull: int = 3, bear: int = 1) -> Result:
    return res(
        tools.ANALYZE_STOCK,
        {
            "signal": signal,
            "bullish_factors": ["b"] * bull,
            "bearish_factors": ["r"] * bear,
            "confidence_score": 50,
        },
    )


def monte(median: float = 110.0, start: float = 100.0, horizon: int | None = 10) -> Result:
    data: dict[str, Any] = {
        "start_price": start,
        "median_price": median,
        "lower_bound": 90.0,
        "upper_bound": 120.0,
        "prob_above": 0.6,
        "prob_below": 0.4,
    }
    if horizon is not None:
        data["horizon_days"] = horizon
    return res(tools.MONTE_CARLO, data, None if horizon is None else str(horizon))


def pretrade(regime: Any = "chop") -> Result:
    return res(
        tools.PRETRADE_RISK_SCAN,
        {"regime": regime, "regimeConfidence": 0.5, "range_90": {"lower": 1.0, "upper": 2.0}},
    )


def option_pressure() -> Result:
    return res(
        tools.OPTION_PRESSURE,
        {"atm_iv": 0.3, "gex_total": 5.0, "weekly_expected_move": 1.5, "days_to_expiry": 4},
    )


def iv_radar() -> Result:
    row = {"iv_rank": 10.0, "iv_percentile": 20.0, "iv_hv_spread": 0.1, "term_structure": "flat"}
    return res(tools.IV_RADAR, {"results": [row]})


def full(**overrides: Any) -> dict[str, Any]:
    results: dict[str, Any] = {
        tools.AI_PREDICTION: ai(),
        tools.ANALYZE_STOCK: analyze(),
        tools.MONTE_CARLO: monte(),
        tools.PRETRADE_RISK_SCAN: pretrade(),
        tools.OPTION_PRESSURE: option_pressure(),
        tools.IV_RADAR: iv_radar(),
    }
    results.update(overrides)
    return results


def stance_of(report: Any, tool: str, field: str) -> str:
    matches = [e for e in report.evidence if e.tool == tool and e.field == field]
    assert len(matches) == 1, (tool, field, report.evidence)
    return matches[0].stance


def run(direction: str, **overrides: Any):
    return evaluate(Thesis("test", direction, 10), full(**overrides))


# -- Thesis validation ----------------------------------------------------


def test_thesis_normalizes_and_validates() -> None:
    t = Thesis(" nvda ", "UP", 10)
    assert (t.ticker, t.direction, t.horizon_days) == ("NVDA", "up", 10)
    for bad in (
        lambda: Thesis("NVDA", "sideways", 10),
        lambda: Thesis("NVDA", "up", 0),
        lambda: Thesis("NVDA", "up", 366),
        lambda: Thesis("NVDA", "up", True),
        lambda: Thesis("NVDA", "up", 5.0),
        lambda: Thesis("1BAD", "up", 5),
        lambda: Thesis("", "up", 5),
    ):
        with pytest.raises(ValueError):
            bad()
    assert Thesis("X", "range", 365).horizon_days == 365
    assert Thesis("X", "range", 1).horizon_days == 1


# -- ai_prediction --------------------------------------------------------


@pytest.mark.parametrize(
    ("prob", "up", "down", "rng"),
    [
        (0.7, "supports", "challenges", "challenges"),
        (0.3, "challenges", "supports", "challenges"),
        (0.5, "neutral", "neutral", "supports"),
        (0.45, "challenges", "supports", "supports"),
        (0.55, "supports", "challenges", "supports"),
        (0.56, "supports", "challenges", "challenges"),
        (0.44, "challenges", "supports", "challenges"),
    ],
)
def test_ai_probability_rule(prob: float, up: str, down: str, rng: str) -> None:
    for direction, expected in (("up", up), ("down", down), ("range", rng)):
        report = run(direction, **{tools.AI_PREDICTION: ai(prob)})
        assert stance_of(report, tools.AI_PREDICTION, "ensemble_up_probability") == expected


def test_ai_uses_latest_item_and_horizon_unstated() -> None:
    items = [
        {"last_date": "2000-01-02", "ensemble_up_probability": 0.9},
        {"last_date": "2000-01-01", "ensemble_up_probability": 0.1},
    ]
    report = run("up", **{tools.AI_PREDICTION: res(tools.AI_PREDICTION, {"items": items})})
    ev = [e for e in report.evidence if e.field == "ensemble_up_probability"][0]
    assert ev.observed == 0.9
    assert ev.horizon_status == "unstated"
    assert ev.source_horizon is None


def test_ai_consensus_is_context_and_price_levels_never_evidence() -> None:
    report = run("up")
    assert stance_of(report, tools.AI_PREDICTION, "model_consensus") == "context"
    fields = {e.field for e in report.evidence}
    assert not any("stop" in f or "take" in f or "suggested" in f for f in fields)
    observed = json.dumps(to_dict(report)["evidence"])
    assert "suggested_stop" not in observed
    assert ("ai_prediction", "suggested_stop_loss_price") in report.excluded
    assert ("ai_prediction", "suggested_take_profit_price") in report.excluded


@pytest.mark.parametrize("bad", ["0.7", True, 1.5, -0.1, float("nan"), [0.7]])
def test_ai_unparseable_probability_goes_to_missing(bad: Any) -> None:
    report = run("up", **{tools.AI_PREDICTION: ai(bad)})
    assert not [e for e in report.evidence if e.field == "ensemble_up_probability"]
    assert any(
        m.field == "ensemble_up_probability" and m.reason == "unparseable" for m in report.missing
    )


# -- analyze_stock --------------------------------------------------------


@pytest.mark.parametrize(
    ("signal", "up", "down", "rng"),
    [
        ("Bullish", "supports", "challenges", "challenges"),
        ("bearish", "challenges", "supports", "challenges"),
        ("Neutral", "neutral", "neutral", "supports"),
        ("BULL_CASE", "supports", "challenges", "challenges"),
    ],
)
def test_signal_word_rule(signal: str, up: str, down: str, rng: str) -> None:
    for direction, expected in (("up", up), ("down", down), ("range", rng)):
        report = run(direction, **{tools.ANALYZE_STOCK: analyze(signal)})
        assert stance_of(report, tools.ANALYZE_STOCK, "signal") == expected


def test_unknown_signal_word_is_unparseable() -> None:
    report = run("up", **{tools.ANALYZE_STOCK: analyze("mystery")})
    assert any(m.field == "signal" and m.reason == "unparseable" for m in report.missing)


@pytest.mark.parametrize(
    ("bull", "bear", "up", "down", "rng"),
    [
        (3, 1, "supports", "challenges", "challenges"),
        (1, 3, "challenges", "supports", "challenges"),
        (2, 2, "neutral", "neutral", "supports"),
    ],
)
def test_factor_count_rule(bull: int, bear: int, up: str, down: str, rng: str) -> None:
    key = "bullish_factors/bearish_factors"
    for direction, expected in (("up", up), ("down", down), ("range", rng)):
        report = run(direction, **{tools.ANALYZE_STOCK: analyze("Neutral", bull, bear)})
        assert stance_of(report, tools.ANALYZE_STOCK, key) == expected


def test_confidence_score_is_context() -> None:
    assert stance_of(run("up"), tools.ANALYZE_STOCK, "confidence_score") == "context"


# -- monte_carlo ----------------------------------------------------------


def test_monte_carlo_up_down() -> None:
    key = "median_price/start_price"
    assert stance_of(run("up"), tools.MONTE_CARLO, key) == "supports"
    assert stance_of(run("down"), tools.MONTE_CARLO, key) == "challenges"
    low = {tools.MONTE_CARLO: monte(median=90.0)}
    assert stance_of(run("up", **low), tools.MONTE_CARLO, key) == "challenges"
    assert stance_of(run("down", **low), tools.MONTE_CARLO, key) == "supports"
    flat = {tools.MONTE_CARLO: monte(median=100.0)}
    assert stance_of(run("up", **flat), tools.MONTE_CARLO, key) == "neutral"


def test_monte_carlo_range_uses_bounds() -> None:
    key = "start_price/lower_bound/upper_bound"
    assert stance_of(run("range"), tools.MONTE_CARLO, key) == "supports"
    outside = {tools.MONTE_CARLO: monte(start=130.0)}
    assert stance_of(run("range", **outside), tools.MONTE_CARLO, key) == "challenges"


def test_monte_carlo_probabilities_are_context() -> None:
    report = run("up")
    assert stance_of(report, tools.MONTE_CARLO, "prob_above") == "context"
    assert stance_of(report, tools.MONTE_CARLO, "prob_below") == "context"


def test_horizon_match_different_unstated() -> None:
    match = run("up")
    mc = [e for e in match.evidence if e.tool == tools.MONTE_CARLO]
    assert mc and all(e.horizon_status == "match" and e.source_horizon == "10" for e in mc)

    different = run("up", **{tools.MONTE_CARLO: monte(horizon=30)})
    mc = [e for e in different.evidence if e.tool == tools.MONTE_CARLO]
    assert mc and all(e.horizon_status == "different" and e.source_horizon == "30" for e in mc)
    assert different.tallies["different_horizon"]["supports"] == 1
    # Different-horizon evidence is shown but not in the matching tally.
    in_match = sum(different.tallies["matching_or_unstated_horizon"].values())
    in_diff = sum(different.tallies["different_horizon"].values())
    assert in_diff == len(mc)
    assert in_match + in_diff == len(different.evidence)

    unstated = run("up", **{tools.MONTE_CARLO: monte(horizon=None)})
    mc = [e for e in unstated.evidence if e.tool == tools.MONTE_CARLO]
    assert mc and all(e.horizon_status == "unstated" and e.source_horizon is None for e in mc)
    others = [e for e in match.evidence if e.tool != tools.MONTE_CARLO]
    assert all(e.horizon_status == "unstated" for e in others)


@pytest.mark.parametrize(
    ("horizon", "status"),
    [
        (10, "match"),
        (10.0, "match"),
        (10.9, "different"),
        ("inf", "different"),
        ("nan", "different"),
        ("1e400", "different"),
        ("ten", "different"),
    ],
)
def test_horizon_must_be_an_exact_whole_day_and_never_crashes(horizon: Any, status: str) -> None:
    report = run("up", **{tools.MONTE_CARLO: monte(horizon=horizon)})
    mc = [e for e in report.evidence if e.tool == tools.MONTE_CARLO]
    assert mc and all(e.horizon_status == status for e in mc)


def test_monte_carlo_unparseable_values_go_to_missing() -> None:
    bad = res(
        tools.MONTE_CARLO, {"start_price": "x", "median_price": 1.0, "horizon_days": 10}, "10"
    )
    report = run("up", **{tools.MONTE_CARLO: bad})
    assert any(m.field == "start_price" and m.reason == "unparseable" for m in report.missing)
    assert not [e for e in report.evidence if e.field == "median_price/start_price"]


# -- pretrade, option_pressure, iv_radar ----------------------------------


def test_regime_without_direction_is_context() -> None:
    report = run("up")
    assert stance_of(report, tools.PRETRADE_RISK_SCAN, "regime") == "context"
    assert stance_of(report, tools.PRETRADE_RISK_SCAN, "regimeConfidence") == "context"
    assert stance_of(report, tools.PRETRADE_RISK_SCAN, "range_90") == "context"


@pytest.mark.parametrize(
    ("regime", "up", "down", "rng"),
    [
        ("bullish_trend", "supports", "challenges", "challenges"),
        ("Bearish", "challenges", "supports", "challenges"),
        ("neutral", "neutral", "neutral", "supports"),
    ],
)
def test_regime_with_direction_maps_like_signal(regime: str, up: str, down: str, rng: str) -> None:
    for direction, expected in (("up", up), ("down", down), ("range", rng)):
        report = run(direction, **{tools.PRETRADE_RISK_SCAN: pretrade(regime)})
        assert stance_of(report, tools.PRETRADE_RISK_SCAN, "regime") == expected


def test_option_and_iv_are_context_only_and_expiry_is_not_a_horizon() -> None:
    for direction in ("up", "down", "range"):
        report = run(direction)
        ctx = [e for e in report.evidence if e.tool in (tools.OPTION_PRESSURE, tools.IV_RADAR)]
        assert ctx
        assert all(e.stance == "context" and e.horizon_status == "unstated" for e in ctx)
        assert not any(e.field == "days_to_expiry" for e in report.evidence)


# -- missing --------------------------------------------------------------


def test_failed_tool_and_none_go_to_missing() -> None:
    report = run(
        "up",
        **{
            tools.MONTE_CARLO: errors.RateLimited("synthetic", tool="monte_carlo"),
            tools.IV_RADAR: None,
            tools.OPTION_PRESSURE: Result(tool="option_pressure", ticker="TEST", error="Timeout"),
        },
    )
    by_tool = {m.tool: m for m in report.missing if m.field is None}
    assert by_tool[tools.MONTE_CARLO].reason == "tool failed"
    assert by_tool[tools.MONTE_CARLO].detail == "RateLimited"
    assert by_tool[tools.IV_RADAR].reason == "tool failed"
    assert by_tool[tools.OPTION_PRESSURE].detail == "Timeout"
    assert not [e for e in report.evidence if e.tool in by_tool]


def test_absent_tool_key_and_missing_field() -> None:
    results = full()
    del results[tools.PRETRADE_RISK_SCAN]
    results[tools.ANALYZE_STOCK] = res(tools.ANALYZE_STOCK, {"signal": "Bullish"})
    report = evaluate(Thesis("TEST", "up", 10), results)
    reasons = {(m.tool, m.field): m.reason for m in report.missing}
    assert reasons[(tools.PRETRADE_RISK_SCAN, None)] == "tool failed"
    assert reasons[(tools.ANALYZE_STOCK, "bullish_factors")] == "field missing"
    assert reasons[(tools.ANALYZE_STOCK, "bearish_factors")] == "field missing"
    assert reasons[(tools.ANALYZE_STOCK, "confidence_score")] == "field missing"
    assert stance_of(report, tools.ANALYZE_STOCK, "signal") == "supports"


def test_empty_results_everything_missing() -> None:
    report = evaluate(Thesis("TEST", "down", 5), {})
    assert not report.evidence
    assert {m.tool for m in report.missing} == set(tools.TOOL_NAMES)


# -- rendering ------------------------------------------------------------


def test_observed_passes_through_unchanged() -> None:
    report = run("up", **{tools.AI_PREDICTION: ai(0.123456789)})
    ev = [e for e in report.evidence if e.field == "ensemble_up_probability"][0]
    assert ev.observed == 0.123456789


@pytest.mark.parametrize("direction", ["up", "down", "range"])
def test_render_has_no_trading_language_and_has_disclaimer(direction: str) -> None:
    report = run(direction)
    text = render_markdown(report)
    assert DISCLAIMER in text
    body = text.replace(DISCLAIMER, "").lower()
    for word in FORBIDDEN:
        assert word not in body, word
    rendered_json = json.dumps(to_dict(report)).replace(DISCLAIMER, "").lower()
    for word in FORBIDDEN:
        assert word not in rendered_json, word


def test_every_rule_text_is_rendered_and_clean() -> None:
    text = render_markdown(run("up"))
    for e in run("up").evidence:
        assert e.rule in text
    for rule in thesis.RULE_TEXT.values():
        low = rule.lower()
        assert not any(word in low for word in FORBIDDEN)


def test_to_dict_is_json_safe_and_complete() -> None:
    weird = {tools.AI_PREDICTION: ai(0.6, model_consensus=object())}
    d = to_dict(run("up", **weird))
    json.dumps(d)
    assert set(d) == {"thesis", "evidence", "missing", "excluded", "tallies", "disclaimer"}
    assert d["thesis"] == {"ticker": "TEST", "direction": "up", "horizon_days": 10}
    assert d["disclaimer"] == DISCLAIMER


def test_markdown_lists_missing_and_excluded() -> None:
    text = render_markdown(evaluate(Thesis("TEST", "up", 10), {tools.AI_PREDICTION: ai()}))
    assert "## Missing" in text and "tool failed" in text
    assert "Deliberately excluded" in text
    assert "suggested_stop_loss_price" in text.split("Deliberately excluded")[1]


# -- entry point ----------------------------------------------------------


class FakeClient:
    def __init__(self, script: dict[str, Exception] | None = None) -> None:
        self.script = script or {}
        self.calls: list[tuple[str, str]] = []
        self.closed = False
        self.results = {k: v for k, v in full().items()}

    def run(self, tool: str, ticker: str) -> Result:
        self.calls.append((tool, ticker))
        if tool in self.script:
            raise self.script[tool]
        return self.results[tool]

    def close(self) -> None:
        self.closed = True


class FakeFactory:
    def __init__(self, client: Any = None, error: Exception | None = None) -> None:
        self.client = client
        self.error = error
        self.kwargs: dict[str, Any] | None = None

    def __call__(self, **kwargs: Any) -> Any:
        self.kwargs = kwargs
        if self.error is not None:
            raise self.error
        return self.client


def test_main_markdown_with_fake_client(capsys: pytest.CaptureFixture[str]) -> None:
    client = FakeClient()
    factory = FakeFactory(client)
    code = thesis.main(
        ["nvda", "--direction", "up", "--horizon", "10", "--max-credits", "40", "--no-ledger"],
        client_factory=factory,
    )
    assert code == 0
    assert client.closed
    assert [t for t, _ in client.calls] == list(tools.TOOL_NAMES)
    assert {tk for _, tk in client.calls} == {"NVDA"}
    assert factory.kwargs is not None
    assert factory.kwargs["max_credits"] == 40
    assert factory.kwargs["ledger_path"] is None
    out = capsys.readouterr().out
    assert "# Thesis evidence: NVDA" in out
    assert DISCLAIMER in out


def test_main_json_and_continue_past_single_failure(
    capsys: pytest.CaptureFixture[str],
) -> None:
    client = FakeClient({tools.IV_RADAR: errors.UpstreamError("synthetic", tool="iv_radar")})
    code = thesis.main(
        ["TEST", "--direction", "range", "--horizon", "7", "--json", "--no-ledger"],
        client_factory=FakeFactory(client),
    )
    captured = capsys.readouterr()
    assert code == 5
    payload = json.loads(captured.out)
    assert any(m["tool"] == "iv_radar" and m["reason"] == "tool failed" for m in payload["missing"])
    assert len(client.calls) == 6
    assert payload["thesis"]["direction"] == "range"


def test_main_auth_failure_exit_code(capsys: pytest.CaptureFixture[str]) -> None:
    factory = FakeFactory(error=errors.AuthError("synthetic key problem", attempts=0))
    code = thesis.main(
        ["TEST", "--direction", "down", "--horizon", "3", "--no-ledger"], client_factory=factory
    )
    assert code == 3
    assert "AuthError" in capsys.readouterr().err


def test_main_credit_stop_marks_remaining_tools_missing(
    capsys: pytest.CaptureFixture[str],
) -> None:
    client = FakeClient({tools.MONTE_CARLO: errors.CreditBudgetExceeded("synthetic")})
    code = thesis.main(
        ["TEST", "--direction", "up", "--horizon", "10", "--json", "--no-ledger"],
        client_factory=FakeFactory(client),
    )
    assert code == 4
    payload = json.loads(capsys.readouterr().out)
    assert client.closed
    missing_tools = {m["tool"] for m in payload["missing"] if m["field"] is None}
    assert tools.MONTE_CARLO in missing_tools


@pytest.mark.parametrize(
    "argv",
    [
        ["TEST", "--direction", "up"],
        ["TEST", "--direction", "sideways", "--horizon", "5"],
        ["TEST", "--direction", "up", "--horizon", "0"],
        ["TEST", "--direction", "up", "--horizon", "400"],
        ["TEST", "--direction", "up", "--horizon", "5", "--no-ledger", "--total-credits", "9"],
    ],
)
def test_main_usage_errors_never_build_a_client(argv: list[str]) -> None:
    def forbidden(**kwargs: Any) -> Any:
        pytest.fail("client factory must not be called on a usage error")

    with pytest.raises(SystemExit) as caught:
        thesis.main(argv, client_factory=forbidden)
    assert caught.value.code == 2
