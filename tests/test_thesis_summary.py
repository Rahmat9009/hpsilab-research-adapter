"""Share-safe thesis summary. Synthetic data only; no network, no real HPSILab values."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

from hpsilab_research_adapter import errors, thesis, tools
from hpsilab_research_adapter.types import Result

TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools"


def _load(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, TOOLS_DIR / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


summary = _load("thesis_summary")

SENTINEL_NUMBER = 123.456789
SENTINEL_SMALL = 0.123456789
SENTINEL_TEXT = "SENTINELVALUE"
SENTINEL_DATE = "1999-12-31"
SENTINELS = (
    "123.456789",
    "0.123456789",
    "SENTINELVALUE",
    "SENTINELREGIME",
    "SENTINELSHAPE",
    "1999-12-31",
    "246.913578",
)


def _res(tool: str, data: dict[str, Any], horizon: str | None = None) -> Result:
    return Result(tool=tool, ticker="TEST", data=data, horizon=horizon)


def _results() -> dict[str, Any]:
    return {
        tools.AI_PREDICTION: _res(
            tools.AI_PREDICTION,
            {
                "items": [
                    {
                        "last_date": SENTINEL_DATE,
                        "ensemble_up_probability": SENTINEL_SMALL,
                        "model_consensus": SENTINEL_TEXT,
                        "suggested_stop_loss_price": SENTINEL_NUMBER,
                        "suggested_take_profit_price": SENTINEL_NUMBER,
                    }
                ]
            },
        ),
        tools.ANALYZE_STOCK: _res(
            tools.ANALYZE_STOCK,
            {
                "signal": "Bullish SENTINELVALUE",
                "bullish_factors": [SENTINEL_TEXT] * 2,
                "bearish_factors": [SENTINEL_TEXT],
                "confidence_score": SENTINEL_NUMBER,
            },
        ),
        tools.MONTE_CARLO: _res(
            tools.MONTE_CARLO,
            {
                "start_price": SENTINEL_NUMBER,
                "median_price": SENTINEL_NUMBER * 2,
                "lower_bound": SENTINEL_NUMBER,
                "upper_bound": SENTINEL_NUMBER,
                "prob_above": SENTINEL_SMALL,
                "prob_below": SENTINEL_SMALL,
                "horizon_days": 5,
            },
            "5",
        ),
        tools.PRETRADE_RISK_SCAN: _res(
            tools.PRETRADE_RISK_SCAN,
            {
                "regime": "SENTINELREGIME",
                "regimeConfidence": SENTINEL_SMALL,
                "range_90": {"lower": SENTINEL_NUMBER, "upper": SENTINEL_NUMBER},
            },
        ),
        tools.OPTION_PRESSURE: _res(
            tools.OPTION_PRESSURE,
            {
                "atm_iv": SENTINEL_SMALL,
                "gex_total": SENTINEL_NUMBER,
                "weekly_expected_move": SENTINEL_NUMBER,
            },
        ),
        tools.IV_RADAR: errors.UpstreamError("SENTINELVALUE should never be shown"),
    }


def _report_dict(**extra: Any) -> dict[str, Any]:
    report = thesis.evaluate(thesis.Thesis("test", "up", 10), _results())
    payload = thesis.to_dict(report)
    payload.update(extra)
    # Round trip through JSON, exactly as the report file is read.
    return json.loads(json.dumps(payload))


def test_sentinel_values_never_appear() -> None:
    raw = json.dumps(_report_dict())
    assert "123.456789" in raw and "SENTINELVALUE" in raw  # the fixture really carries them
    text = summary.summarize(_report_dict())
    for sentinel in SENTINELS:
        assert sentinel not in text
    assert "SENTINEL" not in text


def test_sentinel_in_free_text_slots_is_dropped() -> None:
    report = _report_dict()
    report["evidence"][0]["rule"] = "SENTINELVALUE as a rule"
    report["evidence"][0]["field"] = "SENTINELVALUE 123.456789"
    report["evidence"][0]["source_horizon"] = "SENTINELVALUE"
    report["missing"][0]["detail"] = "SENTINELVALUE 123.456789"
    report["missing"][0]["reason"] = "SENTINELVALUE"
    report["disclaimer"] = "SENTINELVALUE"
    text = summary.summarize(report)
    assert "SENTINEL" not in text and "123.456789" not in text
    assert thesis.DISCLAIMER in text


def test_summary_content() -> None:
    text = summary.summarize(_report_dict(credits_used=38))
    assert "# Thesis evidence summary: TEST" in text
    assert "direction **up**, horizon **10** days" in text
    assert thesis.DISCLAIMER in text
    assert "- iv_radar: failed (UpstreamError)" in text
    assert "- analyze_stock: succeeded" in text
    assert "5 of 6 tools succeeded." in text
    assert "Credits used for this run: 38" in text
    assert "**analyze_stock** `signal`" in text
    assert "stance: supports; horizon status: unstated" in text
    assert "horizon status: different" in text  # monte_carlo ran at 5 days against 10
    assert "- iv_radar: tool failed (UpstreamError)" in text
    assert thesis.RULE_TEXT["signal_word"] in text
    assert "| matching or unstated |" in text and "| different |" in text
    # suggested price-level fields are never read, so they never show up
    assert "suggested_" not in text


def test_tallies_match_report() -> None:
    report = _report_dict()
    text = summary.summarize(report)
    for bucket, label in (
        ("matching_or_unstated_horizon", "matching or unstated"),
        ("different_horizon", "different"),
    ):
        row = (
            "| "
            + label
            + " | "
            + " | ".join(str(report["tallies"][bucket][s]) for s in thesis.STANCES)
            + " |"
        )
        assert row in text


def test_credits_line_is_optional_and_validated() -> None:
    assert "Credits used" not in summary.summarize(_report_dict())
    assert "Credits used" not in summary.summarize(_report_dict(credits_used="SENTINELVALUE"))
    assert "Credits used" not in summary.summarize(_report_dict(credits_used=True))
    assert "Credits used" not in summary.summarize(_report_dict(credits_used=-1))


def test_missing_field_is_listed_with_reason() -> None:
    results = _results()
    results[tools.ANALYZE_STOCK] = _res(tools.ANALYZE_STOCK, {"signal": "Bullish"})
    report = thesis.to_dict(thesis.evaluate(thesis.Thesis("test", "up", 10), results))
    text = summary.summarize(json.loads(json.dumps(report)))
    assert "- analyze_stock `bullish_factors`: field missing" in text
    assert "- analyze_stock: succeeded" in text


def test_empty_report_renders() -> None:
    report = {"thesis": {"ticker": "TEST", "direction": "down", "horizon_days": 3}}
    text = summary.summarize(report)
    assert "No evidence could be evaluated." in text
    assert "Nothing missing." in text
    assert "6 of 6 tools succeeded." in text


@pytest.mark.parametrize(
    "bad",
    [
        None,
        [],
        {},
        {"thesis": "x"},
        {"thesis": {"ticker": "TEST", "direction": "sideways", "horizon_days": 5}},
        {"thesis": {"ticker": "TEST", "direction": "up", "horizon_days": "5"}},
        {"thesis": {"ticker": "bad ticker", "direction": "up", "horizon_days": 5}},
    ],
)
def test_unusable_report_is_rejected(bad: Any) -> None:
    with pytest.raises(ValueError):
        summary.summarize(bad)


def test_main_reads_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "report.json"
    path.write_text(json.dumps(_report_dict()), encoding="utf-8")
    assert summary.main([str(path)]) == 0
    out = capsys.readouterr().out
    assert "# Thesis evidence summary: TEST" in out
    assert "SENTINEL" not in out


def test_main_errors_are_quiet(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("not json SENTINELVALUE", encoding="utf-8")
    assert summary.main([str(bad)]) == 2
    assert summary.main([str(tmp_path / "missing.json")]) == 2
    assert summary.main([]) == 2
    captured = capsys.readouterr()
    assert "SENTINEL" not in captured.out + captured.err


# -- thesis_demo --ledger -------------------------------------------------

demo = _load("thesis_demo")


def test_demo_parse_ledger_option(tmp_path: Path) -> None:
    ledger = tmp_path / "l.json"
    assert demo._parse(["down", "7", "--ledger", str(ledger)]) == (["down", "7"], ledger)
    assert demo._parse(["--ledger", str(ledger)]) == ([], ledger)
    assert demo._parse([]) == ([], demo.LEDGER)
    assert demo.LEDGER == demo.ROOT / ".credits" / "ledger.json"


def test_demo_limits_unchanged() -> None:
    assert (demo.MAX_CREDITS, demo.TOTAL_BUDGET, demo.MIN_BALANCE) == (40, 190, 1800)


def test_demo_refuses_before_any_request_with_unreadable_ledger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    ledger = tmp_path / "ledger.json"
    ledger.write_text("{ damaged", encoding="utf-8")

    def boom(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("a client must not be created")

    monkeypatch.setattr(demo.ResearchClient, "from_env", boom)
    assert demo.main(["up", "10", "--ledger", str(ledger)]) == 3
    assert "REFUSED" in capsys.readouterr().out
    assert ledger.read_text(encoding="utf-8") == "{ damaged"


def test_demo_refuses_when_budget_below_one_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    ledger = tmp_path / "ledger.json"
    ledger.write_text(json.dumps({"entries": []}), encoding="utf-8")
    monkeypatch.setattr(demo, "TOTAL_BUDGET", 0)

    def boom(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("a client must not be created")

    monkeypatch.setattr(demo.ResearchClient, "from_env", boom)
    assert demo.main(["--ledger", str(ledger)]) == 4
    assert "REFUSED" in capsys.readouterr().out


def test_demo_bad_arguments_refuse(capsys: pytest.CaptureFixture[str]) -> None:
    assert demo.main(["sideways"]) == 2
    assert demo.main(["up", "abc"]) == 2
    assert demo.main(["up", "10", "extra"]) == 2
    assert demo.main(["--ledger"]) == 2
    assert capsys.readouterr().out.count("REFUSED") == 4
