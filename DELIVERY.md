# Delivery: HPSILab research adapter v0.1.0

Date: 2026-11-22. Branch: `feat/adapter-v1` (local only, not pushed).
Authors: Mohammed Faisal Parvez (SDK integration, client, credit ledger, normalization, CLI)
and Rahmat Ullah (offline test infrastructure, error-contract and fixture specifications,
read-only AST boundary checks, secret scanning, pre-commit setup).

This is an independent integration, not an official HPSILab product. HPSILab has not endorsed it.
It is read-only and for research and analysis only. See `TERMS.md`.

## What works

- **A read-only Python adapter for six tools**, built on plain `hpsilab-mcp==0.14.2`: `analyze_stock`, `ai_prediction`, `iv_radar`, `option_pressure`, `pretrade_risk_scan` and `monte_carlo`.
  - It calls only those six GET methods, plus two read-only credit endpoints (`/api/credits/balance` and `/api/credits/catalog`).
  - It never calls `generate_*`.
- **Credits-only mode.** The adapter forces `payment_mode=CREDITS_ONLY` and passes no wallet. It refuses to run if `HPSILAB_X402_PRIVATE_KEY` is set.
- **Missing key.** It raises `AuthError` before any SDK client is created, which is verified with network access blocked.
- **CLI.** `hpsilab-research TICKER ... --tool ... [--json]` has per-run, total and balance-floor credit limits and exit codes 0, 2, 3, 4 and 5. It continues past failures of a single call, and always prints the results it has completed.
- **Retries.** 429, 5xx and connection errors get up to 3 attempts. Timeouts get 1 attempt, because a timed-out call may already have been billed. Credit and auth errors are never retried. Every attempt is checked and recorded by the credit ledger.
- **Normalization.** Every tool returns a common `Result`: `tool`, `ticker`, `data`, `horizon`, `source_fields`, `missing_fields`. Values pass through unchanged. `horizon` is reported only when the response states one (`monte_carlo.horizon_days`). It is never inferred.
- **Price parser.** It reads the live catalog shape: `canonical_tool_name` and `aliases` map to `credits` for active entries only, with a fallback that matches the request path against `rest_path_patterns`.
- **Docs.** README with the independent-integration and no-responsibility wording from `TERMS.md`, the link to https://hpsilab.com, MIT `LICENSE` scoped to the adapter code only, and `TERMS.md`.

## Evidence

| Check | Result |
| --- | --- |
| Live probe, NVDA x 6 tools (2026-11-22) | 6/6 HTTP 200. Shapes saved as keys and types only in `schemas/`. 38 credits. |
| Live ship check, AAPL, SPY, NVDA x 6 tools | 17 of 18 planned calls sent, all 17 HTTP 200. The credit guard refused the 18th, NVDA `monte_carlo`, before sending it, because it would have crossed the 112-credit run budget. NVDA `monte_carlo` is covered by the probe. 109 credits. |
| CLI end to end (live) | `hpsilab SPY --tool iv_radar --json` (the command was named `hpsilab` at the time; it is now `hpsilab-research`): HTTP 200, recorded in the ledger, 0 credits. |
| Normalization of real responses (offline) | The final normalizer was run on the 6 real probe responses (NVDA): 6/6 parse with every expected field present (0 missing). `monte_carlo` reports its horizon. Counts only; no values were printed. |
| Test suite | **289 passed, 0 skipped** on `feat/adapter-v1`. The same count comes from a fresh clone with a clean `pip install .`, which installs only `hpsilab-mcp==0.14.2` and the adapter. No x402 or wallet packages are installed. |
| Rahmat's safety tests | `tests/test_readonly.py`, `tests/readonly_scan.py`, `tests/test_secret_scanner.py`, `tools/scan_secrets.py`, `tests/test_errors.py`, `tests/sdk_contract.py`, `.pre-commit-config.yaml` and `.gitleaks.toml` are unchanged from base commit `c06bb13`. All 12 error contracts pass against the real client; none are skipped. |
| Read-only boundary | The AST scan of all production Python finds no broker imports and no `submit_order`, `place_order` or `execute_order`. |
| Secrets and data | gitleaks working-tree scan is clean, and its self-test detects the synthetic canary. The fixtures share no value with the real responses: an automated comparison found 0 overlaps out of 5,485 distinctive values. `.probe/` and `.credits/` are gitignored and untracked. |
| Lint | `ruff check` and `ruff format --check` are clean. `pip check` is clean. |
| Independent review (`REVIEW.md`) | Loop 1: FAIL on the credit ledger, docs and defects; terms and safety passed. Loop 2: FAIL on 2 small blockers. Loop-2 fix verification: **PASS**. |

