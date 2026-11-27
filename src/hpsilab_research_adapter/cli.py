"""Command-line interface for the HPSILab research adapter.

Research and analysis only. Read-only. This CLI never generates, approves,
submits or executes orders. It is an independent integration, not an official
or endorsed HPSILab product.

The live client is imported lazily, only when a run actually needs it, so
``--help``, ``--version`` and ``--status`` never touch the SDK or the network.
"""

from __future__ import annotations

import argparse
import dataclasses
import importlib.metadata
import json
import os
import re
import sys
import textwrap
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hpsilab_research_adapter import __version__, errors, policy, tools
from hpsilab_research_adapter.policy import MAX_ATTEMPTS
from hpsilab_research_adapter.types import Result

ClientFactory = Callable[..., Any]

PHASE = "cli"
DEFAULT_LEDGER = ".credits/ledger.json"
DEFAULT_MAX_CREDITS = 50
SDK_DISTRIBUTION = "hpsilab-mcp"
TICKER_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9.\-]{0,9}")

EXIT_OK = 0
EXIT_ERROR = 1  # any other AdapterError not listed below
EXIT_USAGE = 2
EXIT_AUTH = 3
EXIT_CREDITS = 4
EXIT_UPSTREAM = 5

_EXIT_CODES: tuple[tuple[type[errors.AdapterError], int], ...] = (
    (errors.AuthError, EXIT_AUTH),
    (errors.UnsafeConfiguration, EXIT_AUTH),
    (errors.CreditsExhausted, EXIT_CREDITS),
    (errors.CreditBudgetExceeded, EXIT_CREDITS),
    (errors.RateLimited, EXIT_UPSTREAM),
    (errors.Timeout, EXIT_UPSTREAM),
    (errors.UpstreamError, EXIT_UPSTREAM),
)

# Failures of one (ticker, tool) call: record, report, carry on with the next call.
_PER_CALL_ERRORS = (errors.RateLimited, errors.Timeout, errors.UpstreamError)

DESCRIPTION = (
    "HPSILab research-only CLI. Research and analysis only. The tool is read-only:\n"
    "it never generates, approves, submits or executes orders.\n"
    "Independent, unverified third-party integration, not an official or endorsed HPSILab product."
)
EPILOG = (
    "Live runs need HPSILAB_API_KEY in the environment. Use --status to check\n"
    "configuration without any network access. Every live request is counted\n"
    "against the credit budget (see --max-credits, --min-balance, --total-credits)."
)


def _ticker(raw: str) -> str:
    if not TICKER_PATTERN.fullmatch(raw):
        raise argparse.ArgumentTypeError(f"invalid ticker {raw!r}")
    return raw.upper()


