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
    print("catalog structure (keys/types only):")
    print(json.dumps(shape(body, "NVDA"), indent=1)[:4000])
    print(f"catalog prices parsed: {parse_catalog(body, names)}")
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
    phase = "ship"
    rows = []
    stopped = None
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
                try:
                    r = client.run(tool, ticker)
                    rows.append(
                        (
                            ticker,
                            tool,
                            "ok",
                            len(r.source_fields),
                            list(r.missing_fields),
                            r.horizon is not None,
                        )
                    )
                except CreditBudgetExceeded as exc:
                    stopped = str(exc)
                    break
                except AdapterError as exc:
                    rows.append((ticker, tool, type(exc).__name__, 0, [], False))
            if stopped:
                break

    ledger = CreditLedger(LEDGER)
    costs = {(e.ticker, e.tool): e.cost for e in ledger.entries if e.phase == phase}
    sdk = {s.name: s.sdk_method for s in TOOLS.values()}
    print("ticker tool                 status          fields missing horizon credits")
    for ticker, tool, status, n, missing, has_h in rows:
        print(
            f"{ticker:6s} {tool:20s} {status:15s} {n:6d} {len(missing):7d} "
            f"{'yes' if has_h else 'no':7s} {costs.get((ticker, sdk[tool]))}"
        )
    if stopped:
        print(f"STOPPED by credit guard: {stopped}")
    ok = sum(1 for r in rows if r[2] == "ok")
    print(
        f"ship check: {ok}/{len(rows)} ok of {len(TICKERS) * len(TOOL_NAMES)} planned; "
        f"ship credits={ledger.spent(phase)}; all-time credits={ledger.spent()} "
        f"of {TOTAL_CREDIT_BUDGET}; balance now {ledger.last_balance}; blind={ledger.blind}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
