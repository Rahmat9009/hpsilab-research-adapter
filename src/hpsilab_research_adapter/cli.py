"""Offline entry point. Research commands await the approved SDK interface."""

import argparse
from collections.abc import Sequence

from hpsilab_research_adapter import __version__


def main(argv: Sequence[str] | None = None) -> int:
    """Display scaffold help or status without credentials, SDK imports, or network access."""
    parser = argparse.ArgumentParser(
        prog="hpsilab",
        description="HPSILab research-only CLI scaffold. All operation is currently offline.",
        epilog="Research commands await Faisal's approved SDK methods and response schemas.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--status", action="store_true", help="show offline scaffold and implementation status"
    )
    args = parser.parse_args(argv)
    if args.status:
        print("Offline scaffold: SDK client, research commands, and response schemas pending.")
        print("Research use only. No trading, authorization, broker, or Mizan integration.")
    else:
        parser.print_help()
    return 0