def _non_negative_int(raw: str) -> int:
    try:
        value = int(raw)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected an integer, got {raw!r}") from None
    if value < 0:
        raise argparse.ArgumentTypeError(f"must be 0 or more, got {value}")
    return value


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hpsilab-research",
        description=DESCRIPTION,
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "tickers",
        nargs="*",
        type=_ticker,
        metavar="TICKER",
        help="ticker symbol(s), for example NVDA MSFT",
    )
    parser.add_argument(
        "--tool",
        choices=("all", *tools.TOOL_NAMES),
        default="all",
        help="research tool to run (default: all)",
    )
    parser.add_argument("--json", action="store_true", help="print a JSON array, not text")
    parser.add_argument(
        "--max-credits",
        type=_non_negative_int,
        default=DEFAULT_MAX_CREDITS,
        metavar="N",
        help=(
            f"credit cap for this run (default: {DEFAULT_MAX_CREDITS}; "
            "one pass over all six tools was observed to cost 38 credits)"
        ),
    )
    parser.add_argument(
        "--min-balance",
        type=_non_negative_int,
        default=None,
        metavar="N",
        help="stop if the account balance would drop below N (default: none)",
    )
    parser.add_argument(
        "--total-credits",
        type=_non_negative_int,
        default=None,
        metavar="N",
        help="total credit budget across runs, needs the ledger (default: none)",
    )
    ledger = parser.add_mutually_exclusive_group()
    ledger.add_argument(
        "--ledger",
        default=DEFAULT_LEDGER,
        metavar="PATH",
        help=f"credit ledger file (default: {DEFAULT_LEDGER}, relative to the current directory)",
    )
    ledger.add_argument("--no-ledger", action="store_true", help="do not persist a credit ledger")
    parser.add_argument(
        "--status", action="store_true", help="show configuration status, no network access"
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def _sdk_version() -> str:
    try:
        return importlib.metadata.version(SDK_DISTRIBUTION)
    except importlib.metadata.PackageNotFoundError:
        return "not installed"


def _print_status() -> None:
    # Only a yes/no for the key is printed. Its value never leaves os.environ.
    key_set = "yes" if os.environ.get(policy.ENV_API_KEY) else "no"
    print(f"hpsilab-research {__version__} (research-only, read-only)")
    print("Research and analysis only. Never generates, approves, submits or executes orders.")
    print("Tools:")
    for name in tools.TOOL_NAMES:
        print(f"  - {name}")
    print(f"{policy.ENV_API_KEY} set: {key_set}")
    print(f"SDK version ({SDK_DISTRIBUTION}): {_sdk_version()}")


def _print_text_block(result: Result) -> None:
    horizon = result.horizon if result.horizon is not None else "n/a"
    missing = ", ".join(result.missing_fields) if result.missing_fields else "none"
    print(f"== {result.tool} {result.ticker} ==")
    print(f"  horizon: {horizon}")
    print(f"  source_fields: {len(result.source_fields)}")
    print(f"  missing_fields: {missing}")
    print("  data:")
    body = json.dumps(result.data, indent=2, sort_keys=True, default=str)
    print(textwrap.indent(body, "    "))
    print()


def _emit(results: Sequence[Result], *, as_json: bool) -> None:
    if as_json:
        rows = [dataclasses.asdict(result) for result in results]
        print(json.dumps(rows, indent=2, default=str))
        return
    for result in results:
        _print_text_block(result)


def _exit_code_for(exc: errors.AdapterError) -> int:
    for error_cls, code in _EXIT_CODES:
        if isinstance(exc, error_cls):
            return code
    return EXIT_ERROR


def _load_client_factory() -> ClientFactory:
    # Lazy on purpose: only the run path needs the SDK-backed client.
    from hpsilab_research_adapter.client import ResearchClient

    return ResearchClient.from_env


def main(argv: Sequence[str] | None = None, *, client_factory: ClientFactory | None = None) -> int:
    """Run the research CLI. Tests inject ``client_factory``; the default is the real client."""
    parser = _build_parser()
    args = parser.parse_intermixed_args(argv)

    if args.status:
        _print_status()
        return EXIT_OK
    if not args.tickers:
        parser.print_help()
        return EXIT_OK

    if args.no_ledger and args.total_credits is not None:
        parser.error(
            "--total-credits needs the persisted ledger; it cannot be used with --no-ledger"
        )

    tickers = list(dict.fromkeys(args.tickers))
    tool_names = tools.TOOL_NAMES if args.tool == "all" else (args.tool,)
    planned = [(ticker, tool) for ticker in tickers for tool in tool_names]
    ledger_path = None if args.no_ledger else Path(args.ledger)

    factory = client_factory if client_factory is not None else _load_client_factory()
    results: list[Result] = []
    failed_calls = 0
    stopping: errors.AdapterError | None = None
    try:
        try:
            # Per-run phase id: --max-credits and the call cap are per run, while the
            # persisted ledger still enforces --total-credits across all runs.
            run_phase = f"{PHASE}-{datetime.now(UTC):%Y%m%dT%H%M%S}-{os.getpid()}"
            client = factory(
                phase=run_phase,
                ledger_path=ledger_path,
                max_credits=args.max_credits,
                # Every attempt, retries included, passes through the ledger's call cap.
                call_cap=len(planned) * MAX_ATTEMPTS,
                total_budget=args.total_credits,
                min_balance=args.min_balance,
            )
            try:
                for ticker, tool in planned:
                    try:
                        results.append(client.run(tool, ticker))
                    except _PER_CALL_ERRORS as exc:
                        # Only this call failed; later calls may still succeed.
                        failed_calls += 1
                        print(
                            f"error: {type(exc).__name__}: {exc} ({ticker} {tool})",
                            file=sys.stderr,
                        )
            finally:
                client.close()
        except errors.AdapterError as exc:
            # Auth, unsafe configuration and credit errors affect every later call.
            stopping = exc
            print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
    finally:
        # Completed results are always emitted, also when an unexpected exception
        # is propagating (it is not swallowed).
        _emit(results, as_json=args.json)

    if stopping is not None:
        return _exit_code_for(stopping)
    return EXIT_UPSTREAM if failed_calls else EXIT_OK
