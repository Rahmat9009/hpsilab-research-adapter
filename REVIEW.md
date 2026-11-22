# Review (loop 2)

- Date: 2026-11-22
- Branch: `feat/adapter-v1`
- Commit reviewed (`git rev-parse HEAD`): `6f32f70724db6d0aa2c96758352880124b791c3e` (working tree clean before and after the review)
- Previous review: loop 1, commit `123c37c` (Overall FAIL on F, I, J).
- Reviewer: independent; did not write this code. The only file edited is this one. Nothing was committed or pushed.
- Method: read every tracked source, test and doc file and the wrapped SDK (`.venv/Lib/site-packages/hpsilab_mcp/`, 0.14.2); ran the quality gates; ran three offline probe scripts (kept outside the repository) that drive the real `ResearchClient`, the real SDK and the real CLI through `httpx.MockTransport`, with sockets blocked, every `HPSILAB_*` variable removed and an obviously fake key. No network call to HPSILab was made. `tools/probe.py` and `tools/ship_check.py` were read, not executed. `.probe/` and `.credits/` were not opened; only their ignore status was checked. CLI probes ran from a scratch directory so the default relative ledger path could not touch the repository.

## Summary

| Item | Verdict | One-line reason |
| --- | --- | --- |
| A1 Independent / not endorsed | PASS | `README.md:7`, `cli.py:61` (`--help`), `pyproject.toml:8`. |
| A2 Name only, no logo | PASS | No image file in the tree or in any commit; no image reference. |
| A3 README links https://hpsilab.com | PASS | `README.md:17` (bare URL, autolinked). |
| A4 Research only, read-only | PASS | `README.md:9`; code verified under B. |
| A5 No-responsibility statement | PASS | `README.md:11`. |
| A6 MIT scope limited to adapter code | PASS | `LICENSE:23-24`, `README.md:251`. |
| B Read-only, six SDK methods only | PASS | Six GET methods plus two credit GETs; allowlist now enforced at `client.py:262`. |
| C No secrets, no real data | PASS | Scanner clean on tree and on all history; fixtures fabricated; shapes hold types only. |
| D x402 / real-money payment impossible | PASS | Refusal in every entry point; `CREDITS_ONLY` forced; no wallet; extra not installed. |
| E Missing key raises before SDK client | PASS | 0 SDK clients constructed in three missing-key CLI cases. |
| F Credit ledger and retries | **PARTIAL** | All seven loop-1 findings are fixed or mostly fixed, but one new cap breach exists: a failed call sets the reserved price for that tool to 0, so `--max-credits 0` sends a paid request. |
| G Key never printed, logged or in exceptions | PASS | No leak in 12 response scenarios with the key echoed in bodies; not in ledger files. |
| H Quality gate | PASS | `272 passed`, 0 skipped; ruff, format, pip check clean; eight protected files unchanged from `c06bb13`. |
| I Docs accuracy | **PARTIAL** | Ledger section now matches the code, but `README.md:199` states 211 tests (actual 272) and two docs point to a `DELIVERY.md` that does not exist. |
| J Other defects | 1 blocking | 0 high, 4 medium (1 blocking), 6 low. |

## Previous findings

