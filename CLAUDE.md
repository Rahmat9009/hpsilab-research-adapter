# Orchestrator brief: HPSILab research adapter v1

Goal: a working, read-only Python adapter for 6 HPSILab research tools, with all
tests green, ready for a human to send on Nov 23.

## Layout (this repo, not the brief's `adapter/` sketch)
Package: `src/hpsilab_research_adapter/`. Rahmat's tests in `tests/` are the spec;
see `RECON.md`.

## Frozen contracts (Phase 1). No later phase edits these
`errors.py`, `types.py`, `tools.py`, `policy.py`. `ledger.py` is shared
infrastructure and is changed only by the orchestrator.

## Phase 3 file ownership (parallel, one branch per agent)
| Agent | Owns | Done when |
|---|---|---|
| A (Sonnet) | `client.py`, `tests/conftest.py` binding only | all 12 `test_errors.py` cases pass, none skipped |
| B (Sonnet) | `normalize.py` | full, missing-field and `{}` handled for all 6 tools |
| C (Haiku) | `tests/fixtures/*`, `tests/test_fixtures.py` | 18 fixtures, fake values, match `schemas/*.shape.json` |
| D (Haiku) | `cli.py`, `__main__.py`, `tests/test_cli.py` | `python -m hpsilab_research_adapter NVDA --tool X` runs against mocks |

## SDK rules (hpsilab-mcp 0.14.2)
- Install plain `hpsilab-mcp`. Never install the `[x402]` extra. Never pass a wallet.
- Refuse to start if `HPSILAB_X402_PRIVATE_KEY` is set. Always pass `payment_mode=CREDITS_ONLY`.
- Missing `HPSILAB_API_KEY` raises `AuthError` before the client is created.
- Use only `analyze_stock`, `get_ai_prediction`, `get_iv_radar`, `get_option_pressure`,
  `get_pretrade_risk_scan` and `get_monte_carlo`. Never call `generate_*`, which is
  POST and not idempotent.
- Pass `include_metadata=True` where it is supported (only `get_ai_prediction`).
- The SDK does not retry. The adapter retries 429, 5xx and connection errors:
  3 attempts and 2 backoffs, with sleep injected. Timeouts get `TIMEOUT_ATTEMPTS`.
  Credits and auth failures are never retried.
- Raise adapter errors `from None`, with safe attributes only. No credential may
  appear anywhere in an exception chain.

## Credits, not calls
- Every live request goes through `ledger.RecordingTransport`, which reads
  `X-Credits-Remaining` and persists `.credits/ledger.json`.
- Budgets: probe 60, ship check 60, total 150. Stop if the balance would drop below 1,800.
- If a response has no balance header, the ledger goes blind and refuses further requests.
- Retries go through the same transport, so they are counted and capped.

## Hard rules
- Never commit real HPSILab values. Shapes record keys and types only. Raw data stays in `.probe/`.
- No broker, exchange or order code. No `submit_order`, `place_order` or `execute_order`.
- Never print, log or echo the API key.
- If the same test fails 3 times, escalate to Opus. If Opus fails twice, stop and write `BLOCKED.md`.
- Never push to any remote, never change repo visibility, never send messages.
- Network access is limited to hpsilab.com and PyPI.
- Check `TERMS.md` in the Phase 5 review.
- Finish by writing `DELIVERY.md` and stopping.

Out of scope: colours, caching, async, thesis comparison, PyPI publishing.
