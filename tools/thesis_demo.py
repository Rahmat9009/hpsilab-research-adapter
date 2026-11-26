"""Live thesis demo: one NVDA pass over the six research tools. Run by hand, never in CI.

Usage from the repository root:
    python tools/thesis_demo.py [DIRECTION [HORIZON_DAYS]] [--ledger PATH]
DIRECTION is up, down or range (default up); HORIZON_DAYS defaults to 10. --ledger PATH
uses that ledger file directly (default .credits/ledger.json under the repository root),
for example the main repository's ledger, so it never has to be copied.

The thesis comes from the command line; this script never chooses one. It makes one
pass over the six GET tools through ResearchClient.from_env with the persistent
ledger (default .credits/ledger.json), then writes the evidence report to .probe/thesis_NVDA.md
and .probe/thesis_NVDA.json (git-ignored; real values are never committed). Only stance
tallies, the missing count and the credits used are printed.

Research only. Not a recommendation. Independent, unverified third-party
integration, not verified or endorsed by HPSILab. The API key is read from
HPSILAB_API_KEY by the client and is never printed.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from hpsilab_research_adapter import errors, thesis, tools
from hpsilab_research_adapter.cli import _PER_CALL_ERRORS
from hpsilab_research_adapter.client import ResearchClient
from hpsilab_research_adapter.ledger import UNKNOWN_PRICE_RESERVE, CreditLedger
from hpsilab_research_adapter.policy import MAX_ATTEMPTS
from hpsilab_research_adapter.types import Result

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / ".credits" / "ledger.json"
OUT = ROOT / ".probe"

TICKER = "NVDA"
# The owner approved +40 credits on 2026-11-26 for exactly one NVDA pass beyond the
# original 150-credit cap: 150 + 40 = 190. Do not reuse this allowance for anything else.
MAX_CREDITS = 40
TOTAL_BUDGET = 190
MIN_BALANCE = 1800


def _price_sum(ledger: CreditLedger) -> int:
    """Sum of the observed per-tool prices; an unseen tool is reserved at the unknown price."""
    total = 0
    for name in tools.TOOL_NAMES:
        spec = tools.TOOLS[name]
        seen = [c for c in (ledger.tool_cost(spec.name), ledger.tool_cost(spec.sdk_method)) if c]
        total += max(seen) if seen else max(UNKNOWN_PRICE_RESERVE, ledger.max_cost)
    return total


def _parse(argv: list[str]) -> tuple[list[str], Path]:
    """Split off --ledger PATH; the remaining positionals keep their old meaning."""
    parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    parser.add_argument("--ledger", default=None)
    parser.add_argument("positionals", nargs="*")
    parsed = parser.parse_args(argv)
    return parsed.positionals, Path(parsed.ledger) if parsed.ledger else LEDGER


def main(argv: list[str]) -> int:
    try:
        positionals, ledger_path = _parse(argv)
    except SystemExit:
        print(
            "REFUSED: usage: thesis_demo.py [DIRECTION [HORIZON_DAYS]] [--ledger PATH]", flush=True
        )
        return 2
    if len(positionals) > 2:
        print("REFUSED: too many arguments.", flush=True)
        return 2
    direction = positionals[0] if positionals else "up"
    try:
        horizon = int(positionals[1]) if len(positionals) > 1 else 10
        stated = thesis.Thesis(TICKER, direction, horizon)
    except ValueError as exc:
        print(f"REFUSED: {exc}", flush=True)
        return 2

    ledger = CreditLedger(ledger_path)
    if ledger.unreadable:
        print("REFUSED: the credit ledger is unreadable; fix it first.", flush=True)
        return 3
    remaining = TOTAL_BUDGET - ledger.spent()
    needed = _price_sum(ledger)
    if remaining < needed:
        print(
            f"REFUSED: remaining total budget {remaining} is below the price of one pass "
            f"({needed}).",
            flush=True,
        )
        return 4

    results: dict[str, Result | Exception | None] = {}
    phase = f"thesis-demo-{datetime.now(UTC):%Y%m%dT%H%M%S}"
    try:
        client = ResearchClient.from_env(
            phase=phase,
            ledger_path=ledger_path,
            max_credits=MAX_CREDITS,
            call_cap=len(tools.TOOL_NAMES) * MAX_ATTEMPTS,
            total_budget=TOTAL_BUDGET,
            min_balance=MIN_BALANCE,
        )
    except errors.AdapterError as exc:
        print(f"REFUSED: {type(exc).__name__} before any request was sent.", flush=True)
        return 3
    try:
        for tool in tools.TOOL_NAMES:
            try:
                results[tool] = client.run(tool, TICKER)
            except _PER_CALL_ERRORS as exc:
                results[tool] = exc
    except errors.AdapterError as exc:
        print(f"STOPPED: {type(exc).__name__}", flush=True)
        for tool in tools.TOOL_NAMES:
            results.setdefault(tool, exc)
    finally:
        client.close()

    report = thesis.evaluate(stated, results)
    credits_used = CreditLedger(ledger_path).spent(phase)
    OUT.mkdir(exist_ok=True)
    (OUT / f"thesis_{TICKER}.md").write_text(thesis.render_markdown(report), encoding="utf-8")
    payload = thesis.to_dict(report)
    payload["credits_used"] = credits_used
    (OUT / f"thesis_{TICKER}.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )

    print(f"thesis: {TICKER} {stated.direction} {stated.horizon_days} days", flush=True)
    for bucket, counts in report.tallies.items():
        print(f"  {bucket}: {counts}", flush=True)
    print(f"missing: {len(report.missing)}", flush=True)
    print(f"credits used this run: {credits_used}", flush=True)
    print(f"report: {OUT / f'thesis_{TICKER}.md'}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