| Loop-1 item | Status | Evidence |
| --- | --- | --- |
| F-1 cap exceeded when price unknown | PARTIALLY | Catalog is now loaded on every run (`client.py:267-277`, `ledger.py:489-505`) and an unknown price reserves 20 (`ledger.py:58`, `150-154`). Probe: budget 5, tool costs 10, no catalog -> refused, 0 tool requests. Still breakable through the "largest cost seen" branch when that cost is a 0 recorded for a failed call (new finding F-N1). |
| F-2 floor skipped while balance unknown | PARTIALLY | `ledger.py:180-183` refuses when the floor is set and no balance is known. Probe: floor 1800, endpoint down, fresh ledger -> refused; real balance 100 -> refused before any tool request. Remaining gap: a balance persisted by an earlier run counts as known when this run's read fails (F-N2). |
| F-3 transport-exception attempts unrecorded | RESOLVED | `ledger.py:521-539`. Probe: `call_cap=1`, connection errors -> 1 tool request, 1 entry (status 0), second attempt refused. A billed read timeout is costed from the balance read (10 recorded for 10 spent). |
| F-4 fallback bypasses checks, leaves no trace | RESOLVED | Every credit-endpoint read is recorded whatever the outcome (`ledger.py:439-449`, `559-560`); the fallback is used only after the endpoints were proven free or is disabled for the run (`ledger.py:493-498`, `563-566`). Probe: balance endpoint 500 after a header-less 200 -> meta entry with status 500 present, ledger blind. |
| F-5 unknown costs recorded as 0 or negative | RESOLVED | `ledger.py:219-225`, `276-296`. Probe: `X-Credits-Charged: -50` ignored (cost taken from the balance drop, 10); balance increase -> unknown, counted as 20; `0.5` -> 1. The "HTTP error status = 0" rule is kept, but only when no charged header and no balance evidence exist, and it is now documented (`README.md:169`). |
| F-6 `OverflowError` on non-finite header | RESOLVED | `ledger.py:288-293`. Probe: `X-Credits-Remaining: inf`, `X-Credits-Charged: nan` -> no crash, cost from the endpoint. |
| F-7 no ledger on direct construction | RESOLVED | `client.py:210-217`. Probe: `ResearchClient(KEY)._transport` is a `RecordingTransport`, budget 50, cap 150, in-memory. |
| I README ledger claims (old lines 88-89, 117-118, 149, 156, 158, 166, 168) | RESOLVED | Rewritten at `README.md:118-126`, `154-181`; checked sentence by sentence below. |
| I README exit code 1 / crash on normalizer error | RESOLVED | `client.py:316-325` wraps it as `UpstreamError`; `README.md:137`. |
| I README placeholder comment | RESOLVED | No `<!--` in any doc. |
| I `--total-credits` with `--no-ledger`; ledger path | RESOLVED | `cli.py:213-216` (exit 2); path documented at `README.md:123`. |
| I `RECON.md` "no balance endpoint" | RESOLVED | `RECON.md:79-81`. |
| I `tests/fixtures/README.md` "No provider calls" | RESOLVED | `tests/fixtures/README.md:3`. |
| I `CLAUDE.md` blind sentence | RESOLVED | `CLAUDE.md:41-43`. |
| I `VERIFICATION.md` stale | PARTIALLY | Marked historical (`VERIFICATION.md:3-4`), but it and `tests/README.md:132` now refer to `DELIVERY.md`, which is not in the repository. |
| J-1 budget overshoot, unknown prices | PARTIALLY | Same as F-1. |
| J-2 transport failures invisible | RESOLVED | Same as F-3. |
| J-3 floor skipped | PARTIALLY | Same as F-2. |
| J-4 blind ledger permanent and misreported | RESOLVED | `ledger.py:489-505`, `245-250`. Probe: blind ledger, next run's balance read succeeds -> flag cleared, the unknown call stays counted at 20 (ledger 40, real spend 30). A 5xx no longer blinds. |
| J-5 normalizer error crashes CLI, loses results | RESOLVED | `client.py:316-325`, `cli.py:258-261`. Probe: list body on `iv_radar` -> `UpstreamError`, exit 5; completed results still printed. |
| J-6 `missing_fields` wrong for `ai_prediction` | RESOLVED | `normalize.py:209-210`; `tests/test_normalize.py:206-212`. |
| J-7 `OverflowError`, negative charges | RESOLVED | Same as F-5, F-6. |
| J-8 concurrent runs; corrupt file | RESOLVED (documented limit) | Corrupt file fails closed (`ledger.py:93-100`; probe: empty, truncated, list, null, wrong shape, extra field, BOM -> every request refused, file left untouched). No locking; stated at `ledger.py:29-30`, `README.md:171`. |
| J-9 `ALLOWED_SDK_METHODS` unenforced | RESOLVED | `client.py:262-263`. |
| J-10 `Result.error` dead | RESOLVED (documented) | `README.md:150` states the field is reserved; dead CLI branch removed. |
| J-11 one failing ticker aborts the run; default budget below one pass | RESOLVED | `cli.py:245-251` continues; default raised to 50 (`cli.py:34`). Probe: one pass with prices summing to 38 completes, exit 0. |

