"""Normalized result type. FROZEN CONTRACT (Phase 1): do not edit in later phases."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Result:
    """One research tool's output for one ticker, after normalization.

    tool            canonical tool name from tools.py (e.g. "analyze_stock")
    ticker          upper-cased symbol that was requested
    data            normalized payload; {} when the upstream response was empty
    horizon         forecast/analysis horizon if the response states one, else None.
                    Never inferred or defaulted.
    source_fields   top-level keys present in the raw upstream response, sorted
    missing_fields  keys the probed shape expects but this response lacked, sorted
    error           None on success; otherwise the adapter error class name
                    (e.g. "RateLimited"). Never contains a message or credential.
    """

    tool: str
    ticker: str
    data: dict[str, Any] = field(default_factory=dict)
    horizon: str | None = None
    source_fields: tuple[str, ...] = ()
    missing_fields: tuple[str, ...] = ()
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


__all__ = ["Result"]
