# Delivery: HPSILab research adapter v0.2.0

Date: 2026-11-26. Branch: `release/v0.2.0` (local only, not pushed). It is `feat/adapter-v1` with `fix/known-gaps` and `feat/thesis-demo` merged. The v0.1.0 evidence below was gathered on 2026-11-22 and is kept as history; see `CHANGELOG.md` for what changed in 0.2.0.
Authors: Mohammed Faisal Parvez (SDK integration, client, credit ledger, normalization, CLI)
and Rahmat Ullah (offline test infrastructure, error-contract and fixture specifications,
read-only AST boundary checks, secret scanning, pre-commit setup).

This is an independent, unverified third-party integration, not an official HPSILab product. HPSILab has not verified or endorsed it, and there is no HPSILab Community listing approval.
It is read-only and for research and analysis only. See `TERMS.md`.

## What is new in 0.2.0

- **Ledger lock.** Every read, check, record and save runs under a lock file next to the ledger, so two processes sharing a ledger no longer overwrite each other.
- **Damaged ledger fails closed.** A hand-edited or damaged ledger file refuses every request.
- **Zero-cost learned reserve fix.** A learned cost of 0 no longer lowers the reserved price when the catalog has no price for the tool.
- **Thesis evidence module** (`hpsilab_research_adapter.thesis`, see `docs/THESIS.md`): fixed, documented rules label each observed value `supports`, `challenges`, `neutral` or `context` for a thesis the user states. Research only; no verdict, no advice.
- **Demo script** `tools/thesis_demo.py [DIRECTION [HORIZON_DAYS]] [--ledger PATH]`: hand-run, limits 40 credits per run, 190 in total, balance floor 1800, refuses before any request when the configuration is unusable (including a missing ledger file). `--ledger` uses a given ledger file directly. One pass costs 41 credits at the catalog prices of 2026-11-22, which is above the 40-credit run cap, so the last tool of a pass can be refused; `monte_carlo` runs first so that the horizon-bearing tool is never the one lost.
- **Summary tool** `tools/thesis_summary.py REPORT.json`: a share-safe Markdown summary for an external reviewer that contains no value observed in any HPSILab response.
- Test suite: **402 passed, 0 skipped** (offline).

v0.2.0 is new and has not been reviewed by anyone outside this project. HPSILab has not reviewed, verified or endorsed it.

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
- **Docs.** README with the independent-integration and no-responsibility wording from `TERMS.md`, the link to https://hpsilab.com, the standard MIT `LICENSE`, and `TERMS.md`. The note that the licence covers only the adapter code is in the README and `TERMS.md`.

## Evidence

| Check | Result |
| --- | --- |
| Live probe, NVDA x 6 tools (2026-11-22) | 6/6 HTTP 200. Shapes saved as keys and types only in `schemas/`. 38 credits. |
| Live thesis demo, NVDA, up, 10 days (2026-11-27) | 6/6 tools succeeded. 17 evidence items, 1 field missing (`ai_prediction.model_consensus`), `monte_carlo` horizon matched. 38 credits, within the 40-credit cap and the 190-credit total (185 used). |
| Live ship check, AAPL, SPY, NVDA x 6 tools | 17 of 18 planned calls sent, all 17 HTTP 200. The credit guard refused the 18th, NVDA `monte_carlo`, before sending it, because it would have crossed the 112-credit run budget. NVDA `monte_carlo` is covered by the probe. 109 credits. |
| CLI end to end (live) | `hpsilab SPY --tool iv_radar --json` (the command was named `hpsilab` at the time; it is now `hpsilab-research`): HTTP 200, recorded in the ledger, 0 credits. |
| Normalization of real responses (offline) | The final normalizer was run on the 6 real probe responses (NVDA): 6/6 parse with every expected field present (0 missing). `monte_carlo` reports its horizon. Counts only; no values were printed. |
| Test suite | **289 passed, 0 skipped** on `feat/adapter-v1` at v0.1.0 (401 on `release/v0.2.0`). The same count comes from a fresh clone with a clean `pip install .`, which installs only `hpsilab-mcp==0.14.2` and the adapter. No x402 or wallet packages are installed. |
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
  - **Lock tested on Windows only.** The POSIX path has not been exercised.
  - **Lock scope.** The ledger file is locked (`<ledger>.lock`) while it is read or written, not while a request is in flight. Two processes on one ledger can both pass the budget check before either records, so each can exceed a shared budget by one in-flight call per process. Removing a stale lock is not atomic against another process doing the same. If the lock cannot be taken while recording a response that has already arrived, that call is kept in memory only and the client refuses every later request. The same happens if the ledger file cannot be written (for example Windows refuses to replace it while another process holds it open).
  - **Late billing.** A timeout billed after the fact can be under-counted by one call's price.
  - **Failed first-use check.** If the first-use check of the credit endpoints fails, that run is refused even though nothing was spent.
  - **Top-ups.** A top-up between runs, combined with responses that carry only `X-Credits-Remaining`, can mis-estimate one call's cost.
- **Weak `monte_carlo` range rule.** A central interval usually contains the start price, so the range rule tends to support a range thesis.
- **The live thesis demo has been run once (2026-11-27, NVDA, up, 10 days).** That is one real pass; the rules are otherwise covered by offline tests with synthetic data. The report itself stays local (`.probe/`, git-ignored) and is shared only as the value-free `tools/thesis_summary.py` output.
- **`Result.error` is reserved.** Errors are raised, never returned.
- **The pre-commit hooks are configured but not installed** in this checkout (`pre-commit install` has not been run). gitleaks was run manually.
- **The README's "About HPSILab" section is factual but generic.** It uses only SDK metadata and the link. The owner may replace it with approved wording.
- **Human-only actions:** pushing to the remote, merging to a default branch, changing repository visibility, granting access, and sending any message are done by the maintainers, never by the tooling.

## Next

Run the NVDA 10-day thesis demo by hand (due Dec 16), then share the output of `tools/thesis_summary.py` with the external reviewer. Pushing, merging and any message to others remain human actions.