## A. TERMS.md — PASS (all six)

- **A1 PASS.** `README.md:7` reproduces the term. Also `cli.py:58-62` (printed by `--help`), `pyproject.toml:8`, `README.md:247`.
- **A2 PASS.** `git ls-files` contains no image or PDF. `git log --all --diff-filter=A --name-only` shows no image, `.probe`, `.credits` or `.env` path ever added. `git grep -i` for `logo`, `<img`, `![`, `data:image`, `shields.io`, `badge` returns only `TERMS.md:8-9`, `VERIFICATION.md:92` (a sentence about another project) and this file.
- **A3 PASS.** `README.md:17`: `Website: https://hpsilab.com`.
- **A4 PASS.** `README.md:9`, including "directly or through another service". `cli.py:59-60`, `cli.py:157`. Code evidence under B.
- **A5 PASS.** `README.md:11`, verbatim.
- **A6 PASS.** `LICENSE:23-24`, `README.md:251`.

## B. Read-only — PASS

- Dispatch: `client.py:289-291` resolves the tool with `TOOLS.get`; `client.py:262-265` then checks `spec.sdk_method in ALLOWED_SDK_METHODS` before the only dynamic `getattr` on the SDK. Probe: `run()` with `generate_stock_images`, `register_account`, `get_monte_carlo`, `get_equity_curve`, `set_wallet`, `__class__`, `None` -> `ValueError`, nothing sent. The CLI restricts `--tool` by argparse `choices` (`cli.py:102`); `--tool generate_stock_images` exits 2.
- Wire check through the real CLI and SDK (mock transport): the only method seen was `GET`; tool paths were `/api/analyze_stock/TEST?refresh=false`, `/api/ai_prediction/TEST`, `/api/iv_batch?symbols=TEST`, `/api/option_pressure/TEST`, `/api/pretrade-risk-scan?symbol=TEST`, `/api/monte_carlo/TEST`, plus `/api/credits/balance` and `/api/credits/catalog`.
- `git grep` over `src/` and `tools/` for `.post(`, `.put(`, `.delete(`, `.patch(`, `"POST"`, `generate_`, `register`, `set_wallet`, `set_payment`, `set_api_key`, `call_tool`, `equity_curve`, broker names and order verbs: two hits, both docstrings (`__init__.py:1`, `tools.py:6`). The only `httpx.Request(` constructions are `"GET"` (`ledger.py:359`, `415`).
- Ticker: `client.py:67`, `76-80`. Probe: `../x`, `A/B`, `A?x=1`, empty, 11 characters -> `ValueError`.
- `tools/probe.py:172` uses `getattr(client, spec.sdk_method)` over the same frozen `TOOLS` table.

Notes, not failures: `tests/readonly_scan.py` cannot see a non-literal `getattr`; the guarantee rests on the dict lookup and the allowlist check. `TOOLS` is a mutable module dict and `ResearchClient(request=...)` accepts any callable; neither is reachable from user input.

## C. No secrets, no real data — PASS

- `tools\scan_secrets.py` -> `Secret scan passed: no findings.` (exit 0).
- `gitleaks detect --source . --config .gitleaks.toml --redact --log-opts="--all"` -> `19 commits scanned ... no leaks found`.
- `.probe/` and `.credits/` are ignored (`.gitignore:17-18`); `git ls-files .probe .credits` is empty; neither path was ever committed.
- Fixtures: every leaf across the 18 files is one of `fake-*` (141), `TEST`, `2000-01-01`, `2000-01-02`, `0.5`, `1.25`, `1`, `2`, `false`, `null`.
- `schemas/*.shape.json`: every leaf under `data`/`metadata` is a JSON type name or `null`; `probed_ticker` is `<TICKER>`; no key looks like a date, a number or a ticker symbol.
- Informational, unchanged from loop 1: `policy.py:22-25` and `CLAUDE.md:39-40` hold account operating numbers (budgets, floor 1,800), `ledger.py:57` and `cli.py:114` record observed credit costs (15, 38). These are not credentials or provider data.

## D. x402 / real-money payment — PASS

