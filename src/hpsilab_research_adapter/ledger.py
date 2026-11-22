"""Credit ledger and header-recording transport. Orchestrator-owned shared infrastructure.

HPSILab bills in Credits. Responses carry ``X-Credits-Charged`` and
``X-Credits-Remaining`` (hpsilab-mcp README); ``GET /api/credits/catalog`` lists
tool prices and ``GET /api/credits/balance`` returns the balance. The SDK exposes
none of this, so ``RecordingTransport`` wraps the httpx transport handed to
``HpsiMcpClient(transport=...)``.

Before every tool request ``CreditLedger.authorize`` checks, using the catalog
price when known (else the largest cost seen so far, else 1):
  * the per-run call cap and credit budget,
  * an optional total budget across runs (the persisted ledger),
  * an optional balance floor, against the last balance HPSILab reported.
After every response the cost is taken from ``X-Credits-Charged``, else from the
balance difference. If no balance header is present the transport asks the
balance endpoint; only if that also fails does the ledger go blind, and a blind
ledger refuses every later request.

Credit-endpoint reads (``/api/credits/*``) are recorded under ``<phase>:meta``.
They do not count toward call caps; any cost they show is still counted.

Records hold counts only. No response bodies, no credentials.
"""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from hpsilab_research_adapter.errors import CreditBudgetExceeded
from hpsilab_research_adapter.policy import CREDITS_HEADER

DEFAULT_LEDGER_PATH = Path(".credits") / "ledger.json"
CHARGED_HEADER = "X-Credits-Charged"
BALANCE_PATH = "/api/credits/balance"
CATALOG_PATH = "/api/credits/catalog"

_BALANCE_KEYS = ("credits_remaining", "remaining", "balance", "credits", "available")
_PRICE_KEYS = ("credits", "price", "cost", "credits_per_call", "price_credits", "credit_cost")
_NAME_KEYS = ("tool", "tool_name", "name", "id", "slug", "key")


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
    charged_header: int | None = None
    balance_source: str | None = None  # "header" | "endpoint" | None
    credit_header_names: list[str] = field(default_factory=list)


class CreditLedger:
    def __init__(self, path: Path | None = DEFAULT_LEDGER_PATH) -> None:
        self.path = path
        self._lock = threading.RLock()
        self.entries: list[Entry] = []
        self.blind = False
        self.meta_free_verified = False
        if path is not None and path.exists():
            raw = json.loads(path.read_text(encoding="utf-8"))
            self.entries = [Entry(**e) for e in raw.get("entries", [])]
            self.blind = bool(raw.get("blind", False))
            self.meta_free_verified = bool(raw.get("meta_free_verified", False))

    # ---- queries -------------------------------------------------------
    @property
    def last_balance(self) -> int | None:
        for entry in reversed(self.entries):
            if entry.balance_after is not None:
                return entry.balance_after
        return None

    @property
    def max_cost(self) -> int:
        costs = [e.cost for e in self.entries if e.cost]
        return max(costs) if costs else 1

    def _match(self, entry: Entry, phase: str | None, include_meta: bool) -> bool:
        if phase is None:
            return include_meta or not entry.phase.endswith(":meta")
        if entry.phase == phase:
            return True
        return include_meta and entry.phase == f"{phase}:meta"

    def spent(self, phase: str | None = None) -> int:
        """Credits spent, meta reads included. Unknown cost counts at the largest cost seen."""
        return sum(
            e.cost if e.cost is not None else self.max_cost
            for e in self.entries
            if self._match(e, phase, include_meta=True)
        )

    def calls(self, phase: str | None = None) -> int:
        """Tool calls only; credit-endpoint reads are excluded."""
        return sum(1 for e in self.entries if self._match(e, phase, include_meta=False))

    def unknown_cost_calls(self, phase: str | None = None) -> int:
        return sum(
            1 for e in self.entries if e.cost is None and self._match(e, phase, include_meta=True)
        )

    # ---- enforcement ---------------------------------------------------
    def authorize(
        self,
        phase: str,
        *,
        budget: int,
        call_cap: int,
        price: int | None = None,
        total_budget: int | None = None,
        floor: int | None = None,
    ) -> None:
        """Raise CreditBudgetExceeded unless one more tool request is within every limit."""
        with self._lock:
            reserve = price if price is not None else self.max_cost
            balance = self.last_balance
            checks = [
                (self.blind, "credit balance unknown after an earlier response"),
                (self.calls(phase) >= call_cap, f"{phase} call cap {call_cap} reached"),
                (self.spent(phase) + reserve > budget, f"{phase} credit budget {budget}"),
                (
                    total_budget is not None and self.spent() + reserve > total_budget,
                    f"total credit budget {total_budget}",
                ),
                (
                    floor is not None and balance is not None and balance - reserve < floor,
                    f"balance floor {floor}",
                ),
            ]
            for failed, reason in checks:
                if failed:
                    raise CreditBudgetExceeded(
                        f"Refusing request: {reason}.",
                        spent=self.spent(phase),
                        budget=budget,
                        balance=balance,
                        floor=floor,
                    )

    def record(
        self,
        phase: str,
        *,
        tool: str | None,
        ticker: str | None,
        status: int,
        balance_after: int | None,
        charged: int | None = None,
        balance_source: str | None = None,
        credit_header_names: list[str] | None = None,
    ) -> Entry:
        with self._lock:
            meta = phase.endswith(":meta")
            before = self.last_balance
            cost = charged
            if cost is None and before is not None and balance_after is not None:
                cost = max(0, before - balance_after)
            if cost is None and status >= 400:
                cost = 0  # HPSILab: "a call that fails is never charged"
            if cost is None and meta and self.meta_free_verified:
                cost = 0
            entry = Entry(
                at=datetime.now(UTC).isoformat(timespec="seconds"),
                phase=phase,
                tool=tool,
                ticker=ticker,
                status=status,
                balance_before=before,
                balance_after=balance_after,
                cost=cost,
                charged_header=charged,
                balance_source=balance_source,
                credit_header_names=credit_header_names or [],
            )
            self.entries.append(entry)
            if balance_after is None and charged is None and not meta:
                self.blind = True
            self._save()
            return entry

    def mark_meta_free(self) -> None:
        """Call only after verify_meta_free showed the credit endpoints cost 0."""
        with self._lock:
            self.meta_free_verified = True
            for e in self.entries:
                if e.phase.endswith(":meta") and e.cost is None:
                    e.cost = 0
            self._save()

    def _save(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        payload = {
            "blind": self.blind,
            "meta_free_verified": self.meta_free_verified,
            "entries": [asdict(e) for e in self.entries],
        }
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)


