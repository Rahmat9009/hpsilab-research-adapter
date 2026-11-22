"""CLI behaviour against a fake client factory. No network; the real client is never imported."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest

from hpsilab_research_adapter import __version__, errors, tools
from hpsilab_research_adapter.cli import main
from hpsilab_research_adapter.policy import MAX_ATTEMPTS
from hpsilab_research_adapter.types import Result

SECRET = "fake-key-for-tests-0001"
ALL_TOOLS = tools.TOOL_NAMES
RESULT_FIELDS = {field.name for field in dataclasses.fields(Result)}


def fabricated_result(tool: str, ticker: str) -> Result:
    return Result(
        tool=tool,
        ticker=ticker,
        data={"fabricated_metric": 0.0, "fabricated_label": f"{tool}-{ticker}"},
        horizon="fabricated-horizon",
        source_fields=("fabricated_label", "fabricated_metric"),
        missing_fields=("fabricated_missing",),
    )


class FakeClient:
    def __init__(self, script: dict[tuple[str, str], Exception] | None = None) -> None:
        self.script: dict[tuple[str, str], Exception] = script or {}
        self.calls: list[tuple[str, str]] = []
        self.closed = False

    def run(self, tool: str, ticker: str) -> Result:
        self.calls.append((tool, ticker))
        outcome = self.script.get((tool, ticker))
        if outcome is not None:
            raise outcome
        return fabricated_result(tool, ticker)

    def close(self) -> None:
        self.closed = True


class FakeFactory:
    def __init__(self, client: FakeClient) -> None:
        self.client = client
        self.kwargs: dict[str, Any] | None = None

    def __call__(self, **kwargs: Any) -> FakeClient:
        self.kwargs = kwargs
        return self.client


def forbidden_factory(**kwargs: Any) -> Any:
    pytest.fail("client factory must not be called for this command")


@pytest.fixture
def client() -> FakeClient:
    return FakeClient()


@pytest.fixture
def factory(client: FakeClient) -> FakeFactory:
    return FakeFactory(client)


def test_help_states_research_and_read_only_boundary(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as caught:
        main(["--help"], client_factory=forbidden_factory)
    assert caught.value.code == 0
    out = capsys.readouterr().out
    assert "research-only" in out
    assert "read-only" in out
    assert "never generates, approves, submits or executes orders" in out
    assert "not an official or endorsed HPSILab product" in out


def test_no_arguments_prints_help_and_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([], client_factory=forbidden_factory) == 0
    assert "usage: hpsilab" in capsys.readouterr().out


def test_version_prints_package_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as caught:
        main(["--version"], client_factory=forbidden_factory)
    assert caught.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_status_lists_tools_and_reports_key_presence_only(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HPSILAB_API_KEY", SECRET)
    assert main(["--status"], client_factory=forbidden_factory) == 0
    captured = capsys.readouterr()
    for name in ALL_TOOLS:
        assert name in captured.out
    assert "research-only" in captured.out
    assert "HPSILAB_API_KEY set: yes" in captured.out
    assert "SDK version (hpsilab-mcp):" in captured.out
    assert SECRET not in captured.out
    assert SECRET not in captured.err


def test_status_reports_missing_key(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--status"], client_factory=forbidden_factory) == 0
    assert "HPSILAB_API_KEY set: no" in capsys.readouterr().out


def test_single_tool_text_output(
    capsys: pytest.CaptureFixture[str], factory: FakeFactory, client: FakeClient
) -> None:
    assert main(["nvda", "--tool", "analyze_stock"], client_factory=factory) == 0
    out = capsys.readouterr().out
    assert client.calls == [("analyze_stock", "NVDA")]
    assert client.closed
    assert "== analyze_stock NVDA ==" in out
    assert "source_fields: 2" in out
    assert "missing_fields: fabricated_missing" in out
    assert '"fabricated_label": "analyze_stock-NVDA"' in out


def test_tool_all_calls_every_tool_once(factory: FakeFactory, client: FakeClient) -> None:
    assert main(["NVDA", "--tool", "all"], client_factory=factory) == 0
    assert [tool for tool, _ in client.calls] == list(ALL_TOOLS)
    assert all(ticker == "NVDA" for _, ticker in client.calls)


def test_json_output_is_array_of_result_dicts(
    capsys: pytest.CaptureFixture[str], factory: FakeFactory
) -> None:
    assert main(["NVDA", "--json"], client_factory=factory) == 0
    rows = json.loads(capsys.readouterr().out)
    assert isinstance(rows, list)
    assert len(rows) == len(ALL_TOOLS)
    for row in rows:
        assert set(row) == RESULT_FIELDS
    assert rows[0]["ticker"] == "NVDA"


def test_multiple_tickers_run_in_order(factory: FakeFactory, client: FakeClient) -> None:
    assert main(["nvda", "msft", "--tool", "iv_radar"], client_factory=factory) == 0
    assert client.calls == [("iv_radar", "NVDA"), ("iv_radar", "MSFT")]


def test_duplicate_tickers_run_once(factory: FakeFactory, client: FakeClient) -> None:
    assert main(["nvda", "NVDA", "--tool", "iv_radar"], client_factory=factory) == 0
    assert client.calls == [("iv_radar", "NVDA")]


@pytest.mark.parametrize("ticker", ["1ABC", "BAD!", "A" * 11, "-X", "NV DA"])
def test_invalid_ticker_exits_2(ticker: str, factory: FakeFactory, client: FakeClient) -> None:
    with pytest.raises(SystemExit) as caught:
        main([ticker], client_factory=factory)
    assert caught.value.code == 2
    assert client.calls == []
    assert factory.kwargs is None


@pytest.mark.parametrize("tool", ["generate_report", "submit", "ALL"])
def test_invalid_tool_exits_2(tool: str, factory: FakeFactory) -> None:
    with pytest.raises(SystemExit) as caught:
        main(["NVDA", "--tool", tool], client_factory=factory)
    assert caught.value.code == 2
    assert factory.kwargs is None


@pytest.mark.parametrize(
    ("error_cls", "exit_code"),
    [
        (errors.AuthError, 3),
        (errors.UnsafeConfiguration, 3),
        (errors.CreditsExhausted, 4),
        (errors.CreditBudgetExceeded, 4),
        (errors.RateLimited, 5),
        (errors.Timeout, 5),
        (errors.UpstreamError, 5),
    ],
)
def test_adapter_errors_map_to_exit_codes(
    capsys: pytest.CaptureFixture[str],
    error_cls: type[errors.AdapterError],
    exit_code: int,
) -> None:
    client = FakeClient({("analyze_stock", "NVDA"): error_cls("fabricated failure")})
    rc = main(["NVDA", "--tool", "analyze_stock"], client_factory=FakeFactory(client))
    assert rc == exit_code
    assert capsys.readouterr().err == f"error: {error_cls.__name__}: fabricated failure\n"


def test_missing_key_raised_by_factory_exits_3(capsys: pytest.CaptureFixture[str]) -> None:
    def factory(**kwargs: Any) -> Any:
        raise errors.AuthError("HPSILAB_API_KEY is not set")

    assert main(["NVDA"], client_factory=factory) == 3
    assert "error: AuthError: HPSILAB_API_KEY is not set" in capsys.readouterr().err


def test_partial_results_printed_before_error(capsys: pytest.CaptureFixture[str]) -> None:
    client = FakeClient({("ai_prediction", "NVDA"): errors.RateLimited("fabricated limit")})
    rc = main(["NVDA"], client_factory=FakeFactory(client))
    assert rc == 5
    assert client.calls == [("analyze_stock", "NVDA"), ("ai_prediction", "NVDA")]
    assert client.closed
    captured = capsys.readouterr()
    assert "== analyze_stock NVDA ==" in captured.out
    assert "== ai_prediction" not in captured.out
    assert captured.err == "error: RateLimited: fabricated limit\n"


def test_partial_results_in_json_before_error(capsys: pytest.CaptureFixture[str]) -> None:
    client = FakeClient({("ai_prediction", "NVDA"): errors.Timeout("fabricated timeout")})
    rc = main(["NVDA", "--json"], client_factory=FakeFactory(client))
    assert rc == 5
    rows = json.loads(capsys.readouterr().out)
    assert [row["tool"] for row in rows] == ["analyze_stock"]


def test_unexpected_exception_propagates() -> None:
    client = FakeClient({("analyze_stock", "NVDA"): RuntimeError("fabricated bug")})
    with pytest.raises(RuntimeError, match="fabricated bug"):
        main(["NVDA", "--tool", "analyze_stock"], client_factory=FakeFactory(client))


def test_flags_pass_through_to_factory(factory: FakeFactory) -> None:
    rc = main(
        [
            "nvda",
            "--tool",
            "iv_radar",
            "--max-credits",
            "7",
            "--min-balance",
            "1900",
            "--total-credits",
            "40",
            "--ledger",
            "custom/ledger.json",
        ],
        client_factory=factory,
    )
    assert rc == 0
    assert factory.kwargs.pop("phase").startswith("cli-")
    assert factory.kwargs == {
        "ledger_path": Path("custom/ledger.json"),
        "max_credits": 7,
        "call_cap": 1 * MAX_ATTEMPTS,
        "total_budget": 40,
        "min_balance": 1900,
    }


def test_default_flags_reach_factory(factory: FakeFactory) -> None:
    assert main(["NVDA"], client_factory=factory) == 0
    assert factory.kwargs.pop("phase").startswith("cli-")
    assert factory.kwargs == {
        "ledger_path": Path(".credits/ledger.json"),
        "max_credits": 20,
        "call_cap": len(ALL_TOOLS) * MAX_ATTEMPTS,
        "total_budget": None,
        "min_balance": None,
    }


def test_no_ledger_passes_none(factory: FakeFactory) -> None:
    assert main(["NVDA", "--no-ledger"], client_factory=factory) == 0
    assert factory.kwargs is not None
    assert factory.kwargs["ledger_path"] is None


def test_ledger_and_no_ledger_are_mutually_exclusive(factory: FakeFactory) -> None:
    with pytest.raises(SystemExit) as caught:
        main(["NVDA", "--ledger", "x.json", "--no-ledger"], client_factory=factory)
    assert caught.value.code == 2
    assert factory.kwargs is None
