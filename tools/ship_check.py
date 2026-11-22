"""Phase 7 live ship check: NVDA, AAPL, SPY x 6 tools inside the remaining credit budget.

Prints a summary only (status, field counts, horizon, credits); no response values.
Every request goes through the persisted credit ledger with the 150-credit total
cap and the 1,800 balance floor. Also saves the credit catalog to .probe/ and
prints its structure (keys and types) so the price parser can be checked.

Run from the repository root:  python tools/ship_check.py
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from hpsilab_mcp.client import DEFAULT_BASE_URL
from probe import shape

from hpsilab_research_adapter import cli
from hpsilab_research_adapter.client import ResearchClient
from hpsilab_research_adapter.errors import AdapterError, CreditBudgetExceeded
from hpsilab_research_adapter.ledger import (
    CATALOG_PATH,
    CreditLedger,
    RecordingTransport,
    make_template,
    parse_catalog,
)
from hpsilab_research_adapter.policy import (
    BALANCE_FLOOR,
    ENV_API_KEY,
    ENV_X402_WALLET,
    SHIP_CHECK_CALL_CAP,
    TOTAL_CREDIT_BUDGET,
)
from hpsilab_research_adapter.tools import TOOL_NAMES, TOOLS

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / ".credits" / "ledger.json"
TICKERS = ("AAPL", "SPY", "NVDA")  # NVDA last: it was probed already


def catalog_report(api_key: str) -> None:
    ledger = CreditLedger(LEDGER)
    transport = RecordingTransport(ledger, "ship", budget=0, call_cap=0)
    response, body = transport._meta_get(make_template(DEFAULT_BASE_URL, api_key), CATALOG_PATH)
    (ROOT / ".probe").mkdir(exist_ok=True)
    (ROOT / ".probe" / "catalog.raw.json").write_text(json.dumps(body, indent=2), "utf-8")
    names = {s.name for s in TOOLS.values()} | {s.sdk_method for s in TOOLS.values()}
    print(f"catalog status={response.status_code}")
    print(f"catalog structure: {json.dumps(shape(body, 'NVDA'))[:300]}...")
    print(f"catalog prices parsed: {parse_catalog(body, names)}", flush=True)
    transport.close()


def cli_smoke(remaining: int) -> None:
    """End-to-end through the real CLI: one zero-cost tool, JSON output, counted not shown."""
    argv = [
        "SPY",
        "--tool",
        "iv_radar",
        "--json",
        "--total-credits",
        str(TOTAL_CREDIT_BUDGET),
        "--min-balance",
        str(BALANCE_FLOOR),
        "--max-credits",
        str(min(remaining, 20)),
        "--ledger",
        str(LEDGER),
    ]
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = cli.main(argv)
    try:
        parsed = json.loads(out.getvalue())
        shape_ok = isinstance(parsed, list) and all("source_fields" in r for r in parsed)
        n = len(parsed)
    except ValueError:
        shape_ok, n = False, 0
    print(
        f"CLI smoke `hpsilab SPY --tool iv_radar --json`: exit={rc} results={n} "
        f"json_ok={shape_ok} stderr={err.getvalue().strip()[:200]!r}"
    )


def main() -> int:
    if os.environ.get(ENV_X402_WALLET):
        print(f"REFUSED: {ENV_X402_WALLET} is set.")
        return 3
    api_key = os.environ.get(ENV_API_KEY)
    if not api_key:
        print(f"REFUSED: {ENV_API_KEY} is not set.")
        return 3

    catalog_report(api_key)
    del api_key

    ledger = CreditLedger(LEDGER)
    remaining = TOTAL_CREDIT_BUDGET - ledger.spent()
    print(
        f"credits spent before ship check: {ledger.spent()}; remaining budget: {remaining}; "
        f"last balance: {ledger.last_balance}"
    )
    if remaining <= 0:
        print("STOPPED: no credit budget left.")
        return 4

    cli_smoke(remaining)

    ledger = CreditLedger(LEDGER)
    remaining = TOTAL_CREDIT_BUDGET - ledger.spent()
    phase = f"ship-{datetime.now(UTC):%Y%m%dT%H%M%S}"
    sdk = {s.name: s.sdk_method for s in TOOLS.values()}
    rows: list[dict] = []
    stopped = None
    print(f"per-ticker run: phase={phase} budget={remaining} floor={BALANCE_FLOOR}", flush=True)
    print(
        "ticker tool                 status               fields missing horizon credits",
        flush=True,
    )
    try:
        with ResearchClient.from_env(
            phase=phase,
            ledger_path=LEDGER,
            max_credits=remaining,
            call_cap=SHIP_CHECK_CALL_CAP,
            total_budget=TOTAL_CREDIT_BUDGET,
            min_balance=BALANCE_FLOOR,
        ) as client:
            for ticker in TICKERS:
                for tool in TOOL_NAMES:
                    row = {
                        "ticker": ticker,
                        "tool": tool,
                        "status": "ok",
                        "fields": 0,
                        "missing": 0,
                        "horizon": False,
                    }
                    try:
                        r = client.run(tool, ticker)
                        row.update(
                            fields=len(r.source_fields),
                            missing=len(r.missing_fields),
                            horizon=r.horizon is not None,
                        )
                    except CreditBudgetExceeded as exc:
                        stopped = f"credit guard refused {ticker} {tool}: {exc}"
                        break
                    except AdapterError as exc:
                        row["status"] = type(exc).__name__
                    last = [
                        e
                        for e in CreditLedger(LEDGER).entries
                        if e.phase == phase and e.tool == sdk[tool] and e.ticker == ticker
                    ]
                    row["credits"] = last[-1].cost if last else None
                    rows.append(row)
                    print(
                        f"{ticker:6s} {tool:20s} {row['status']:20s} {row['fields']:6d} "
                        f"{row['missing']:7d} {'yes' if row['horizon'] else 'no':7s} "
                        f"{row['credits']}",
                        flush=True,
                    )
                if stopped:
                    break
    except Exception as exc:  # report, never hide; no message text (could echo a body)
        stopped = f"unexpected {type(exc).__name__} after {len(rows)} calls"
    if stopped:
        print(f"STOPPED: {stopped}", flush=True)

    ledger = CreditLedger(LEDGER)
    ok = sum(1 for r in rows if r["status"] == "ok")
    summary = {
        "phase": phase,
        "planned": len(TICKERS) * len(TOOL_NAMES),
        "completed": len(rows),
        "ok": ok,
        "stopped": stopped,
        "rows": rows,
        "ship_credits": ledger.spent(phase),
        "all_time_credits": ledger.spent(),
        "total_budget": TOTAL_CREDIT_BUDGET,
        "balance_now": ledger.last_balance,
        "blind": ledger.blind,
    }
    (ROOT / ".credits" / "ship_summary.json").write_text(json.dumps(summary, indent=2), "utf-8")
    print(
        f"ship check: {ok}/{len(rows)} ok of {summary['planned']} planned; "
        f"ship credits={summary['ship_credits']}; all-time credits={summary['all_time_credits']} "
        f"of {TOTAL_CREDIT_BUDGET}; balance now {summary['balance_now']}; blind={ledger.blind}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
