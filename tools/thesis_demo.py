"""Live thesis demo: one NVDA pass over the six research tools. Run by hand, never in CI.

Usage from the repository root:
    python tools/thesis_demo.py [DIRECTION [HORIZON_DAYS]] [--ledger PATH]
DIRECTION is up, down or range (default up); HORIZON_DAYS defaults to 10. --ledger PATH
uses that ledger file directly (default .credits/ledger.json under the repository root),
for example the main repository's ledger, so it never has to be copied. The ledger file
must already exist: the total budget only means something against the recorded history,
so a missing file (or an empty --ledger value) is refused before any request.

The thesis comes from the command line; this script never chooses one. It makes one
pass over the six GET tools through ResearchClient.from_env with the persistent
ledger (default .credits/ledger.json), then writes the evidence report to .probe/thesis_NVDA.md
and .probe/thesis_NVDA.json (git-ignored; real values are never committed). Only the
stated thesis, stance tallies, the missing count, the credits used and the report path
are printed. Exit codes: 0 done, 2 bad arguments, 3 refused (ledger, key or client),
4 refused (budget), 5 stopped early by a limit (the report is partial).

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
from hpsilab_research_adapter.ledger import CreditLedger
from hpsilab_research_adapter.policy import MAX_ATTEMPTS
from hpsilab_research_adapter.types import Result

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / ".credits" / "ledger.json"
OUT = ROOT / ".probe"

TICKER = "NVDA"
# Fixed project budgets: 40 credits per run, 190 across all runs in the ledger.
# The per-run cap is below the catalog price of all six tools together, so the last
# tool of a pass can be refused; monte_carlo (the only horizon-bearing tool) runs first.
MAX_CREDITS = 40
TOTAL_BUDGET = 190
MIN_BALANCE = 1800
RUN_ORDER = (tools.MONTE_CARLO, *(t for t in tools.TOOL_NAMES if t != tools.MONTE_CARLO))


def _price_sum(ledger: CreditLedger) -> int:
    """Sum of the positive per-tool costs observed in the ledger. A tool with no positive
    cost on record adds nothing here: its real price comes from the catalog at run time
    and the client's per-run budget refuses it before it can exceed MAX_CREDITS."""
    total = 0
    for name in tools.TOOL_NAMES:
        spec = tools.TOOLS[name]
        seen = [c for c in (ledger.tool_cost(spec.name), ledger.tool_cost(spec.sdk_method)) if c]
        total += max(seen) if seen else 0
    return total


def _parse(argv: list[str]) -> tuple[list[str], Path]:
    """Split off --ledger PATH; the remaining positionals keep their old meaning."""
    parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    parser.add_argument("--ledger", default=None)
    parser.add_argument("positionals", nargs="*")
    parsed = parser.parse_args(argv)
    if parsed.ledger is None:
        return parsed.positionals, LEDGER
    if not parsed.ledger.strip():
        raise SystemExit(2)  # an empty --ledger must not fall back to the default
    return parsed.positionals, Path(parsed.ledger)


def main(argv: list[str]) -> int:
    if any(a in ("-h", "--help") for a in argv):
        usage = (__doc__ or "").strip().split("\n\n")[1]
        print(usage, flush=True)
        print("Independent, unverified third-party integration; research only.", flush=True)
        return 0
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

    if not ledger_path.is_file():
        print(
            "REFUSED: the ledger file does not exist. Pass --ledger PATH to the existing "
            "credit ledger; the total budget cannot be enforced without its history.",
            flush=True,
        )
        return 3
    ledger = CreditLedger(ledger_path)
    if ledger.unreadable:
        print("REFUSED: the credit ledger is unreadable; fix it first.", flush=True)
        return 3
    remaining = TOTAL_BUDGET - ledger.spent()
    needed = _price_sum(ledger)
    if remaining < MAX_CREDITS or needed > min(remaining, MAX_CREDITS):
        print(
            f"REFUSED: remaining total budget {remaining} or the per-run cap {MAX_CREDITS} "
            f"is below the recorded price of one pass ({needed}) or below the cap itself.",
            flush=True,
        )
        return 4

    results: dict[str, Result | Exception | None] = {}
    stopped = False
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
        for tool in RUN_ORDER:
            try:
                results[tool] = client.run(tool, TICKER)
            except _PER_CALL_ERRORS as exc:
                results[tool] = exc
    except errors.AdapterError as exc:
        stopped = True
        print(f"STOPPED: {type(exc).__name__}", flush=True)
        for tool in tools.TOOL_NAMES:
            results.setdefault(tool, exc)
    finally:
        client.close()

    report = thesis.evaluate(stated, results)
    after = CreditLedger(ledger_path)
    credits_used: int | None = None if after.unreadable else after.spent(phase)
    OUT.mkdir(exist_ok=True)
    (OUT / f"thesis_{TICKER}.md").write_text(thesis.render_markdown(report), encoding="utf-8")
    payload = thesis.to_dict(report)
    payload["credits_used"] = credits_used  # null when the ledger could not be read back
    (OUT / f"thesis_{TICKER}.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )

    print(f"thesis: {TICKER} {stated.direction} {stated.horizon_days} days", flush=True)
    for bucket, counts in report.tallies.items():
        print(f"  {bucket}: {counts}", flush=True)
    print(f"missing: {len(report.missing)}", flush=True)
    if credits_used is None:
        print("credits used this run: unknown (the ledger could not be read back)", flush=True)
    else:
        print(f"credits used this run: {credits_used}", flush=True)
    print(f"report: {OUT / f'thesis_{TICKER}.md'}", flush=True)
    return 5 if stopped else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
