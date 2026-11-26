"""Credit ledger and recording transport. Orchestrator-owned shared infrastructure.

HPSILab bills in Credits. Responses carry ``X-Credits-Charged`` and
``X-Credits-Remaining`` (hpsilab-mcp README). ``GET /api/credits/catalog`` lists
tool prices and ``GET /api/credits/balance`` returns the balance. The SDK exposes
none of this, so ``RecordingTransport`` wraps the httpx transport handed to
``HpsiMcpClient(transport=...)``.

Guarantees (each is covered by tests/test_ledger.py):

* Every HTTP request the transport sends is recorded: tool calls, retries,
  credit-endpoint reads, and attempts that end in a transport exception.
* Before every tool request, ``authorize`` checks the per-run call cap and
  credit budget, the optional total budget across runs, and the optional
  balance floor. The price used is the catalog price when known, else the
  largest cost seen for that tool, else ``UNKNOWN_PRICE_RESERVE``.
* A floor is never checked against an unknown balance: with a floor set and no
  known balance, the request is refused.
* A cost is never assumed to be zero without evidence. Evidence is the charged
  header, a non-negative balance difference, an HTTP error status (the SDK
  README states failed calls are not charged), or a credit-endpoint read after
  those endpoints were proven free. Anything else is unknown, and unknown costs
  count as ``UNKNOWN_PRICE_RESERVE`` (or more) in every budget sum.
* A tool request whose cost cannot be established marks the ledger blind, and a
  blind ledger refuses tool requests until a later balance read succeeds
  (``RecordingTransport.start`` does that read at the beginning of every run).
* An unreadable ledger file refuses every request rather than starting from 0,
  on every call, and never sends one.
* Every load, authorize, record and save of a persisted ledger runs under a
  cross-process lock file (``<ledger>.lock``, created with O_CREAT|O_EXCL, stdlib
  only) and re-reads the file first, so two processes never overwrite each
  other's entries. If the lock cannot be taken within the timeout the request is
  refused (``CreditBudgetExceeded``). A lock older than ``lock_stale_after``
  seconds is treated as left by a dead process and removed.
* If saving the file fails (``OSError``), the entry stays in memory and the ledger is
  marked unreadable, so every later request from this instance is refused and the
  unsaved charge is never dropped by a reload.
* A learned cost of 0 does not lower a tool's reserve below
  ``UNKNOWN_PRICE_RESERVE`` when the catalog has no price for it.

Known limits:
* The lock is held only while the ledger is read or written, not while a request
  is in flight. Two processes can both pass ``authorize`` before either records,
  so each can overshoot a shared budget by one in-flight call per process.
  Removing a stale lock is not atomic against another process doing the same.
* A request that times out but is billed by HPSILab after the timeout is
  attributed only through the balance: if the next response carries
  ``X-Credits-Charged`` the late charge is not attributed to any entry, so the
  ledger can under-count by that call's price. The balance and the floor check
  stay correct because they use the balance HPSILab reports.
* If the first-use verification of the credit endpoints fails (balance moved or
  unreadable), its reads stay recorded at an unknown cost, so that run is
  usually refused on its budget even though nothing was spent. This fails
  closed; the next run re-verifies.

Records hold counts only. No response bodies, no credentials.
"""

from __future__ import annotations

import json
import math
import os
import re
import threading
import time
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
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
# Reserve for a call whose price is unknown. Larger than any single tool cost
# observed on 2026-11-22 (max 15 credits, pretrade_risk_scan).
UNKNOWN_PRICE_RESERVE = 20
TRANSPORT_FAILURE = 0  # status recorded when no HTTP response arrived
LOCK_TIMEOUT_SECONDS = 10.0  # how long to wait for another process's ledger lock
LOCK_STALE_SECONDS = 30.0  # a lock file older than this is from a dead process
_LOCK_POLL_SECONDS = 0.01

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


def _is_meta(phase: str) -> bool:
    return phase.endswith(":meta")


