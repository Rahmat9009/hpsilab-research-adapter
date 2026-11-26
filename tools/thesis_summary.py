"""Share-safe Markdown summary of a thesis report JSON, for an external reviewer.

Usage:  python tools/thesis_summary.py PATH_TO_REPORT.json
        python tools/thesis_summary.py --help

The input is the file tools/thesis_demo.py (or thesis.to_dict) writes. The output
contains only field names, stance labels, horizon statuses, rule text, counts and
reasons. It never contains an observed value from an HPSILab response: the "observed"
and "source_horizon" entries of the report are never read, and every string that is
printed is either a constant of this project or checked against a fixed whitelist.

Research only. Not a recommendation. Independent, unverified third-party
integration, not verified or endorsed by HPSILab.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from hpsilab_research_adapter import errors, thesis, tools

_ERROR_CLASS_NAMES = frozenset(
    name
    for name, obj in vars(errors).items()
    if isinstance(obj, type) and issubclass(obj, Exception)
) | {"Exception", "ValueError", "TypeError", "KeyError", "RuntimeError", "OSError"}
_KNOWN_DETAILS = frozenset(
    {
        "not a Result",
        "expected a number 0-1",
        "expected a number",
        "expected numbers",
        "expected lists",
        "expected a word",
        "expected lower and upper numbers",
        "unrecognised signal word",
        "unexpected type",
        "no result",
    }
)
_KNOWN_REASONS = (
    thesis.REASON_TOOL_FAILED,
    thesis.REASON_FIELD_MISSING,
    thesis.REASON_UNPARSEABLE,
)
_KNOWN_RULES = frozenset(thesis.RULE_TEXT.values())
_PLACEHOLDER = "(not recognised)"


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _field(value: Any) -> str:
    if isinstance(value, str) and value in thesis.FIELD_NAMES:
        return value
    return _PLACEHOLDER


def _tool(value: Any) -> str | None:
    return value if isinstance(value, str) and value in tools.TOOL_NAMES else None


def _choice(value: Any, allowed: tuple[str, ...]) -> str:
    return value if isinstance(value, str) and value in allowed else _PLACEHOLDER


def _detail(value: Any) -> str | None:
    """A fixed message or a known exception class name; anything else is dropped."""
    if isinstance(value, str) and (value in _KNOWN_DETAILS or value in _ERROR_CLASS_NAMES):
        return value
    return None


def summarize(report: Any) -> str:
    """Markdown summary of a report dict. Raises ValueError on an unusable report."""
    if not isinstance(report, dict) or not isinstance(report.get("thesis"), dict):
        raise ValueError("not a thesis report")
    try:
        stated = thesis.Thesis(
            report["thesis"].get("ticker"),
            report["thesis"].get("direction"),
            report["thesis"].get("horizon_days"),
        )
    except (ValueError, AttributeError) as exc:
        raise ValueError("not a thesis report") from exc

    evidence = [e for e in _as_list(report.get("evidence")) if isinstance(e, dict)]
    missing = [m for m in _as_list(report.get("missing")) if isinstance(m, dict)]

    failed_tools: dict[str, str | None] = {}
    for m in missing:
        name = _tool(m.get("tool"))
        if name is not None and m.get("field") is None:
            failed_tools[name] = _detail(m.get("detail"))

    lines = [
        f"# Thesis evidence summary: {stated.ticker}",
        "",
        f"Stated by the user: direction **{stated.direction}**, horizon "
        f"**{stated.horizon_days}** days.",
        "",
        f"> {thesis.DISCLAIMER}",
        "",
        "This summary lists field names, labels, rules, counts and reasons only. It "
        "contains no value observed in any HPSILab response.",
        "",
        "## Tool outcomes",
        "",
    ]
    for name in tools.TOOL_NAMES:
        if name in failed_tools:
            detail = failed_tools[name]
            lines.append(f"- {name}: failed" + (f" ({detail})" if detail else ""))
        else:
            lines.append(f"- {name}: succeeded")
    succeeded = len(tools.TOOL_NAMES) - len(failed_tools)
    lines += ["", f"{succeeded} of {len(tools.TOOL_NAMES)} tools succeeded.", ""]

    credits = report.get("credits_used")
    if isinstance(credits, int) and not isinstance(credits, bool) and credits >= 0:
        lines += [f"Credits used for this run: {credits}", ""]

    tallies = {
        "matching_or_unstated_horizon": dict.fromkeys(thesis.STANCES, 0),
        "different_horizon": dict.fromkeys(thesis.STANCES, 0),
    }
    lines += ["## Fields used", ""]
    shown = 0
    for e in evidence:
        name = _tool(e.get("tool"))
        stance = _choice(e.get("stance"), thesis.STANCES)
        status = _choice(e.get("horizon_status"), thesis.HORIZON_STATUSES)
        if name is None or stance == _PLACEHOLDER:
            continue
        bucket = "different_horizon" if status == "different" else "matching_or_unstated_horizon"
        tallies[bucket][stance] += 1
        rule = e.get("rule")
        rule_text = rule if isinstance(rule, str) and rule in _KNOWN_RULES else _PLACEHOLDER
        lines += [
            f"- **{name}** `{_field(e.get('field'))}`",
            f"  - stance: {stance}; horizon status: {status}",
            f"  - rule: {rule_text}",
        ]
        shown += 1
    if not shown:
        lines.append("No evidence could be evaluated.")

    lines += ["", "## Tallies per stance", ""]
    lines += [
        "| Horizon | " + " | ".join(thesis.STANCES) + " |",
        "|---|" + "---|" * len(thesis.STANCES),
    ]
    for bucket, label in (
        ("matching_or_unstated_horizon", "matching or unstated"),
        ("different_horizon", "different"),
    ):
        counts = " | ".join(str(tallies[bucket][s]) for s in thesis.STANCES)
        lines.append(f"| {label} | {counts} |")

    lines += ["", "## Missing", ""]
    shown_missing = 0
    for m in missing:
        name = _tool(m.get("tool"))
        if name is None:
            continue
        reason = _choice(m.get("reason"), _KNOWN_REASONS)
        field_name = m.get("field")
        target = name if field_name is None else f"{name} `{_field(field_name)}`"
        detail = _detail(m.get("detail"))
        lines.append(f"- {target}: {reason}" + (f" ({detail})" if detail else ""))
        shown_missing += 1
    if not shown_missing:
        lines.append("Nothing missing.")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    if argv in (["-h"], ["--help"]):
        print("usage: thesis_summary.py PATH_TO_REPORT.json")
        print(
            "Share-safe summary of a thesis report: field names, labels, rules and counts "
            "only, no observed value. Research only; independent, unverified third-party "
            "integration, not verified by HPSILab."
        )
        return 0
    if len(argv) != 1:
        print("usage: thesis_summary.py PATH_TO_REPORT.json", file=sys.stderr)
        return 2
    try:
        report = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
        print(summarize(report))
    except (OSError, ValueError) as exc:
        print(f"error: {type(exc).__name__}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