## Credits used

| Phase | Tool calls | Credits |
| --- | --- | --- |
| Probe (NVDA) | 6 | 38 |
| Ship check (AAPL, SPY, NVDA) | 17 | 109 |
| CLI smoke (SPY iv_radar) | 1 | 0 |
| Credit-endpoint reads (balance, catalog) | 10 (not tool calls) | 0 (verified free) |
| **Total** | **24** | **147 of the 150-credit cap** |

The balance went from 2,200 to 2,053, staying above the 1,800 floor. Every figure comes from `X-Credits-Charged` and `X-Credits-Remaining` on each response, recorded in `.credits/ledger.json`, which is local and not committed.

Prices from the live catalog: analyze_stock 12, ai_prediction 2, iv_radar 3, option_pressure 4, pretrade_risk_scan 15, monte_carlo 5. All charges matched the catalog except iv_radar, which was charged 0 on all 5 calls. The credit endpoints themselves return no credit headers.

## Known gaps

- **Ship-check responses were not stored, and its printed summary was lost.** HTTP success for those 17 calls is proven by the ledger. Their normalization is not separately evidenced. Normalization was checked offline on the 6 real probe responses instead. `tools/ship_check.py` now prints each row live and writes `.credits/ship_summary.json`, so this cannot recur silently.
- **Live coverage is one day, three tickers**, against hpsilab-mcp 0.14.2 shapes observed on 2026-11-22. If HPSILab changes a response, `schemas/`, the fixtures and `normalize.EXPECTED_FIELDS` must be updated together.
- **Credit ledger limits**, also documented in the README:
  - **No file lock.** Do not run two processes on one ledger file.
  - **Late billing.** A timeout billed after the fact can be under-counted by one call's price.
  - **Failed first-use check.** If the first-use check of the credit endpoints fails, that run is refused even though nothing was spent.
  - **Zero-cost calls.** A successful call charged 0 sets that tool's learned reserve to 0 when the catalog has no price for it. iv_radar is the one case observed, and the catalog now prices it at 3.
  - **Top-ups.** A top-up between runs, combined with responses that carry only `X-Credits-Remaining`, can mis-estimate one call's cost.
  - **Damaged ledger.** A library client that hits an unreadable ledger raises `TypeError` instead of `CreditBudgetExceeded` on its second call. No request is sent, and the CLI is unaffected.
- **`Result.error` is reserved.** Errors are raised, never returned.
- **The pre-commit hooks are configured but not installed** in this checkout (`pre-commit install` has not been run). gitleaks was run manually.
- **The README's "About HPSILab" section is factual but generic.** It uses only SDK metadata and the link. The owner may replace it with approved wording.
- **The local development `.venv` editable install reports version 0.0.1.** A reinstall was blocked by the permission system. A fresh install reports 0.1.0.
- **Human-only actions, not done:** pushing to the remote, merging to a default branch, changing repository visibility, granting access, and sending any message.

## Next

The NVDA 10-day thesis demo, due Dec 16. It will cover the fields used, the supports/challenges logic, and how missing evidence or a different time horizon is reported.
