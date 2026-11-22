"""Adversarial regression tests for the credit ledger and RecordingTransport.

Each test drives a real ``ResearchClient`` (real hpsilab_mcp SDK) through a
``RecordingTransport`` whose inner transport is an ``httpx.MockTransport`` that
plays HPSILab: ``/api/credits/balance``, ``/api/credits/catalog`` and tool paths.
Behaviour is asserted, not docstrings. Offline only.
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import Callable
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest

from hpsilab_research_adapter.client import DEFAULT_CALL_CAP, DEFAULT_MAX_CREDITS, ResearchClient
from hpsilab_research_adapter.errors import (
    AdapterError,
    CreditBudgetExceeded,
    Timeout,
)
from hpsilab_research_adapter.ledger import (
    BALANCE_PATH,
    CATALOG_PATH,
    UNKNOWN_PRICE_RESERVE,
    CreditLedger,
    RecordingTransport,
    parse_balance,
    parse_catalog,
    parse_catalog_paths,
    price_for_path,
)

KEY = "test-only-credential-not-valid"
OK = {"symbol": "TEST", "score": 1}
PHASE = "p"
META = f"{PHASE}:meta"


def resp(
    status: int = 200,
    *,
    charged: str | None = None,
    remaining: str | None = None,
    body: object = OK,
) -> httpx.Response:
    headers = {}
    if charged is not None:
        headers["X-Credits-Charged"] = charged
    if remaining is not None:
        headers["X-Credits-Remaining"] = remaining
    return httpx.Response(status, json=body, headers=headers)


class Fake:
    """A mocked HPSILab. ``tool`` is called with (fake, request) for every tool path."""

    def __init__(
        self,
        *,
        balance: int = 1000,
        catalog: object = None,
        tool: Callable[[Fake, httpx.Request], httpx.Response] | None = None,
    ) -> None:
        self.balance = balance
        self.catalog = {"tools": []} if catalog is None else catalog
        self.tool = tool or (lambda fake, request: resp())
        self.balance_fails: str | None = None  # None | "500" | "raise"
        self.drift = 0  # balance decrease applied after every balance read
        self.credit_hits: list[str] = []
        self.tool_hits: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == BALANCE_PATH:
            self.credit_hits.append(path)
            if self.balance_fails == "raise":
                raise httpx.ConnectError("balance down", request=request)
            if self.balance_fails == "500":
                return httpx.Response(500, json={})
            current = self.balance
            self.balance -= self.drift
            return httpx.Response(200, json={"credits_remaining": current})
        if path == CATALOG_PATH:
            self.credit_hits.append(path)
            return httpx.Response(200, json=self.catalog)
        self.tool_hits.append(path)
        return self.tool(self, request)


def make(
    fake: Fake,
    *,
    ledger: CreditLedger | None = None,
    phase: str = PHASE,
    budget: int = 100,
    call_cap: int = 10,
    total_budget: int | None = None,
    floor: int | None = None,
) -> tuple[ResearchClient, CreditLedger, RecordingTransport]:
    ledger = ledger if ledger is not None else CreditLedger(None)
    transport = RecordingTransport(
        ledger,
        phase,
        budget=budget,
        call_cap=call_cap,
        total_budget=total_budget,
        floor=floor,
        inner=httpx.MockTransport(fake.handler),
    )
    return ResearchClient(KEY, transport=transport, sleep=Mock()), ledger, transport


def tool_entries(ledger: CreditLedger, phase: str = PHASE):
    return [e for e in ledger.entries if e.phase == phase]


def meta_entries(ledger: CreditLedger, phase: str = PHASE):
    return [e for e in ledger.entries if e.phase == f"{phase}:meta"]


# ---------------------------------------------------------------- F-1 / F-1b
def test_f1_unlisted_tool_refused_before_sending_when_reserve_exceeds_budget():
    fake = Fake()
    client, ledger, _ = make(fake, budget=5)
    with pytest.raises(CreditBudgetExceeded):
        client.run("analyze_stock", "TEST")
    assert UNKNOWN_PRICE_RESERVE > 5
    assert fake.tool_hits == []
    assert tool_entries(ledger) == []


def test_f1_catalog_price_allows_call_within_budget():
    fake = Fake(
        catalog={"tools": [{"tool": "analyze_stock", "credits": 3}]},
        tool=lambda f, r: resp(charged="3", remaining="997"),
    )
    client, ledger, _ = make(fake, budget=5)
    assert client.run("analyze_stock", "TEST").data == OK
    assert len(fake.tool_hits) == 1
    assert ledger.spent(PHASE) == 3


def test_f1_observed_history_cost_refuses_under_small_budget():
    fake = Fake()
    ledger = CreditLedger(None)
    ledger.record(
        "earlier",
        tool="analyze_stock",
        ticker="TEST",
        status=200,
        balance_after=990,
        charged=10,
        balance_before=1000,
    )
    client, ledger, _ = make(fake, ledger=ledger, budget=5)
    with pytest.raises(CreditBudgetExceeded):
        client.run("analyze_stock", "TEST")
    assert fake.tool_hits == []


@pytest.mark.parametrize(
    "catalog",
    [
        {"tools": [{"tool": "analyze_stock", "credits": 12}]},
        {"analyze_stock": 12},
    ],
    ids=["list-of-objects", "mapping"],
)
def test_f1b_catalog_forms_parse_and_feed_authorize(catalog):
    assert parse_catalog(catalog, {"analyze_stock"}) == {"analyze_stock": 12}

    # budget 11 < price 12: refused before sending.
    fake = Fake(catalog=catalog)
    client, _, transport = make(fake, budget=11)
    with pytest.raises(CreditBudgetExceeded):
        client.run("analyze_stock", "TEST")
    assert transport.prices.get("analyze_stock") == 12
    assert fake.tool_hits == []

    # budget 12 == price 12: allowed.
    fake = Fake(catalog=catalog, tool=lambda f, r: resp(charged="12", remaining="988"))
    client, ledger, _ = make(fake, budget=12)
    assert client.run("analyze_stock", "TEST").data == OK
    assert ledger.spent(PHASE) == 12


# ---------------------------------------------------------------------- F-2
def test_f2_floor_with_unknown_balance_refuses_before_any_tool_request():
    fake = Fake()
    fake.balance_fails = "500"
    client, ledger, _ = make(fake, floor=1800)
    with pytest.raises(CreditBudgetExceeded):
        client.run("analyze_stock", "TEST")
    assert fake.tool_hits == []
    assert tool_entries(ledger) == []


def test_f2_floor_with_balance_endpoint_raising_refuses():
    fake = Fake()
    fake.balance_fails = "raise"
    client, _, _ = make(fake, floor=1800)
    with pytest.raises(CreditBudgetExceeded):
        client.run("analyze_stock", "TEST")
    assert fake.tool_hits == []


# ---------------------------------------------------------------------- F-3
def _timeout_tool(drop: int = 0, balance_down: bool = False):
    def tool(fake: Fake, request: httpx.Request) -> httpx.Response:
        fake.balance -= drop
        if balance_down:
            fake.balance_fails = "raise"
        raise httpx.ReadTimeout("slow", request=request)

    return tool


def test_f3_transport_exception_is_recorded_and_counts_toward_call_cap():
    fake = Fake(tool=_timeout_tool())
    client, ledger, _ = make(fake, call_cap=1)
    with pytest.raises(Timeout):
        client.run("analyze_stock", "TEST")
    entries = tool_entries(ledger)
    assert len(entries) == 1
    assert entries[0].status == 0
    assert ledger.calls(PHASE) == 1
    with pytest.raises(CreditBudgetExceeded):
        client.run("analyze_stock", "TEST")
    assert len(fake.tool_hits) == 1


def test_f3_failed_attempt_cost_equals_balance_drop():
    fake = Fake(tool=_timeout_tool(drop=7))
    client, ledger, _ = make(fake)
    with pytest.raises(Timeout):
        client.run("analyze_stock", "TEST")
    entry = tool_entries(ledger)[0]
    assert entry.status == 0
    assert entry.cost == 7
    assert ledger.spent(PHASE) == 7


def test_f3_failed_attempt_with_balance_down_blinds_ledger_and_refuses_next():
    fake = Fake(tool=_timeout_tool(balance_down=True))
    client, ledger, _ = make(fake)
    with pytest.raises(Timeout):
        client.run("analyze_stock", "TEST")
    entry = tool_entries(ledger)[0]
    assert entry.status == 0
    assert entry.cost is None
    assert ledger.blind is True
    assert ledger.spent(PHASE) >= UNKNOWN_PRICE_RESERVE
    with pytest.raises(CreditBudgetExceeded):
        client.run("analyze_stock", "TEST")
    assert len(fake.tool_hits) == 1


# ---------------------------------------------------------------------- F-4
@pytest.mark.parametrize(("mode", "status"), [("500", 500), ("raise", 0)])
def test_f4_every_credit_endpoint_get_is_in_the_meta_phase(mode, status):
    fake = Fake(tool=lambda f, r: resp())  # no headers: forces the fallback balance GET
    client, ledger, _ = make(fake)
    client.run("analyze_stock", "TEST")  # fallback GET succeeds
    fake.balance_fails = mode  # now the fallback GET fails
    client.run("analyze_stock", "TEST")
    assert len(fake.credit_hits) == 6  # 4 at start + 2 fallbacks
    meta = meta_entries(ledger)
    assert len(meta) == len(fake.credit_hits)
    assert sorted(e.tool for e in meta) == sorted(fake.credit_hits)
    assert meta[-1].status == status
    # nothing credit-related leaked into the tool phase
    assert all(e.tool not in (BALANCE_PATH, CATALOG_PATH) for e in tool_entries(ledger))


# ------------------------------------------------------------ fallback costing
def test_fallback_costing_attributes_balance_drop_to_the_tool_not_the_meta_read():
    def tool(fake: Fake, request: httpx.Request) -> httpx.Response:
        fake.balance -= 4
        return resp()  # no credit headers at all

    fake = Fake(tool=tool)
    client, ledger, _ = make(fake)
    client.run("analyze_stock", "TEST")
    (entry,) = tool_entries(ledger)
    assert entry.cost == 4
    assert entry.balance_source == "endpoint"
    last_meta = meta_entries(ledger)[-1]
    assert last_meta.cost in (0, None)
    assert ledger.spent(PHASE) == 4  # no double counting
    assert ledger.spent() == 4


# ---------------------------------------------------------------------- F-5
def test_f5_negative_charged_header_is_not_a_negative_cost():
    fake = Fake(tool=lambda f, r: resp(charged="-50", remaining="1000"))
    client, ledger, _ = make(fake)
    before = ledger.spent(PHASE)
    client.run("analyze_stock", "TEST")
    (entry,) = tool_entries(ledger)
    assert entry.cost is None or entry.cost >= 0
    assert entry.charged_header is None or entry.charged_header >= 0
    assert ledger.spent(PHASE) >= before
    assert ledger.spent(PHASE) >= 0


def test_f5_topup_between_calls_is_unknown_cost_counted_conservatively():
    answers = iter([resp(remaining="1000", charged="0"), resp(remaining="1500")])
    fake = Fake(tool=lambda f, r: next(answers))
    client, ledger, _ = make(fake)
    client.run("analyze_stock", "TEST")
    spent_after_first = ledger.spent(PHASE)
    client.run("analyze_stock", "TEST")
    first, second = tool_entries(ledger)
    assert second.cost is None  # a balance increase is not a negative cost
    assert ledger.unknown_cost_calls(PHASE) == 1
    assert ledger.spent(PHASE) >= spent_after_first + UNKNOWN_PRICE_RESERVE


def test_f5_fractional_charged_header_rounds_up():
    fake = Fake(tool=lambda f, r: resp(charged="2.1", remaining="998"))
    client, ledger, _ = make(fake)
    client.run("analyze_stock", "TEST")
    (entry,) = tool_entries(ledger)
    assert entry.cost == 3
    assert ledger.spent(PHASE) == 3


# ---------------------------------------------------------------------- F-6
@pytest.mark.parametrize("value", ["inf", "nan", "abc", "-inf", ""])
def test_f6_junk_remaining_header_does_not_raise_in_parser(value):
    assert parse_balance(httpx.Headers({"X-Credits-Remaining": value})) is None


@pytest.mark.parametrize("value", ["inf", "nan", "abc"])
def test_f6_junk_remaining_header_is_treated_as_unknown(value):
    def tool(fake: Fake, request: httpx.Request) -> httpx.Response:
        fake.balance_fails = "500"  # the fallback cannot rescue it
        return resp(remaining=value)

    fake = Fake(tool=tool)
    client, ledger, _ = make(fake)
    assert client.run("analyze_stock", "TEST").data == OK  # no exception
    (entry,) = tool_entries(ledger)
    assert entry.balance_after is None
    assert entry.cost is None
    assert ledger.blind is True


# ---------------------------------------------------------- HTTP error statuses
@pytest.mark.parametrize("status", [402, 429, 500])
def test_http_error_statuses_without_credit_headers_cost_zero_and_do_not_blind(status):
    def tool(fake: Fake, request: httpx.Request) -> httpx.Response:
        fake.balance_fails = "500"  # no balance evidence: only the status can say 0
        return resp(status, body={"error": "x"})

    fake = Fake(tool=tool)
    client, ledger, _ = make(fake)
    with pytest.raises(AdapterError):
        client.run("analyze_stock", "TEST")
    entries = tool_entries(ledger)
    assert entries
    assert {e.status for e in entries} == {status}
    assert all(e.cost == 0 for e in entries)
    assert ledger.blind is False
    assert ledger.spent(PHASE) == 0


# ------------------------------------------------------------------------ J4
def _make_blind_file(path: Path) -> None:
    def tool(fake: Fake, request: httpx.Request) -> httpx.Response:
        fake.balance_fails = "500"
        return resp()  # no headers, no balance: cost unknowable

    fake = Fake(tool=tool)
    client, ledger, _ = make(fake, ledger=CreditLedger(path))
    client.run("analyze_stock", "TEST")
    assert ledger.blind is True
    assert json.loads(path.read_text(encoding="utf-8"))["blind"] is True


def test_j4_blind_ledger_is_cleared_next_run_when_balance_read_succeeds(tmp_path):
    path = tmp_path / "ledger.json"
    _make_blind_file(path)
    assert CreditLedger(path).blind is True

    fake = Fake(tool=lambda f, r: resp(charged="1", remaining="999"))
    client, ledger, _ = make(fake, ledger=CreditLedger(path), phase="next")
    assert client.run("analyze_stock", "TEST").data == OK
    assert len(fake.tool_hits) == 1
    assert ledger.blind is False
    assert json.loads(path.read_text(encoding="utf-8"))["blind"] is False


def test_j4_blind_ledger_stays_refused_when_balance_read_fails(tmp_path):
    path = tmp_path / "ledger.json"
    _make_blind_file(path)

    fake = Fake()
    fake.balance_fails = "500"
    client, ledger, _ = make(fake, ledger=CreditLedger(path), phase="next")
    with pytest.raises(CreditBudgetExceeded):
        client.run("analyze_stock", "TEST")
    assert fake.tool_hits == []
    assert ledger.blind is True
    assert json.loads(path.read_text(encoding="utf-8"))["blind"] is True


# ------------------------------------------------------------------------ J8
def test_j8_corrupt_ledger_file_refuses_everything_and_is_not_overwritten(tmp_path):
    path = tmp_path / "ledger.json"
    path.write_text("{not json", encoding="utf-8")
    fake = Fake()
    client, ledger, transport = make(fake, ledger=CreditLedger(path))
    assert ledger.unreadable is True
    with pytest.raises(CreditBudgetExceeded):
        client.run("analyze_stock", "TEST")
    with pytest.raises(CreditBudgetExceeded):
        client.run("analyze_stock", "TEST")
    # also straight through the transport, bypassing the client
    with pytest.raises(CreditBudgetExceeded):
        transport.handle_request(httpx.Request("GET", "https://example.invalid/x/TEST"))
    assert fake.tool_hits == []
    assert fake.credit_hits == []
    assert path.read_text(encoding="utf-8") == "{not json"
    assert not path.with_suffix(".tmp").exists()


@pytest.mark.parametrize("content", ["[]", '{"entries": [{"bogus": 1}]}', '{"entries": 5}'])
def test_j8_structurally_wrong_ledger_file_also_fails_closed(tmp_path, content):
    path = tmp_path / "ledger.json"
    path.write_text(content, encoding="utf-8")
    fake = Fake()
    client, ledger, _ = make(fake, ledger=CreditLedger(path))
    assert ledger.unreadable is True
    with pytest.raises(CreditBudgetExceeded):
        client.run("analyze_stock", "TEST")
    assert fake.tool_hits == []
    assert path.read_text(encoding="utf-8") == content


# ---------------------------------------------------------------------- F-7
def test_f7_bare_constructor_installs_a_finite_recording_transport():
    client = ResearchClient(KEY)
    try:
        transport = client._transport
        assert isinstance(transport, RecordingTransport)
        assert isinstance(transport.budget, int)
        assert 0 < transport.budget <= DEFAULT_MAX_CREDITS
        assert 0 < transport.call_cap <= DEFAULT_CALL_CAP
        assert transport.ledger.path is None
    finally:
        client.close()


# ------------------------------------------------------------- total budget
def test_total_budget_is_enforced_across_runs_with_different_phases(tmp_path):
    path = tmp_path / "ledger.json"
    fake = Fake(tool=lambda f, r: resp(charged="20", remaining="980"))
    client1, _, _ = make(fake, ledger=CreditLedger(path), phase="a", total_budget=30)
    client1.run("analyze_stock", "TEST")
    assert CreditLedger(path).spent() == 20

    fake2 = Fake(tool=lambda f, r: resp(charged="20", remaining="960"))
    client2, ledger2, _ = make(fake2, ledger=CreditLedger(path), phase="b", total_budget=30)
    with pytest.raises(CreditBudgetExceeded):
        client2.run("analyze_stock", "TEST")
    assert fake2.tool_hits == []
    assert ledger2.spent("b") == 0
    assert ledger2.spent() == 20


# ------------------------------------------------------------------ retries
def test_retries_are_counted_as_separate_tool_entries():
    answers = iter([resp(503, body={"error": "down"}, remaining="1000"), resp(remaining="999")])
    fake = Fake(tool=lambda f, r: next(answers))
    client, ledger, _ = make(fake)
    assert client.run("analyze_stock", "TEST").data == OK
    entries = tool_entries(ledger)
    assert [e.status for e in entries] == [503, 200]
    assert ledger.calls(PHASE) == 2
    assert len(fake.tool_hits) == 2


# ------------------------------------------------- credit endpoints unproven
def test_unproven_credit_endpoints_are_not_used_again_in_the_run():
    fake = Fake(tool=lambda f, r: resp())  # no headers: would normally trigger a fallback GET
    fake.drift = 1  # the balance moves between the free-check reads
    client, ledger, transport = make(fake)
    client.run("analyze_stock", "TEST")
    assert transport.meta_enabled is False
    after_start = len(fake.credit_hits)
    assert after_start == 4  # balance, balance, catalog, balance
    with contextlib.suppress(CreditBudgetExceeded):
        client.run("analyze_stock", "TEST")
    # (the second run is refused if the ledger went blind; either way no more GETs)
    assert len(fake.credit_hits) == after_start
    assert ledger.meta_free_verified is False


# ------------------------------------------------------- review loop 2 (F-N1, F-N2)
def test_fn1_failed_call_does_not_lower_the_reserve(tmp_path: Path):
    """A 404 (recorded at cost 0) must not make the tool look free next time."""
    path = tmp_path / "ledger.json"
    first = Fake(tool=lambda f, r: resp(404, body={"error": "not_found"}))
    client, _, _ = make(first, ledger=CreditLedger(path), phase="run1", budget=100)
    with contextlib.suppress(AdapterError):
        client.run("monte_carlo", "TEST")

    second = Fake(tool=lambda f, r: resp(charged="8", remaining="992"))
    client, _, _ = make(second, ledger=CreditLedger(path), phase="run2", budget=0)
    with pytest.raises(CreditBudgetExceeded):
        client.run("monte_carlo", "TEST")
    assert second.tool_hits == []


def test_fn1_within_one_run_failure_then_success_respects_budget():
    """A failing ticker then a working one: the second call reserves the full unknown price."""

    def tool(fake: Fake, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/BADX"):
            return resp(404, body={"error": "not_found"})
        return resp(charged="15", remaining="985")

    fake = Fake(tool=tool)
    client, ledger, _ = make(fake, budget=UNKNOWN_PRICE_RESERVE - 1)
    with contextlib.suppress(AdapterError):
        client.run("monte_carlo", "BADX")
    with pytest.raises(CreditBudgetExceeded):
        client.run("monte_carlo", "TEST")
    assert ledger.spent(PHASE) <= UNKNOWN_PRICE_RESERVE - 1


def test_fn2_floor_ignores_balance_from_an_earlier_run(tmp_path: Path):
    """Balance read fails at start: a balance persisted by a previous run is not trusted."""
    path = tmp_path / "ledger.json"
    first = Fake(balance=5000, tool=lambda f, r: resp(charged="1", remaining="4999"))
    client, _, _ = make(first, ledger=CreditLedger(path), phase="run1")
    client.run("iv_radar", "TEST")

    second = Fake(tool=lambda f, r: resp(charged="1", remaining="999"))
    second.balance_fails = "500"
    client, _, _ = make(second, ledger=CreditLedger(path), phase="run2", floor=1800)
    with pytest.raises(CreditBudgetExceeded):
        client.run("iv_radar", "TEST")
    assert second.tool_hits == []


def test_fn2_floor_uses_balance_seen_in_this_run():
    fake = Fake(balance=1000, tool=lambda f, r: resp(charged="1", remaining="999"))
    client, _, transport = make(fake, floor=1800)
    with pytest.raises(CreditBudgetExceeded):
        client.run("iv_radar", "TEST")
    assert transport.run_balance == 1000
    assert fake.tool_hits == []


@pytest.mark.parametrize(
    "entry_patch",
    [{"cost": -50}, {"cost": "12"}, {"balance_after": -1}, {"status": "200"}, {"cost": True}],
)
def test_hand_edited_ledger_values_fail_closed(tmp_path: Path, entry_patch: dict):
    path = tmp_path / "ledger.json"
    fake = Fake(tool=lambda f, r: resp(charged="2", remaining="998"))
    client, _, _ = make(fake, ledger=CreditLedger(path), phase="run1")
    client.run("iv_radar", "TEST")
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["entries"][-1].update(entry_patch)
    path.write_text(json.dumps(raw), encoding="utf-8")
    before = path.read_text(encoding="utf-8")

    ledger = CreditLedger(path)
    assert ledger.unreadable
    client, _, _ = make(fake, ledger=ledger, phase="run2")
    with pytest.raises(CreditBudgetExceeded):
        client.run("iv_radar", "TEST")
    assert path.read_text(encoding="utf-8") == before


def test_from_env_default_phase_is_unique(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("HPSILAB_API_KEY", KEY)
    a = ResearchClient.from_env(ledger_path=None)
    b = ResearchClient.from_env(ledger_path=None)
    try:
        assert a._transport.phase != b._transport.phase
        assert a._transport.phase.startswith("lib-")
    finally:
        a.close()
        b.close()


def test_from_env_default_phase_unique_in_tight_loop(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("HPSILAB_API_KEY", KEY)
    clients = [ResearchClient.from_env(ledger_path=None) for _ in range(50)]
    try:
        assert len({c._transport.phase for c in clients}) == 50
    finally:
        for c in clients:
            c.close()


def test_string_flags_in_ledger_file_are_not_truthy(tmp_path: Path):
    path = tmp_path / "ledger.json"
    path.write_text(json.dumps({"blind": "false", "meta_free_verified": "false", "entries": []}))
    ledger = CreditLedger(path)
    assert ledger.meta_free_verified is False


# ------------------------------------------- catalog shape observed live 2026-11-22
FAKE_CATALOG = json.loads(
    (Path(__file__).parent / "fixtures" / "credits_catalog_fake.json").read_text(encoding="utf-8")
)
SDK_NAMES = {
    "analyze_stock",
    "get_ai_prediction",
    "get_iv_radar",
    "get_option_pressure",
    "get_pretrade_risk_scan",
    "get_monte_carlo",
}


def test_catalog_canonical_names_and_aliases_only_when_active():
    prices = parse_catalog(FAKE_CATALOG, SDK_NAMES)
    assert prices == {
        "analyze_stock": 7,  # the inactive 99-credit duplicate is ignored
        "get_ai_prediction": 9,  # matched through aliases
        "get_monte_carlo": 1,
    }
    # active: "true" (a string) is not active; iv_radar has a different catalog name.
    assert "get_option_pressure" not in prices
    assert "get_iv_radar" not in prices


def test_catalog_path_patterns_cover_renamed_tools():
    pairs = parse_catalog_paths(FAKE_CATALOG)
    assert price_for_path("/api/iv_batch", pairs) == 11
    assert price_for_path("/api/monte_carlo/TEST", pairs) == 1
    assert price_for_path("/api/montecarlo/TEST", pairs) == 1
    assert price_for_path("/api/analyze_stock/TEST", pairs) == 7  # active entry first
    assert price_for_path("/api/option_pressure/TEST", pairs) is None  # inactive ("true")
    assert price_for_path("/api/monte_carlo/TEST/extra", pairs) is None
    assert price_for_path("/api/pretrade-risk-scan", pairs) is None


def test_transport_prices_renamed_tool_by_path_and_refuses_over_budget():
    fake = Fake(catalog=FAKE_CATALOG, tool=lambda f, r: resp(charged="11", remaining="989"))
    client, ledger, transport = make(fake, budget=10)
    with pytest.raises(CreditBudgetExceeded):
        client.run("iv_radar", "TEST")  # path price 11 > budget 10
    assert fake.tool_hits == []
    client, ledger, transport = make(fake, budget=11)
    client.run("iv_radar", "TEST")
    assert len(fake.tool_hits) == 1


def test_inactive_catalog_price_never_used():
    catalog = {
        "tools": [
            {
                "canonical_tool_name": "analyze_stock",
                "aliases": [],
                "credits": 1,
                "active": False,
                "rest_path_patterns": ["/api/analyze_stock/*"],
            }
        ]
    }
    fake = Fake(catalog=catalog)
    client, _, _ = make(fake, budget=5)
    with pytest.raises(CreditBudgetExceeded):  # unknown price reserves 20
        client.run("analyze_stock", "TEST")
    assert fake.tool_hits == []