- `pyproject.toml:15` pins `hpsilab-mcp==0.14.2` with no extra. No `x402`, `eth_*` or `web3` package is installed in `.venv`.
- Guards: `client.py:203-206` (constructor), `client.py:245-248` (`from_env`, hence the CLI), `tools/probe.py:127-128`, `tools/ship_check.py:93-95`. All run before any client or request. CLI probe with a fake `HPSILAB_X402_PRIVATE_KEY`: `UnsafeConfiguration`, exit 3, 0 SDK clients, 0 requests.
- `client.py:224` and `tools/probe.py:142` pass `payment_mode=CREDITS_ONLY` and no wallet; `client.py:226-228` and `tools/probe.py:145-146` refuse if `payment_policy.pays`.
- The SDK reads exactly one environment variable (`payments.py:63`, `149`); the base URL is not environment-driven.
- Probe: a 402 carrying an x402 `accepts` offer -> one GET, no payment header, `CreditsExhausted`, no retry.
- The credit-endpoint GETs (`ledger.py:408-437`) bypass the SDK and contain no payment logic.

## E. Missing key — PASS

`client.py:201-202` raises before `HpsiMcpClient(...)` at `client.py:220`; `from_env` raises at `client.py:242-244` before the ledger or transport exist. CLI probe with `HpsiMcpClient.__init__` counted: no variable, whitespace-only variable -> `AuthError: HPSILab API key is missing.`, exit 3, 0 SDK clients, 0 requests. `tools/probe.py:129-131` and `tools/ship_check.py:96-99` refuse before creating a client (read, not run).

## F. Credit ledger and retries — PARTIAL

Retry policy, re-measured through the real SDK with the ledger installed (sleep injected):

| Upstream | Tool requests | Sleeps | Raised | Ledger entries (status, cost) |
| --- | --- | --- | --- | --- |
| 429, `Retry-After: 1` | 3 | 1.0, 1.0 | `RateLimited` | (429, 0) x3 |
| 503 | 3 | 1.0, 2.0 | `UpstreamError` | (503, 0) x3 |
| connection error | 3 | 1.0, 2.0 | `UpstreamError` | (0, 0) x3 |
| read timeout | 1 | none | `Timeout` | (0, 0) |
| 401, 403 | 1 | none | `AuthError` | one each |
| 402 credits, 402 x402 offer | 1 | none | `CreditsExhausted` | (402, 0) |
| 404, 422 | 1 | none | `UpstreamError` | one each |
| 200 non-JSON | 1 | none | `UpstreamError` | (200, 8) |

Every attempt is authorized and recorded. Call cap 2 with repeated 503 -> exactly 2 tool requests, then refused. `--total-credits 40` with a 15-credit tool over three runs on one ledger -> 15, 30, refused. `--no-ledger` enforces the per-run budget in memory; `--no-ledger --total-credits` exits 2. Unreadable ledger files refuse everything and are not overwritten. The seven loop-1 findings are covered in the table above.

New findings from attacking the new code:

**F-N1 (medium, blocking). A failed call sets the reserved price of that tool to 0, so a cap can be passed with nothing reserved.**
`reserve_for` (`ledger.py:150-154`) falls back to `tool_cost` when no catalog price is known, and `tool_cost` (`ledger.py:115-118`) takes the maximum of every recorded cost for the tool, including the 0 that `record` assigns to an HTTP error (`ledger.py:222-223`) or to a transport failure with an unchanged balance. After one such entry the reserve for that tool is 0, and `spent + 0 > budget` and `balance - 0 < floor` can never refuse.
Probes (catalog endpoint answering 404, so no catalog price):
- Run 1 `BADX --tool monte_carlo` -> 404, cost 0. Run 2, same ledger, `TEST --tool monte_carlo --max-credits 0` -> request sent, exit 0, 8 credits spent with a budget of 0. Control on a fresh ledger: refused, 0 spent.
- One run, `BADX TEST --max-credits 25`: after the six 404s for `BADX`, the `TEST` pass spends 30 against a cap of 25. Control without `BADX`: stops at 10.
The overshoot is at most one call's full price per run (the next check sees the real spend), and it needs a missing catalog price for that tool (catalog read failed in this run, or the tool is not matched by `parse_catalog`). It contradicts the module's own guarantee at `ledger.py:19` and defeats `--max-credits 0`. No test covers it (`tests/test_ledger.py:125` covers only a never-seen tool).
Minimal fix: in `tool_cost`, use only entries from successful responses (`200 <= e.status < 300`); if there are none, `reserve_for` returns `unknown_cost_value`. Add a regression test: prior 404 entry, no catalog, `budget=0` -> refused before sending.