# ---- parsing (formats of the credit endpoints are undocumented; parse tolerantly) ----
def _int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        try:
            return int(float(value.strip()))
        except ValueError:
            return None
    return None


def header_int(headers: httpx.Headers, name: str) -> int | None:
    raw = headers.get(name)
    return None if raw is None else _int(raw)


def parse_balance(headers: httpx.Headers) -> int | None:
    return header_int(headers, CREDITS_HEADER)


def parse_balance_body(body: Any) -> int | None:
    """Find the balance in a /api/credits/balance body: top level or one level down."""
    if not isinstance(body, Mapping):
        return _int(body)
    for key in _BALANCE_KEYS:
        if key in body and _int(body[key]) is not None:
            return _int(body[key])
    for value in body.values():
        if isinstance(value, Mapping):
            for key in _BALANCE_KEYS:
                if key in value and _int(value[key]) is not None:
                    return _int(value[key])
    return None


def parse_catalog(body: Any, tool_names: set[str]) -> dict[str, int]:
    """Map SDK tool name -> credit price from a /api/credits/catalog body, best effort."""
    prices: dict[str, int] = {}

    def price_of(value: Any) -> int | None:
        if isinstance(value, Mapping):
            for key in _PRICE_KEYS:
                if key in value and _int(value[key]) is not None:
                    return _int(value[key])
            return None
        return _int(value)

    def walk(node: Any) -> None:
        if isinstance(node, Mapping):
            for key, value in node.items():
                if key in tool_names and price_of(value) is not None:
                    prices.setdefault(key, price_of(value))  # type: ignore[arg-type]
            for nk in _NAME_KEYS:
                name = node.get(nk)
                if isinstance(name, str) and name in tool_names:
                    p = price_of(node)
                    if p is not None:
                        prices.setdefault(name, p)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(body)
    return prices