def _validate_entry(e: Entry) -> None:
    """Reject a hand-edited or damaged entry instead of trusting it."""

    def credits(value: object, nullable: bool = True) -> bool:
        if value is None:
            return nullable
        return isinstance(value, int) and not isinstance(value, bool) and value >= 0

    ok = (
        isinstance(e.phase, str)
        and isinstance(e.status, int)
        and not isinstance(e.status, bool)
        and credits(e.cost)
        and credits(e.charged_header)
        and credits(e.balance_before)
        and credits(e.balance_after)
    )
    if not ok:
        raise ValueError("invalid ledger entry")


class _FileLock:
    """Exclusive cross-process lock: a lock file created with O_CREAT|O_EXCL.

    ``acquire`` raises ``CreditBudgetExceeded`` (fail closed) if the lock cannot
    be taken within ``timeout`` seconds. A lock file whose mtime is older than
    ``stale_after`` seconds is treated as abandoned and removed."""

    def __init__(self, path: Path, timeout: float, stale_after: float) -> None:
        self.path = path
        self.timeout = timeout
        self.stale_after = stale_after
        self._token = ""

    @staticmethod
    def _refuse(reason: str) -> CreditBudgetExceeded:
        return CreditBudgetExceeded(f"Refusing request: ledger lock {reason}.")

    def _break_if_stale(self) -> bool:
        try:
            age = time.time() - self.path.stat().st_mtime
        except FileNotFoundError:
            return True  # released meanwhile; retry at once
        except OSError:
            return False
        if age <= self.stale_after:
            return False
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            return False
        return True

    def acquire(self) -> None:
        deadline = time.monotonic() + self.timeout
        token = f"{os.getpid()}:{uuid.uuid4().hex}"
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            raise self._refuse("directory is not writable") from None
        while True:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except (FileExistsError, PermissionError) as exc:
                # Windows reports a lock file that is being deleted as PermissionError.
                # The deadline is checked on every path so no branch can spin forever.
                if time.monotonic() >= deadline:
                    raise self._refuse(f"could not be taken within {self.timeout}s") from None
                if isinstance(exc, PermissionError) and not self.path.exists():
                    # Denied although no lock file exists (unwritable directory or
                    # delete-pending file): wait, do not spin, and honour the deadline.
                    time.sleep(_LOCK_POLL_SECONDS)
                    continue
                if self._break_if_stale():
                    continue
                time.sleep(_LOCK_POLL_SECONDS)
                continue
            except OSError:
                raise self._refuse("could not be created") from None
            try:
                os.write(fd, token.encode("ascii"))
            finally:
                os.close(fd)
            self._token = token
            return

    def release(self) -> None:
        try:
            if self.path.read_text(encoding="ascii") != self._token:
                return  # taken over as stale by another process; not ours to delete
            self.path.unlink()
        except (OSError, UnicodeError):
            pass