**F-N2 (medium, not blocking if documented). The floor is checked against a balance persisted by an earlier run when this run's balance read fails.**
`start()` ignores a failed read (`ledger.py:500-505`; its return value is discarded at `client.py:274`), and `authorize` uses `last_balance` from the file (`ledger.py:170`, `104-108`). Probe: ledger whose last balance is 1990 from an earlier run, account since reduced to 1000 elsewhere, balance and catalog endpoints answering 500, floor 1800 -> the first request is sent (balance 990 afterwards); the second is refused. Exposure: one call per run, and only when the balance endpoint fails at start. `README.md:121` and `README.md:164` say a request is refused when the balance cannot be determined, which is not what happens here.
Fix: have `start()` record whether a fresh balance was obtained and refuse tool requests when a floor is set and it was not; or state the limit in the README.

**F-N3 (medium, not blocking if documented). A timed-out call that is billed after the timeout is recorded as cost 0.**
On a transport failure the balance is read immediately (`ledger.py:523-536`); if the charge has not landed yet, the delta is 0 and that counts as evidence. When the next response carries `X-Credits-Charged`, the cost is the header alone (`ledger.py:218`), so the late charge is never counted. Probe: timeout billed late, then a normal call -> ledger 10, real spend 20. The balance itself stays correct, so the floor is unaffected; the per-run and total budgets undercount by one call per such timeout. Fix: when both a charged header and a balance drop are known, record the larger; or document it.

**F-N4 (low). A failed endpoint verification consumes the run's budget.** While a ledger is unverified, each credit-endpoint read with a 2xx status or a transport failure has unknown cost and counts as 20 (`ledger.py:224-225`, `131-138`). Probe: balance moves during verification (or the endpoints are unreachable) -> 60 to 80 credits counted, every tool request refused with `credit budget 50`, exit 4, although nothing was spent; a second such run on the same ledger shows 120 against `--total-credits`. It fails closed and the phantom entries are zeroed by the next successful verification (`ledger.py:252-259`), but the message blames the budget and `README.md:158` ("otherwise it stops using them for that run") reads as if the run continues.

**F-N5 (low). Semantically invalid ledger files are trusted.** A hand-edited file with `"cost": -500` loads and enlarges every budget (probe: `spent = -490`, request sent); `"cost": "abc"` raises an uncaught `TypeError`. Syntactically corrupt files are handled correctly. Fix: validate field types and non-negativity on load and set `unreadable` otherwise.

**F-N6 (low). Blind recovery relies on tolerant balance parsing.** `parse_balance_body` (`ledger.py:308-320`) accepts a bare number or any `credits`/`balance`/`available`/`remaining` integer one level down. Probe: body `{"limits": {"credits": 5}}` -> balance 5, blind cleared. Booleans, strings in objects and error statuses are rejected (a 500 with a balance header does not clear blind). The real endpoint format was checked by the authors' live probe, which I did not open, so this is a robustness note, not a demonstrated fault.

Checked and found sound: ordering of the fallback read versus the tool entry (the tool entry is costed from the balance captured before sending and is written first, the meta entry never derives a cost); no double counting in normal flows (an unknown entry followed by a balance-derived cost can count the same charge twice, which errs high); a 5xx that does reduce the balance is costed from the drop; `KeyboardInterrupt` during a request still records the attempt; catalog prices keyed by either tool name reach the authorizer (`client.py:275-277`).

## G. Key handling — PASS

