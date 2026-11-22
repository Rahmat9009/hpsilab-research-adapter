"""Retry and spend policy. FROZEN CONTRACT (Phase 1): do not edit in later phases.

Values come from tests/README.md (3 attempts / 2 backoffs) and the owner's brief
(credit budgets, balance floor). TIMEOUT_ATTEMPTS is an owner decision that
Rahmat's tests leave open (1-3). It is set to 1 because a timed-out request
may already have been billed, and retrying it could charge twice.
"""

from __future__ import annotations

ENV_API_KEY = "HPSILAB_API_KEY"
# hpsilab-mcp builds a paying x402 wallet from this variable even without the
# [x402] extra being requested by us. Its presence makes the adapter refuse to run.
ENV_X402_WALLET = "HPSILAB_X402_PRIVATE_KEY"

MAX_ATTEMPTS = 3  # one request + two retries, for 429 / 5xx / connection errors
TIMEOUT_ATTEMPTS = 1  # owner decision; see module docstring
BACKOFF_BASE_SECONDS = 1.0
BACKOFF_CAP_SECONDS = 30.0

CREDITS_HEADER = "X-Credits-Remaining"
PROBE_CREDIT_BUDGET = 60
SHIP_CHECK_CREDIT_BUDGET = 60  # leaves 30 of the 150 total for re-runs
TOTAL_CREDIT_BUDGET = 150
BALANCE_FLOOR = 1800  # stop if the account balance is below this

PROBE_CALL_CAP = 10
SHIP_CHECK_CALL_CAP = 20
