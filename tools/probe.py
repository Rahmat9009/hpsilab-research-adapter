"""Phase 2 live probe: one call per research tool, shapes only.

Writes schemas/<tool>.shape.json (keys and types, never values) and keeps raw
responses in .probe/ (gitignored). Every request goes through the credit ledger:
the call cap, the probe and total credit budgets, and the balance floor are
checked before sending, and the probe stops if the balance header is missing.

Run from the repository root:  python tools/probe.py [--ticker NVDA]
The API key is read from HPSILAB_API_KEY and is never printed.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from hpsilab_mcp import CREDITS_ONLY, HpsiMcpClient, HpsiMcpError
from hpsilab_mcp.client import DEFAULT_BASE_URL

from hpsilab_research_adapter.errors import AuthError, CreditBudgetExceeded, UnsafeConfiguration
from hpsilab_research_adapter.ledger import CreditLedger, RecordingTransport, make_template
from hpsilab_research_adapter.policy import (
    BALANCE_FLOOR,
    ENV_API_KEY,
    ENV_X402_WALLET,
    PROBE_CALL_CAP,
    PROBE_CREDIT_BUDGET,
    TOTAL_CREDIT_BUDGET,
)
from hpsilab_research_adapter.tools import TOOLS

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "schemas"
RAW = ROOT / ".probe"
PHASE = "probe"

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}([T ].*)?$")
_NUMBER = re.compile(r"^-?\d+(\.\d+)?$")


def _key_is_data(key: str, ticker: str) -> bool:
    """A dict key that is itself a value (date, number, the ticker) must not leak."""
    return bool(_DATE.match(key) or _NUMBER.match(key) or key.upper() == ticker.upper())


def shape(value: Any, ticker: str) -> Any:
    """Replace every value with its JSON type; collapse value-like keys into a map."""
    if isinstance(value, dict):
        keys = list(value)
        if keys and (
            sum(_key_is_data(str(k), ticker) for k in keys) * 2 > len(keys) or len(keys) > 60
        ):
            merged = _merge([shape(v, ticker) for v in value.values()])
            return {"type": "map", "key_count_observed": len(keys), "values": merged}
        return {
            "type": "object",
            "keys": {
                ("<TICKER>" if str(k).upper() == ticker.upper() else str(k)): shape(v, ticker)
                for k, v in value.items()
            },
        }
    if isinstance(value, list):
        return {
            "type": "array",
            "items": _merge([shape(v, ticker) for v in value]) if value else None,
        }
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    return type(value).__name__


def _merge(shapes: list[Any]) -> Any:
    """Merge element shapes: union object keys, collect distinct scalar types."""
    objects = [s for s in shapes if isinstance(s, dict) and s.get("type") == "object"]
    others = []
    for s in shapes:
        if not (isinstance(s, dict) and s.get("type") == "object") and s not in others:
            others.append(s)
    variants = list(others)
    if objects:
        keys: dict[str, list[Any]] = {}
        for obj in objects:
            for k, v in obj["keys"].items():
                keys.setdefault(k, []).append(v)
        merged = {
            "type": "object",
            "keys": {k: _merge(vs) for k, vs in keys.items()},
            "optional_keys": sorted(k for k, vs in keys.items() if len(vs) < len(objects)),
        }
        if not merged["optional_keys"]:
            del merged["optional_keys"]
        variants.append(merged)
    if len(variants) == 1:
        return variants[0]
    return {"anyOf": variants}


def unwrap(result: Any) -> tuple[Any, Any]:
    """Split McpToolResult(data, metadata) when include_metadata was used."""
    if hasattr(result, "data") and hasattr(result, "metadata"):
        meta = result.metadata
        if hasattr(meta, "__dict__") and not isinstance(meta, dict):
            meta = {k: v for k, v in vars(meta).items() if not k.startswith("_")}
        return result.data, meta
    return result, None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ticker", default="NVDA")
    args = parser.parse_args(argv)
    ticker = args.ticker.upper()

    if os.environ.get(ENV_X402_WALLET):
        raise UnsafeConfiguration(f"{ENV_X402_WALLET} is set; refusing to run (could pay USDC).")
    api_key = os.environ.get(ENV_API_KEY)
    if not api_key:
        raise AuthError(f"{ENV_API_KEY} is not set; refusing to create the client.")

    ledger = CreditLedger(ROOT / ".credits" / "ledger.json")
    transport = RecordingTransport(
        ledger,
        PHASE,
        budget=PROBE_CREDIT_BUDGET,
        call_cap=PROBE_CALL_CAP,
        total_budget=TOTAL_CREDIT_BUDGET,
        floor=BALANCE_FLOOR,
    )
    client = HpsiMcpClient(api_key=api_key, transport=transport, payment_mode=CREDITS_ONLY)
    template = make_template(DEFAULT_BASE_URL, api_key)
    del api_key
    if client.payment_policy.pays:
        raise UnsafeConfiguration("SDK payment policy would pay per call; refusing to run.")

    SCHEMAS.mkdir(exist_ok=True)
    RAW.mkdir(exist_ok=True)
    report = []

    # Step 1: prove the credit endpoints are free before relying on them.
    names = {s.name for s in TOOLS.values()} | {s.sdk_method for s in TOOLS.values()}
    free = transport.verify_meta_free(template, names)
    for spec in TOOLS.values():  # key prices by SDK tool name, whichever name matched
        if spec.sdk_method not in transport.prices and spec.name in transport.prices:
            transport.prices[spec.sdk_method] = transport.prices[spec.name]
    print(
        f"credit endpoints: free={free['free']} statuses={free['statuses']} "
        f"balances={free['balances']} charged={free['charged_headers']}"
    )
    print(f"catalog prices (SDK tool -> credits): {free['prices']}")
    if not free["free"]:
        print("STOPPED before any tool call: credit endpoints not proven free.")
        client.close()
        return 1
    start_balance = free["balances"][-1]

    try:
        for spec in TOOLS.values():
            transport.context = {"tool": spec.sdk_method, "ticker": ticker}
            method = getattr(client, spec.sdk_method)
            kwargs = {"include_metadata": True} if spec.supports_metadata else {}
            outcome = "ok"
            try:
                data, meta = unwrap(method(ticker, **kwargs))
            except CreditBudgetExceeded as stop:
                report.append((spec.name, f"STOPPED: {stop}"))
                break
            except HpsiMcpError as err:
                outcome = f"{type(err).__name__} (status {getattr(err, 'status_code', None)})"
                report.append((spec.name, outcome))
                if ledger.blind:
                    break
                continue
            (RAW / f"{spec.name}.raw.json").write_text(
                json.dumps({"data": data, "metadata": meta}, indent=2, default=str),
                encoding="utf-8",
            )
            doc = {
                "tool": spec.name,
                "sdk_method": spec.sdk_method,
                "sdk_version": "hpsilab-mcp 0.14.2",
                "probed_ticker": "<TICKER>",
                "note": "Keys and JSON types only. No values. Generated by tools/probe.py.",
                "data": shape(data, ticker),
            }
            if meta is not None:
                doc["metadata"] = shape(meta, ticker)
            (SCHEMAS / f"{spec.name}.shape.json").write_text(
                json.dumps(doc, indent=2) + "\n", encoding="utf-8"
            )
            report.append((spec.name, outcome))
            if ledger.blind:
                report.append(("-", "STOPPED: no credit balance header on the response"))
                break
    finally:
        end_balance = transport.read_balance(template)
        client.close()

    print(f"ticker={ticker}")
    for name, outcome in report:
        print(f"  {name:20s} {outcome}")
    per_call = [(e.tool, e.status, e.cost) for e in ledger.entries if e.phase == PHASE]
    print(f"per call (tool, status, credits): {per_call}")
    print(
        f"probe tool calls={ledger.calls(PHASE)} credits={ledger.spent(PHASE)} "
        f"(unknown-cost={ledger.unknown_cost_calls(PHASE)}) "
        f"balance {start_balance} -> {end_balance} "
        f"(endpoint delta {None if None in (start_balance, end_balance) else start_balance - end_balance}) "
        f"blind={ledger.blind}"
    )
    seen = sorted({n for e in ledger.entries for n in e.credit_header_names})
    print(f"credit-related response header names seen: {seen}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