- `--status` prints `HPSILAB_API_KEY set: yes` only (`cli.py:155`, `161`).
- 12 response scenarios with the fake key echoed in 401, 403, 404, 422, 429, 503 bodies, in a connection-error message and in a non-JSON 200 body: key absent from `str`, `repr` and `vars` of the raised error; `__cause__` and `__context__` are `None` (`client.py:314-315`, `321-325`).
- CLI stdout and stderr never contained the key in any probe; ledger files never contained it (`Entry`, `ledger.py:66-78`, has no header or body field). `repr(ResearchClient)` does not contain it.
- `tools/probe.py:181` prints the exception class and status only; `tools/ship_check.py` prints counts and shapes.

Notes: unclassified SDK errors still propagate unchanged (`client.py:307-308`); in 0.14.2 those are raised only on `register_account` paths, which are unreachable. The key is held on `ResearchClient._api_key` (`client.py:207`) and in the template request built at `client.py:274`.

## H. Quality gate — PASS

| Command | Result |
| --- | --- |
| `python -m pytest --basetemp=.test-tmp -q` | `272 passed in 2.77s` (0 skipped, 0 failed; `-rs` lists nothing) |
| `python -m ruff check .` | `All checks passed!` |
| `python -m ruff format --check .` | `32 files already formatted` |
| `python -m pip check` | `No broken requirements found.` |
| `python tools\scan_secrets.py` | `Secret scan passed: no findings.` |
| `python -m pre_commit validate-config` | exit 0 |

`git diff c06bb13 -- tests/test_readonly.py tests/readonly_scan.py tests/test_secret_scanner.py tools/scan_secrets.py tests/test_errors.py tests/sdk_contract.py .pre-commit-config.yaml .gitleaks.toml` is empty: all eight protected files are unchanged.

Per file: `test_cli.py` 44, `test_client.py` 30, `test_errors.py` 12, `test_fixtures.py` 50, `test_ledger.py` 37, `test_normalize.py` 60, `test_readonly.py` 37, `test_secret_scanner.py` 2.

Note (environment, not repository): the editable install in `.venv` still reports distribution version 0.0.1 (`pip show`), while `pyproject.toml` and `--version` say 0.1.0. Re-run `pip install -e ".[dev]"` before shipping.

## I. Docs accuracy — PARTIAL

Verified true: the `--help` block (`README.md:67-100`) matches real output byte for byte; `--status` and `--version`; exit codes 0, 2, 3, 4, 5 (`README.md:130-137`) in probes; continue-on-failure and "completed results are always printed" (`README.md:114`); the credit-flag table (`README.md:118-126`); the library example and the direct-constructor sentence (`README.md:141-152`); the retry policy (`README.md:173-179`); the tool table.

"Credits and safety", sentence by sentence against `ledger.py`:

| README | Claim | Verdict |
| --- | --- | --- |
| 156 | Every HTTP request is recorded: tool calls, retries, attempts without a response, credit-endpoint reads | True (`ledger.py:508-561`, `439-449`). |
| 158 | Catalog and balance read at the start of each run; first use reads balance, balance, catalog, balance and uses the endpoints only if the balance did not move | True (`ledger.py:468-505`). Omits that the failed verification's reads can exhaust the run's budget (F-N4), and "the first time" is really "until one verification succeeds", which is every run with `--no-ledger`. |
| 158 | A successful balance read clears a blind ledger | True (`ledger.py:503-504`). |
| 160-165 | The four pre-request checks; call cap is planned requests times three | True (`ledger.py:171-188`, `cli.py:237`). "Refuses the request if the balance is unknown" does not hold for a stale persisted balance (F-N2). |
| 167 | Reserve: catalog price, else largest cost recorded for the tool, else 20 | True as written; the middle branch includes the 0 of a failed call (F-N1). |
| 169 | Cost from `X-Credits-Charged`, else the drop in `X-Credits-Remaining`, else the balance endpoint | True. |
| 169 | HTTP error status counts as 0 | True when no charged header and no balance evidence exist (`ledger.py:222-223`). |
| 169 | A negative charge counts as unknown | Imprecise: the header is ignored and the cost falls back to the balance drop; unknown only if that is unavailable too. Harmless. |
| 169 | Balance increase or missing balance count as unknown; unknown counts as at least 20 | True (`ledger.py:221`, `121-122`). |
| 169 | Blind when the cost cannot be established; refused until a later balance read succeeds | True (`ledger.py:240-241`, `173`). |
| 169 | Unreadable ledger file refuses every request | True. |
| 171 | The ledger file is not locked | True. |
| 181 | Six read-only SDK methods plus the two credit endpoints | True. |