class RecordingTransport(httpx.BaseTransport):
    """Wraps the real transport; authorizes before and records after each request.

    Set ``context`` (``tool`` = SDK tool name, ``ticker``) before each SDK call.
    ``prices`` maps SDK tool name -> credits; fill it with ``load_catalog``.
    """

    def __init__(
        self,
        ledger: CreditLedger,
        phase: str,
        *,
        budget: int,
        call_cap: int,
        total_budget: int | None = None,
        floor: int | None = None,
        inner: httpx.BaseTransport | None = None,
    ) -> None:
        self.ledger = ledger
        self.phase = phase
        self.budget = budget
        self.call_cap = call_cap
        self.total_budget = total_budget
        self.floor = floor
        self.inner = inner or httpx.HTTPTransport()
        self.context: dict[str, str | None] = {"tool": None, "ticker": None}
        self.prices: dict[str, int] = {}

    # -- credit endpoints -------------------------------------------------
    def _meta_get(self, template: httpx.Request, path: str) -> tuple[httpx.Response, Any]:
        url = template.url.copy_with(path=path, query=None)
        auth = {k: v for k, v in template.headers.items() if k.lower() == "authorization"}
        req = httpx.Request("GET", url, headers=auth)
        response = self.inner.handle_request(req)
        response.read()
        try:
            body = response.json()
        except ValueError:
            body = None
        charged = header_int(response.headers, CHARGED_HEADER)
        balance = parse_balance(response.headers)
        source = "header" if balance is not None else None
        if balance is None and path == BALANCE_PATH and response.status_code < 400:
            balance = parse_balance_body(body)
            source = "endpoint" if balance is not None else None
        self.ledger.record(
            f"{self.phase}:meta",
            tool=path,
            ticker=None,
            status=response.status_code,
            balance_after=balance,
            charged=charged,
            balance_source=source,
            credit_header_names=_credit_names(response.headers),
        )
        return response, body

    def read_balance(self, template: httpx.Request) -> int | None:
        response, body = self._meta_get(template, BALANCE_PATH)
        if response.status_code >= 400:
            return None
        balance = parse_balance(response.headers)
        return balance if balance is not None else parse_balance_body(body)

    def verify_meta_free(self, template: httpx.Request, tool_names: set[str]) -> dict:
        """Read balance, balance, catalog, balance. Free iff the balance never moves and
        no X-Credits-Charged above 0 is reported. Marks the ledger on success."""
        first = self.read_balance(template)
        second = self.read_balance(template)
        self.load_catalog(template, tool_names)
        third = self.read_balance(template)
        meta = [e for e in self.ledger.entries if e.phase == f"{self.phase}:meta"][-4:]
        charged = [e.charged_header for e in meta if e.charged_header]
        balances = [first, second, third]
        free = None not in balances and len(set(balances)) == 1 and not charged
        if free:
            self.ledger.mark_meta_free()
        return {
            "free": free,
            "balances": balances,
            "charged_headers": charged,
            "statuses": [e.status for e in meta],
            "prices": dict(self.prices),
        }

    def load_catalog(self, template: httpx.Request, tool_names: set[str]) -> dict[str, int]:
        response, body = self._meta_get(template, CATALOG_PATH)
        if response.status_code < 400:
            self.prices.update(parse_catalog(body, tool_names))
        return dict(self.prices)

    # -- tool requests ----------------------------------------------------
    def handle_request(self, request: httpx.Request) -> httpx.Response:
        tool = self.context.get("tool")
        self.ledger.authorize(
            self.phase,
            budget=self.budget,
            call_cap=self.call_cap,
            price=self.prices.get(tool) if tool else None,
            total_budget=self.total_budget,
            floor=self.floor,
        )
        response = self.inner.handle_request(request)
        charged = header_int(response.headers, CHARGED_HEADER)
        balance = parse_balance(response.headers)
        source = "header" if balance is not None else None
        if balance is None:
            # Header missing: ask the balance endpoint rather than go blind.
            fallback = self._meta_balance_quiet(request)
            if fallback is not None:
                balance, source = fallback, "endpoint"
        self.ledger.record(
            self.phase,
            tool=tool,
            ticker=self.context.get("ticker"),
            status=response.status_code,
            balance_after=balance,
            charged=charged,
            balance_source=source,
            credit_header_names=_credit_names(response.headers),
        )
        return response

    def _meta_balance_quiet(self, template: httpx.Request) -> int | None:
        """Balance endpoint read whose own ledger entry must not make the ledger blind."""
        url = template.url.copy_with(path=BALANCE_PATH, query=None)
        auth = {k: v for k, v in template.headers.items() if k.lower() == "authorization"}
        try:
            response = self.inner.handle_request(httpx.Request("GET", url, headers=auth))
            response.read()
            body = response.json() if response.status_code < 400 else None
        except (httpx.HTTPError, ValueError):
            return None
        balance = parse_balance(response.headers)
        if balance is None:
            balance = parse_balance_body(body)
        if balance is not None:
            self.ledger.record(
                f"{self.phase}:meta",
                tool=BALANCE_PATH,
                ticker=None,
                status=response.status_code,
                balance_after=balance,
                charged=header_int(response.headers, CHARGED_HEADER),
                balance_source="endpoint",
                credit_header_names=_credit_names(response.headers),
            )
        return balance

    def close(self) -> None:
        self.inner.close()


def make_template(base_url: str, api_key: str) -> httpx.Request:
    """A request carrying only the auth header, used to address the credit endpoints."""
    return httpx.Request("GET", base_url, headers={"Authorization": f"Bearer {api_key}"})


def _credit_names(headers: httpx.Headers) -> list[str]:
    return sorted(k for k in headers.keys() if "credit" in k.lower())
