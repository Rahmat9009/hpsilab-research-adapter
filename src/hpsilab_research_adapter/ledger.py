"""Credit ledger and header-recording transport. Shared infrastructure (Phase 1/2).

The SDK does not expose response headers, so ``RecordingTransport`` wraps the
httpx transport handed to ``HpsiMcpClient(transport=...)`` and reads the
credit balance header on every response, including error responses.

``CreditLedger`` persists across processes in ``.credits/ledger.json``
(gitignored) so the 150-credit total holds over the probe, tests and ship check.
It records counts only: phase, tool, ticker, HTTP status, balance before/after.
No response bodies, no credentials.

Enforcement happens BEFORE each request, in ``authorize``:
  * the phase call cap and credit budget, and the total budget,
  * the balance floor, using the last balance HPSILab reported,
  * a reserve equal to the most expensive call observed so far, so a call is
    refused if it could cross a budget. Before any cost is known the reserve
    is 1 credit, so at most one call's cost can overrun a budget.
If a response carries no balance header, ``record`` marks the ledger blind and
every later ``authorize`` refuses. Spending we cannot count is not allowed.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import httpx

from hpsilab_research_adapter.errors import CreditBudgetExceeded
from hpsilab_research_adapter.policy import BALANCE_FLOOR, CREDITS_HEADER, TOTAL_CREDIT_BUDGET

DEFAULT_LEDGER_PATH = Path(".credits") / "ledger.json"


@dataclass
class Entry:
    at: str
    phase: str
    tool: str | None
    ticker: str | None
    status: int
    balance_before: int | None
    balance_after: int | None
    cost: int | None
    credit_header_names: list[str] = field(default_factory=list)


class CreditLedger:
    def __init__(self, path: Path | None = DEFAULT_LEDGER_PATH) -> None:
        self.path = path
        self._lock = threading.Lock()
        self.entries: list[Entry] = []
        self.blind = False
        if path is not None and path.exists():
            raw = json.loads(path.read_text(encoding="utf-8"))
            self.entries = [Entry(**e) for e in raw.get("entries", [])]
            self.blind = bool(raw.get("blind", False))

    # ---- queries -------------------------------------------------------
    @property
    def last_balance(self) -> int | None:
        for entry in reversed(self.entries):
            if entry.balance_after is not None:
                return entry.balance_after
        return None

    def spent(self, phase: str | None = None) -> int:
        """Credits spent. A call with unknown cost (e.g. the very first one, which has
        no earlier balance to diff against) is counted at the largest cost seen."""
        return sum(
            e.cost if e.cost is not None else self.max_cost
            for e in self.entries
            if phase is None or e.phase == phase
        )

    def unknown_cost_calls(self, phase: str | None = None) -> int:
        return sum(
            1 for e in self.entries if e.cost is None and (phase is None or e.phase == phase)
        )

    def calls(self, phase: str | None = None) -> int:
        return sum(1 for e in self.entries if phase is None or e.phase == phase)

    @property
    def max_cost(self) -> int:
        costs = [e.cost for e in self.entries if e.cost]
        return max(costs) if costs else 1

    # ---- enforcement ---------------------------------------------------
    def authorize(self, phase: str, *, budget: int, call_cap: int) -> None:
        """Raise CreditBudgetExceeded unless one more request is within every limit."""
        with self._lock:
            reserve = self.max_cost
            checks = [
                (self.blind, "credit balance header missing on an earlier response"),
                (self.calls(phase) >= call_cap, f"{phase} call cap {call_cap} reached"),
                (self.spent(phase) + reserve > budget, f"{phase} credit budget {budget}"),
                (
                    self.spent() + reserve > TOTAL_CREDIT_BUDGET,
                    f"total credit budget {TOTAL_CREDIT_BUDGET}",
                ),
                (
                    self.last_balance is not None and self.last_balance - reserve < BALANCE_FLOOR,
                    f"balance floor {BALANCE_FLOOR}",
                ),
            ]
            for failed, reason in checks:
                if failed:
                    raise CreditBudgetExceeded(
                        f"Refusing request: {reason}.",
                        spent=self.spent(phase),
                        budget=budget,
                        balance=self.last_balance,
                        floor=BALANCE_FLOOR,
                    )

    def record(
        self,
        phase: str,
        *,
        tool: str | None,
        ticker: str | None,
        status: int,
        balance_after: int | None,
        credit_header_names: list[str],
    ) -> Entry:
        with self._lock:
            before = self.last_balance
            cost = None
            if before is not None and balance_after is not None:
                cost = max(0, before - balance_after)
            entry = Entry(
                at=datetime.now(UTC).isoformat(timespec="seconds"),
                phase=phase,
                tool=tool,
                ticker=ticker,
                status=status,
                balance_before=before,
                balance_after=balance_after,
                cost=cost,
                credit_header_names=credit_header_names,
            )
            self.entries.append(entry)
            if balance_after is None:
                self.blind = True
            self._save()
            return entry

    def _save(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        payload = {"blind": self.blind, "entries": [asdict(e) for e in self.entries]}
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)


def parse_balance(headers: httpx.Headers) -> int | None:
    raw = headers.get(CREDITS_HEADER)
    if raw is None:
        return None
    try:
        return int(float(raw.strip()))
    except ValueError:
        return None


class RecordingTransport(httpx.BaseTransport):
    """Wraps the real transport; authorizes before and records after each request.

    ``context`` is set by the caller before each SDK call so the ledger entry
    names the tool and ticker. The first call has unknown cost: the ledger
    authorizes it with a 1-credit reserve.
    """

    def __init__(
        self,
        ledger: CreditLedger,
        phase: str,
        *,
        budget: int,
        call_cap: int,
        inner: httpx.BaseTransport | None = None,
    ) -> None:
        self.ledger = ledger
        self.phase = phase
        self.budget = budget
        self.call_cap = call_cap
        self.inner = inner or httpx.HTTPTransport()
        self.context: dict[str, str | None] = {"tool": None, "ticker": None}

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.ledger.authorize(self.phase, budget=self.budget, call_cap=self.call_cap)
        response = self.inner.handle_request(request)
        names = sorted(k for k in response.headers.keys() if "credit" in k.lower())
        self.ledger.record(
            self.phase,
            tool=self.context.get("tool"),
            ticker=self.context.get("ticker"),
            status=response.status_code,
            balance_after=parse_balance(response.headers),
            credit_header_names=names,
        )
        return response

    def close(self) -> None:
        self.inner.close()