False or incomplete:

| Location | Claim | Finding | Fix |
| --- | --- | --- | --- |
| `README.md:199` | "The expected result is 211 passed, 0 skipped." | Actual: 272 passed. | Change to 272 (blocking, one word). |
| `VERIFICATION.md:4`, `tests/README.md:132` | "see `DELIVERY.md`" | The file does not exist in the repository (`CLAUDE.md:53` plans it). | Create it at delivery or remove the references. |
| `README.md:121`, `164` | Refused when the balance cannot be determined | Not for a stale persisted balance (F-N2). | Fix F-N2 or qualify. |
| `README.md:158` | Stops using the endpoints for that run | The run is in practice refused at the default budget (F-N4). | Add one sentence. |
| `README.md:176` | A timed-out request may already have been billed | True, but the ledger can record such a call as 0 (F-N3). | Add one sentence or fix F-N3. |

## J. Other defects, ranked

High: none.

Medium:
1. **Reserve of 0 after a failed call lets a paid request through a cap** (F-N1). `ledger.py:115-118`, `150-154`. **Blocking.**
2. **Floor checked against a stale persisted balance** (F-N2). `ledger.py:500-505`, `170`. Acceptable for v1 if documented.
3. **Late-billed timeout recorded as 0** (F-N3). `ledger.py:218`, `523-536`. Acceptable for v1 if documented.
4. **README test count is wrong** (`README.md:199`). **Blocking** only in the sense that item I cannot pass with it; the fix is one number.

Low (acceptable known gaps; document where noted):
5. Failed endpoint verification exhausts the budget and reports a credit error for what is a network or verification problem (F-N4). A fresh ledger with the network down exits 4 with `credit budget 50` instead of an upstream error.
6. Semantically invalid ledger values are trusted or crash (F-N5).
7. Tolerant balance and catalog parsing (F-N6); a catalog price is used even when lower than a cost already observed for the tool (`ledger.py:151-152`). Using `max(price, seen)` would be stricter.
8. `from_env` defaults to the constant phase `"cli"` (`client.py:235`); a library caller who keeps the default ledger file shares one "per-run" budget and call cap across all runs. The CLI is unaffected (`cli.py:231`). The CLI phase id has one-second resolution, so two `cli.main()` calls in one process within a second share a budget (observed in my in-process probe; errs toward refusing).
9. A ledger write failure (`ledger.py:261-272`, for example a full disk) raises `OSError` out of `handle_request` after the response was received and billed.
10. Dangling `DELIVERY.md` references; stale 0.0.1 editable install in `.venv`.

Nothing found allows an order, a real-money payment, a non-GET request, or disclosure of the key.

## Overall: FAIL

A1-A6, B, C, D, E, G and H pass. F and I are PARTIAL, so the condition "A-I all pass" is not met. The remaining work is small.

Blocking list, with the minimal fix for each:

1. **F-N1 / J-1 — reserve of 0 after a failed call.** In `CreditLedger.tool_cost` (`ledger.py:115-118`) consider only entries with `200 <= e.status < 300`; with none, `reserve_for` must return `unknown_cost_value`. Add a regression test to `tests/test_ledger.py`: a ledger holding one 404 entry for the tool, no catalog price, `budget=0` (and a second case with a floor equal to the balance) -> `CreditBudgetExceeded` before any request is sent.
2. **I — `README.md:199`.** Replace "211 passed" with the real count (272 today; it will change when the regression test above is added).

Should be fixed or documented in the same pass, not blocking on their own:

3. **F-N2** — refuse tool requests when a floor is set and `start()` did not obtain a fresh balance, or say in `README.md:121`/`164` that a balance from an earlier run is used when the read fails.
4. **F-N3** — record `max(charged, balance drop)` when both are known, or add the limitation next to `README.md:176`.
5. **F-N4** — one README sentence: a failed verification counts its reads as unknown and normally ends the run.
6. Create `DELIVERY.md` or remove the two references to it.