class CreditLedger:
    def __init__(
        self,
        path: Path | None = DEFAULT_LEDGER_PATH,
        *,
        lock_timeout: float = LOCK_TIMEOUT_SECONDS,
        lock_stale_after: float = LOCK_STALE_SECONDS,
    ) -> None:
        self.path = path
        self._lock = threading.RLock()
        self._file_lock = (
            None
            if path is None
            else _FileLock(path.with_name(path.name + ".lock"), lock_timeout, lock_stale_after)
        )
        self._depth = 0
        self.entries: list[Entry] = []
        self.blind = False
        self.meta_free_verified = False
        self.unreadable = False
        if path is not None and path.exists():
            try:
                with self._locked():
                    self._load()
            except CreditBudgetExceeded:
                self.unreadable = True  # cannot read safely; fail closed

    @contextmanager
    def _locked(self) -> Iterator[None]:
        """Thread lock, plus the cross-process file lock for a persisted ledger.
        Re-entrant: the file lock is taken by the outermost call only."""
        with self._lock:
            if self._file_lock is not None and self._depth == 0:
                self._file_lock.acquire()
            self._depth += 1
            try:
                yield
            finally:
                self._depth -= 1
                if self._depth == 0 and self._file_lock is not None:
                    self._file_lock.release()

    def _load(self) -> None:
        """(Re)read the file. A missing file leaves memory as it is; an unreadable
        one sets ``unreadable`` and drops every parsed entry, so nothing downstream
        ever computes on half-validated data."""
        if self.path is None or self.unreadable or not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            entries = [Entry(**e) for e in raw.get("entries", [])]
            for e in entries:
                _validate_entry(e)
            self.blind = raw.get("blind", False) is True
            self.meta_free_verified = raw.get("meta_free_verified", False) is True
            self.entries = entries
        except (OSError, ValueError, TypeError, AttributeError):
            self.entries = []
            self.blind = False
            self.meta_free_verified = False
            self.unreadable = True  # fail closed; never silently restart at 0

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
        return max(costs) if costs else 0

    def tool_cost(self, tool: str | None) -> int | None:
        """Largest cost observed for this tool on a SUCCESSFUL (2xx) call, or None.

        Failed calls are recorded at cost 0 (they are not charged), so they say
        nothing about the tool's price and must never lower its reserve."""
        costs = [
            e.cost
            for e in self.entries
            if e.tool == tool and e.cost is not None and 200 <= e.status < 300
        ]
        return max(costs) if costs else None

    @property
    def unknown_cost_value(self) -> int:
        return max(UNKNOWN_PRICE_RESERVE, self.max_cost)

    def _match(self, entry: Entry, phase: str | None, include_meta: bool) -> bool:
        if phase is None:
            return include_meta or not _is_meta(entry.phase)
        if entry.phase == phase:
            return True
        return include_meta and entry.phase == f"{phase}:meta"

    def spent(self, phase: str | None = None) -> int:
        """Credits spent, credit-endpoint reads included. Unknown costs count high."""
        unknown = self.unknown_cost_value
        return sum(
            e.cost if e.cost is not None else unknown
            for e in self.entries
            if self._match(e, phase, include_meta=True)
        )

    def calls(self, phase: str | None = None) -> int:
        """Tool requests (attempts) only; credit-endpoint reads are excluded."""
        return sum(1 for e in self.entries if self._match(e, phase, include_meta=False))

    def unknown_cost_calls(self, phase: str | None = None) -> int:
        return sum(
            1 for e in self.entries if e.cost is None and self._match(e, phase, include_meta=True)
        )

    # ---- enforcement ---------------------------------------------------
    def reserve_for(self, tool: str | None, price: int | None) -> int:
        if price is not None:
            return price
        seen = self.tool_cost(tool)
        # A learned 0 is not evidence the tool is free (iv_radar once charged 0 and
        # was later priced above 0); only a catalog price, handled above, may
        # reserve less than the unknown-price reserve.
        return seen if seen else self.unknown_cost_value

    def authorize(
        self,
        phase: str,
        *,
        budget: int,
        call_cap: int,
        price: int | None = None,
        tool: str | None = None,
        total_budget: int | None = None,
        floor: int | None = None,
        balance: int | None | object = ...,
    ) -> None:
        """Raise CreditBudgetExceeded unless one more tool request is within every limit.

        ``balance`` is the balance to check the floor against. The transport passes
        only a balance observed during the current run, so a balance persisted by
        an earlier run is never trusted for the floor. It defaults to the ledger's
        last balance for direct callers."""
        with self._locked():
            self._load()
            if self.unreadable:
                raise CreditBudgetExceeded(
                    "Refusing request: ledger file is unreadable; fix or move it.",
                    budget=budget,
                    floor=floor,
                )
            reserve = self.reserve_for(tool, price)
            balance = self.last_balance if balance is ... else balance
            checks = [
                (self.blind, "credit balance unknown after an earlier response"),
                (self.calls(phase) >= call_cap, f"{phase} call cap {call_cap} reached"),
                (self.spent(phase) + reserve > budget, f"{phase} credit budget {budget}"),
                (
                    total_budget is not None and self.spent() + reserve > total_budget,
                    f"total credit budget {total_budget}",
                ),
                (
                    floor is not None and balance is None,
                    f"balance floor {floor} set but the balance is unknown",
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
        balance_before: int | None | object = ...,
    ) -> Entry:
        """Record one request. ``balance_before`` defaults to the last known balance;
        tool requests pass the balance captured before sending. Credit-endpoint
        reads never derive a cost from a balance difference.

        The response already exists when this runs, so a lock failure does not raise:
        the entry is kept in memory and the ledger is marked unreadable, which refuses
        every later request from this instance and never overwrites the file."""
        fields: dict[str, Any] = {
            "tool": tool,
            "ticker": ticker,
            "status": status,
            "balance_after": balance_after,
            "charged": charged,
            "balance_source": balance_source,
            "credit_header_names": credit_header_names,
            "balance_before": balance_before,
        }
        try:
            with self._locked():
                self._load()
                return self._record_locked(phase, **fields)
        except CreditBudgetExceeded:
            self.unreadable = True
            return self._record_locked(phase, **fields)

    def _record_locked(
        self,
        phase: str,
        *,
        tool: str | None,
        ticker: str | None,
        status: int,
        balance_after: int | None,
        charged: int | None,
        balance_source: str | None,
        credit_header_names: list[str] | None,
        balance_before: int | None | object,
    ) -> Entry:
        with self._lock:
            meta = _is_meta(phase)
            before = self.last_balance if balance_before is ... else balance_before
            cost: int | None = charged  # already validated: non-negative or None
            if cost is None and not meta and isinstance(before, int) and balance_after is not None:
                delta = before - balance_after
                cost = delta if delta >= 0 else None  # negative = top-up; cost unknown
            if cost is None and status >= 400:
                cost = 0  # hpsilab-mcp README: "a call that fails is never charged"
            if cost is None and meta and self.meta_free_verified:
                cost = 0
            entry = Entry(
                at=datetime.now(UTC).isoformat(timespec="seconds"),
                phase=phase,
                tool=tool,
                ticker=ticker,
                status=status,
                balance_before=before if isinstance(before, int) else None,
                balance_after=balance_after,
                cost=cost,
                charged_header=charged,
                balance_source=balance_source,
                credit_header_names=credit_header_names or [],
            )
            self.entries.append(entry)
            if not meta and cost is None and balance_after is None:
                self.blind = True
            self._save()
            return entry

    def clear_blind(self) -> None:
        """Call only after a fresh balance read succeeded."""
        with self._locked():
            self._load()
            if self.blind and not self.unreadable:
                self.blind = False
                self._save()

    def mark_meta_free(self) -> None:
        """Call only after verify_meta_free showed the credit endpoints cost 0."""
        with self._locked():
            self._load()
            if self.unreadable:
                return
            self.meta_free_verified = True
            for e in self.entries:
                if _is_meta(e.phase) and e.cost is None:
                    e.cost = 0
            self._save()

    def _save(self) -> None:
        """Write the file. If the write fails (for example Windows refuses os.replace
        while another process holds the ledger open), the entries stay in memory and the
        ledger is marked unreadable: fail closed, so a later authorize never reloads an
        older file and forgets a charge that was never persisted."""
        if self.path is None or self.unreadable:
            return
        tmp = self.path.with_suffix(".tmp")
        payload = {
            "blind": self.blind,
            "meta_free_verified": self.meta_free_verified,
            "entries": [asdict(e) for e in self.entries],
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError:
            self.unreadable = True
            try:
                tmp.unlink()
            except OSError:
                pass


# ---- parsing (credit endpoint formats are undocumented; parse tolerantly) ----
def _int(value: Any) -> int | None:
    """Non-negative integer credits, rounded up; anything else is None."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, str):
        try:
            value = float(value.strip())
        except ValueError:
            return None
    if isinstance(value, int):
        number = value
    elif isinstance(value, float):
        if not math.isfinite(value):
            return None
        try:
            number = math.ceil(value)
        except (OverflowError, ValueError):
            return None
    else:
        return None
    return number if number >= 0 else None


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
    """Map tool name -> credit price from a /api/credits/catalog body, best effort."""
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
                p = price_of(value) if key in tool_names else None
                if p is not None:
                    prices.setdefault(key, p)
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

    structured = _catalog_entries(body)
    if structured is not None:
        # The documented live shape (observed 2026-11-22). Only this is used when
        # present, so an inactive entry can never leak in through the generic walk.
        for entry in structured:
            credits = _int(entry.get("credits"))
            if credits is None:
                continue
            names = [entry.get("canonical_tool_name"), *(entry.get("aliases") or [])]
            for name in names:
                if isinstance(name, str) and name in tool_names:
                    prices.setdefault(name, credits)
        return prices
    walk(body)
    return prices


def _catalog_entries(body: Any) -> list[Mapping[str, Any]] | None:
    """Active entries of a catalog shaped {"tools": [{"canonical_tool_name", "aliases",
    "credits", "active", "rest_path_patterns", ...}]}; None if the body is not that shape.
    ``active`` must be exactly true; anything else (false, missing, "true") is skipped."""
    if not isinstance(body, Mapping) or not isinstance(body.get("tools"), list):
        return None
    tools = [t for t in body["tools"] if isinstance(t, Mapping)]
    if not tools or not all("canonical_tool_name" in t for t in tools):
        return None
    return [t for t in tools if t.get("active") is True]


def parse_catalog_paths(body: Any) -> list[tuple[str, int]]:
    """(rest_path_pattern, credits) for active catalog entries, for matching by request
    path when a tool's SDK name differs from the catalog's names."""
    pairs: list[tuple[str, int]] = []
    for entry in _catalog_entries(body) or []:
        credits = _int(entry.get("credits"))
        patterns = entry.get("rest_path_patterns") or []
        if credits is None or not isinstance(patterns, list):
            continue
        pairs.extend((p, credits) for p in patterns if isinstance(p, str) and p)
    return pairs


def price_for_path(path: str, pairs: list[tuple[str, int]]) -> int | None:
    """Price of the first catalog pattern matching ``path`` (``*`` matches one segment
    or a suffix, as in "/api/monte_carlo/*" and "/api/iv_batch*")."""
    for pattern, credits in pairs:
        regex = "^" + re.escape(pattern).replace(r"\*", r"[^/]*") + "$"
        if re.match(regex, path):
            return credits
    return None


def make_template(base_url: str, api_key: str) -> httpx.Request:
    """A request carrying only the auth header, used to address the credit endpoints."""
    return httpx.Request("GET", base_url, headers={"Authorization": f"Bearer {api_key}"})


def _credit_names(headers: httpx.Headers) -> list[str]:
    return sorted(k for k in headers.keys() if "credit" in k.lower())


@dataclass
class _Fetched:
    path: str
    response: httpx.Response | None
    body: Any
    status: int
    balance: int | None
    source: str | None
    charged: int | None
    header_names: list[str]


class RecordingTransport(httpx.BaseTransport):
    """Wraps the real transport; authorizes before and records after every request.

    Set ``context`` (``tool`` = SDK tool name, ``ticker``) before each SDK call.
    Call ``start(template, tool_names)`` once per run before the first tool call.
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
        self.path_prices: list[tuple[str, int]] = []
        self.meta_enabled = True
        # Balance observed during THIS run (None until one is seen). The floor is
        # checked only against this, never against a balance from an earlier run.
        self.run_balance: int | None = None

    # -- credit endpoints -------------------------------------------------
    def _fetch(self, template: httpx.Request, path: str) -> _Fetched:
        """GET a credit endpoint without recording it. Never raises transport errors."""
        if self.ledger.unreadable:
            raise CreditBudgetExceeded("Refusing request: ledger file is unreadable.")
        url = template.url.copy_with(path=path, query=None)
        auth = {k: v for k, v in template.headers.items() if k.lower() == "authorization"}
        try:
            response = self.inner.handle_request(httpx.Request("GET", url, headers=auth))
            response.read()
        except httpx.HTTPError:
            return _Fetched(path, None, None, TRANSPORT_FAILURE, None, None, None, [])
        try:
            body = response.json()
        except ValueError:
            body = None
        balance = parse_balance(response.headers)
        source = "header" if balance is not None else None
        if balance is None and path == BALANCE_PATH and response.status_code < 400:
            balance = parse_balance_body(body)
            source = "endpoint" if balance is not None else None
        return _Fetched(
            path,
            response,
            body,
            response.status_code,
            balance,
            source,
            header_int(response.headers, CHARGED_HEADER),
            _credit_names(response.headers),
        )

    def _record_meta(self, fetched: _Fetched) -> None:
        if fetched.balance is not None and 0 < fetched.status < 400:
            self.run_balance = fetched.balance
        self.ledger.record(
            f"{self.phase}:meta",
            tool=fetched.path,
            ticker=None,
            status=fetched.status,
            balance_after=fetched.balance,
            charged=fetched.charged,
            balance_source=fetched.source,
            credit_header_names=fetched.header_names,
        )

    def _meta_get(self, template: httpx.Request, path: str) -> tuple[httpx.Response | None, Any]:
        """GET a credit endpoint and record it. Never raises transport errors."""
        fetched = self._fetch(template, path)
        self._record_meta(fetched)
        return fetched.response, fetched.body

    def read_balance(self, template: httpx.Request) -> int | None:
        fetched = self._fetch(template, BALANCE_PATH)
        self._record_meta(fetched)
        return fetched.balance if fetched.status and fetched.status < 400 else None

    def load_catalog(self, template: httpx.Request, tool_names: set[str]) -> dict[str, int]:
        response, body = self._meta_get(template, CATALOG_PATH)
        if response is not None and response.status_code < 400:
            self.prices.update(parse_catalog(body, tool_names))
            self.path_prices = parse_catalog_paths(body)
        return dict(self.prices)

    def verify_meta_free(self, template: httpx.Request, tool_names: set[str]) -> dict:
        """Read balance, balance, catalog, balance. Free iff the balance never moves and
        no positive X-Credits-Charged is reported. Marks the ledger on success."""
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

    def start(self, template: httpx.Request, tool_names: set[str]) -> int | None:
        """Begin a run: prove the credit endpoints free (once per ledger), load prices,
        and read a fresh balance. A successful read clears a blind ledger. If the
        endpoints are not free, they are not used again in this run."""
        if not self.ledger.meta_free_verified:
            result = self.verify_meta_free(template, tool_names)
            if not result["free"]:
                self.meta_enabled = False
                self.prices.clear()
                self.path_prices = []
                return None
            balance = result["balances"][-1]
        else:
            self.load_catalog(template, tool_names)
            balance = self.read_balance(template)
        if balance is not None:
            self.ledger.clear_blind()
        return balance

    # -- tool requests ----------------------------------------------------
    def handle_request(self, request: httpx.Request) -> httpx.Response:
        tool = self.context.get("tool")
        ticker = self.context.get("ticker")
        self.ledger.authorize(
            self.phase,
            budget=self.budget,
            call_cap=self.call_cap,
            price=self._price(tool, request.url.path),
            tool=tool,
            total_budget=self.total_budget,
            floor=self.floor,
            balance=self.run_balance,
        )
        before = self.ledger.last_balance
        try:
            response = self.inner.handle_request(request)
        except BaseException:
            # No response, but the request may still have been billed. Record the
            # attempt (tool entry first, then the balance read used to cost it).
            fetched = self._fallback_balance(request)
            balance = fetched.balance if fetched else None
            self.ledger.record(
                self.phase,
                tool=tool,
                ticker=ticker,
                status=TRANSPORT_FAILURE,
                balance_after=balance,
                balance_source="endpoint" if balance is not None else None,
                balance_before=before,
            )
            self.run_balance = balance  # None if unknown: the floor then refuses
            if fetched:
                self._record_meta(fetched)
            raise
        charged = header_int(response.headers, CHARGED_HEADER)
        balance = parse_balance(response.headers)
        source = "header" if balance is not None else None
        fetched = None
        if balance is None:
            fetched = self._fallback_balance(request)
            balance = fetched.balance if fetched else None
            source = "endpoint" if balance is not None else None
        entry = self.ledger.record(
            self.phase,
            tool=tool,
            ticker=ticker,
            status=response.status_code,
            balance_after=balance,
            charged=charged,
            balance_source=source,
            credit_header_names=_credit_names(response.headers),
            balance_before=before,
        )
        if balance is not None:
            self.run_balance = balance
        elif entry.cost is not None and self.run_balance is not None:
            self.run_balance = max(0, self.run_balance - entry.cost)
        else:
            self.run_balance = None
        if fetched:
            self._record_meta(fetched)
        return response

    def _price(self, tool: str | None, path: str) -> int | None:
        """Catalog price by SDK tool name, else by the request path's catalog pattern."""
        if tool and tool in self.prices:
            return self.prices[tool]
        return price_for_path(path, self.path_prices)

    def _fallback_balance(self, template: httpx.Request) -> _Fetched | None:
        if not self.meta_enabled:
            return None
        return self._fetch(template, BALANCE_PATH)

    def close(self) -> None:
        self.inner.close()
