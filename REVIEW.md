# Independent review: HPSILab research adapter v1

- Date: 2026-11-22
- Branch: `feat/adapter-v1`
- Commit reviewed: `2bde3877bb7c04a87dc754c1b269181e2f1117cc` (working tree clean)
- Reviewer: independent; did not write this code. No file other than this one was created or edited. Nothing was committed or pushed.
- Method: read all tracked files and the wrapped SDK source (`.venv/Lib/site-packages/hpsilab_mcp/`, 0.14.2), ran the quality gates, and ran offline behavioural probes against `httpx.MockTransport` with sockets blocked and an obviously fake key. No network call to HPSILab was made. `.probe/` and `.credits/` were not opened; only their ignore status was checked.

## Summary

| Item | Verdict | One-line reason |
| --- | --- | --- |
| A1 Independent / not endorsed | PASS | Stated in README, CLI help and package description. |
| A2 Name only, no logo | PASS | 61 tracked files, all text; no image, mark or image reference in tree or history. |
| A3 README links https://hpsilab.com | PASS | `README.md:19` (bare URL, autolinked). |
| A4 Research only, read-only | PASS | Wording present; code verified under B. |
| A5 No-responsibility statement | PASS | `README.md:11`. |
| A6 MIT scope limited to adapter code | PASS | `LICENSE:23-24`, `README.md:238`. |
| B Read-only, six SDK methods only | PASS | Only six GET methods reachable; dispatch is allowlisted by dict lookup. Notes below. |
| C No secrets, no real data | PASS | gitleaks clean on tree and on all history; fixtures fabricated; shapes hold keys and types only. |
| D x402 / real-money payment impossible | PASS | Refusal in every entry point, `CREDITS_ONLY` forced, no wallet, extra not installed. |
| E Missing key raises before SDK client | PASS | 0 SDK clients constructed for 5 missing-key cases. |
| F Retries don't burn credits / ledger | **FAIL** | Retry policy is correct, but the ledger's cap can be exceeded, the floor can be skipped, failed attempts are not recorded, and unknown costs become 0. |
| G Key never printed, logged or in exceptions | PASS | Fixed messages, raised outside the `except`; no leak in probes with the key echoed in bodies. |
| H Quality gate | PASS | 211 passed, 0 skipped; ruff, format, pip check clean; four protected files unchanged from `c06bb13`. |
| I Docs accuracy | **FAIL** | Several README claims about the ledger are false (follow from F); stale and contradictory secondary docs. |
| J Other defects | **FAIL** | 2 high, 4 medium, 5 low. Ranked list below. |

## A. TERMS.md

**A1 PASS.** `README.md:7` reproduces the term verbatim. Also `cli.py:58` (shown in `--help`), `pyproject.toml:8`, `README.md:234`.

**A2 PASS.** `git ls-files -z | xargs -0 file` reports no non-text file. `git log --all --name-status` shows only additions of the same 61 text files; nothing binary was ever added and removed. `git grep -i` for `logo`, `![`, `<img`, `.svg`, `.png`, `.jpg`, `data:image`, `badge`, `shields.io`, the SDK's stylized mark, `®`, `™` returns only `TERMS.md:8-9` and `VERIFICATION.md:89` (a sentence about a file in a different project). No untracked, non-ignored files exist.

**A3 PASS.** `README.md:19`: `Website: https://hpsilab.com`. It is a bare URL rather than `[text](url)`; GitHub and PyPI autolink it. Note only.

**A4 PASS.** `README.md:9` carries the full sentence including "directly or through another service". `cli.py:56-57`, `cli.py:151`. Code evidence is under B.

**A5 PASS.** `README.md:11`, verbatim. It appears only in the README.

**A6 PASS.** `LICENSE:23-24` and `README.md:238`. `pyproject.toml:9-10` declares `MIT` with `license-files`.

## B. Read-only — PASS

- Dispatch: `client.py:280` resolves the tool with `TOOLS.get(tool)`; unknown names raise `ValueError` (`client.py:282`). `client.py:254` then calls `getattr(self._sdk, spec.sdk_method)` where `spec` comes only from the frozen `ToolSpec` entries at `tools.py:32-37`. Probe: `run("generate_stock_images")`, `run("register_account")`, `run("get_monte_carlo")`, `run("__class__")` all raise `ValueError`; nothing is sent. The CLI restricts `--tool` with argparse `choices` (`cli.py:99`).
- Wire check (mock transport): the six tools sent exactly `GET /api/analyze_stock/TEST`, `GET /api/ai_prediction/TEST`, `GET /api/iv_batch`, `GET /api/option_pressure/TEST`, `GET /api/pretrade-risk-scan`, `GET /api/monte_carlo/TEST`. SDK source confirms each uses `_get` (SDK `client.py:464-526`); `generate_*` and `register_account` use `_post`/`POST` (SDK `client.py:528-628`) and are never referenced.
- Search of all tracked files (not only `.py`) for `POST|PUT|DELETE|PATCH`, `.post(`, `generate_`, `register`, `set_wallet`, `set_payment`, `call_tool`, broker names, `order`: hits are documentation sentences and the scanner's own inventories. The only HTTP verb literal in code is `"GET"` (`ledger.py:321`, `417`, `444`).
- Ticker is constrained to `^[A-Z][A-Z0-9.\-]{0,9}$` (`client.py:67-77`, `cli.py:36`), so it cannot alter the path; `run("analyze_stock", "../x")` raises.

Notes, not failures:
1. Besides the six SDK methods, the adapter sends raw `GET /api/credits/balance` and `GET /api/credits/catalog` with the bearer key, outside the SDK (`ledger.py:318-322`, `412-417`; `tools/ship_check.py:50`). Both are read-only and documented in the SDK README. The README's sentence "The adapter calls only the six read-only SDK methods" (`README.md:168`) is true of SDK methods but omits these two requests.
2. `ALLOWED_SDK_METHODS` (`tools.py:42`) is defined and never enforced. `TOOLS` is a mutable module dict and `ResearchClient(request=...)` accepts any callable (`client.py:192`). Neither is reachable from user input; a one-line assertion in `_sdk_request` would make the allowlist real.
3. `tests/readonly_scan.py` cannot see the non-literal `getattr` at `client.py:254` or `tools/probe.py:172`; its own docstring says so. The guarantee rests on the dict lookup, not on the AST test.

## C. No secrets, no real data — PASS

- `.venv\Scripts\python.exe tools\scan_secrets.py` -> `Secret scan passed: no findings.` (exit 0). `--self-test` -> canary detected (exit 0).
- `tools/scan_secrets.py` scans the working tree only (`detect --no-git`, `tools/scan_secrets.py:22`). I additionally ran `gitleaks detect --source . --config .gitleaks.toml --redact --log-opts="--all"` (gitleaks 8.30.1): `14 commits scanned ... no leaks found`.
- `.probe/` and `.credits/` are ignored (`.gitignore:17-18`) and `git ls-files .probe .credits` is empty; neither path appears anywhere in `git log --all --name-status`.
- Fixtures: across all 18 files the only string values not starting with `fake-` are `TEST`, `2000-01-01`, `2000-01-02`; the only numbers are `0.5`, `1`, `1.25`, `2`.
- `schemas/*.shape.json`: every leaf is a JSON type name, apart from the five header fields (`tool`, `sdk_method`, `sdk_version`, `probed_ticker: "<TICKER>"`, `note`). No numeric leaf exists in any shape file. Schemas have a single commit (`6f214cb`), whose diff contains no ticker or market value.
- Informational: `policy.py:22-25` and `CLAUDE.md:39` commit account-specific operating numbers (budgets 60/60/150, balance floor 1,800), and commit `6f214cb`'s subject records a 38-credit spend. These are not credentials or provider data.

## D. x402 / real-money payment — PASS

- Dependency: `pyproject.toml:15` is `hpsilab-mcp==0.14.2` with no extra. `x402` appears in the repo only in warnings and guards. `pip list` in `.venv` shows no `x402`, `eth-account` or `web3`.
- No wallet is ever passed: `client.py:209-214` and `tools/probe.py:142` pass `payment_mode=CREDITS_ONLY` and no `wallet=`. `set_wallet` / `set_payment_policy` are never referenced.
- Env guard in every entry point: `client.py:200-203` (direct constructor), `client.py:234-237` (`from_env`, hence the CLI), `tools/probe.py:127-128`, `tools/ship_check.py:93-95`. Run results with a fake value: CLI exit 3 `UnsafeConfiguration`; `ship_check.py` prints `REFUSED` exit 3; `probe.py` raises `UnsafeConfiguration` (uncaught traceback, exit 1) before any client exists.
- Second layer: `client.py:215-217` and `tools/probe.py:145-146` refuse if `payment_policy.pays`.
- SDK trace: the wallet is resolved once, in the constructor (SDK `client.py:184`, `payments.py:142-154`); `decide` refuses whenever `not policy.pays` (SDK `policy.py:382`). Probe "env var set after the client is built, server answers 402 with a signable `accepts` offer": `wallet=None`, `pays=False`, exactly one GET with no payment header, `CreditsExhausted`, no retry.
- The raw credit-endpoint GETs in `ledger.py` bypass the SDK entirely and contain no payment logic.

## E. Missing key — PASS

`client.py:198-199` raises `AuthError` before `HpsiMcpClient(...)` at `client.py:209`; `from_env` raises at `client.py:231-233` before the ledger or transport exist. With `HpsiMcpClient` wrapped by a counter, `ResearchClient(None)`, `("")`, `("   ")`, `(123)` and `from_env()` with no variable all raised `AuthError` and constructed 0 SDK clients. This guard matters: with no key the SDK does not raise, it switches to anonymous mode (SDK `client.py:226-227`). CLI: no key -> `error: AuthError: HPSILab API key is missing.` exit 3; whitespace-only key -> same.

## F. Retries and the credit ledger — FAIL

What passes (verified by probe, sleep injected):

| Upstream | Requests sent | Sleeps | Raised |
| --- | --- | --- | --- |
| 429 with `Retry-After: 1` | 3 | 1.0, 1.0 | `RateLimited` |
| 503 with balance header | 3 | 1.0, 2.0 | `UpstreamError` |
| connection error | 3 | 1.0, 2.0 | `UpstreamError` |
| read timeout | 1 | none | `Timeout` |
| 401 | 1 | none | `AuthError` |
| 402 insufficient credits | 1 | none | `CreditsExhausted` |
| 402 x402 offer | 1 | none | `CreditsExhausted` |
| 404, 422 | 1 | none | `UpstreamError` |

`ledger.authorize` runs before `inner.handle_request` (`ledger.py:383-391`), and every SDK attempt, retries included, enters `handle_request`. The retry policy itself is sound. The failures are in the ledger.

**F-1 (high). `--max-credits` can be exceeded when the price is unknown, which is the normal case.**
`ledger.py:129` reserves `price` or else `max_cost`, and `max_cost` is 1 when nothing has been recorded (`ledger.py:88-90`). The catalog is only loaded when the persisted ledger carries `meta_free_verified` (`client.py:248`, `258`), and only `tools/probe.py:154` ever sets that flag. A user on a fresh ledger or with `--no-ledger` therefore never has prices (probe: `catalog_pending: False prices: {}`).
Probe: budget 5, tool charges 10 -> request sent, `spent: 10 budget: 5`. The cap is breached by `price - 1` on the first call and by `price - largest_seen` afterwards.
Fix: in `from_env`, always load the catalog before the first tool request (the endpoint is documented in the SDK README), and in `authorize` refuse when `price is None` instead of reserving 1 (or reserve the highest catalog price). Add a test with a tool priced above the remaining budget.

**F-2 (medium). `--min-balance` is not enforced until a balance is known.**
`ledger.py:140`: `floor is not None and balance is not None and ...`. With no recorded balance the check is skipped.
Probe: floor 1800, real balance 100, fresh ledger -> request sent, balance now 90; only the second request is refused. With a persisted ledger the check uses the last balance from an earlier run, which may be stale.
Fix: when `floor` is set and `last_balance` is `None`, call `read_balance` first and refuse if it still cannot be determined.

**F-3 (high). Attempts that end in a transport exception are never recorded, so the call cap does not count them.**
`ledger.py:391` calls `self.inner.handle_request(request)` with no `try`. On `ReadError`, `ConnectError` or a timeout the function exits before `ledger.record` (`ledger.py:400`).
Probe: `call_cap=1`, connection errors -> one `run()` sent 3 requests, a second `run()` sent 3 more; `ledger entries: 0, calls: 0, blind: False`. A read timeout, which `policy.py:5-6` itself says may already have been billed, also leaves no entry and does not blind the ledger; the next request is authorized as if nothing happened.
Fix: wrap the inner call; on `httpx.TransportError` record an entry (status 0, cost `None`) so it counts toward the cap, and for errors after the request was written (read errors, read timeouts) mark the ledger blind or force a balance read before the next request; then re-raise.

**F-4 (medium). The balance fallback request bypasses `authorize`, and a failed one leaves no trace.**
`ledger.py:397` -> `_meta_balance_quiet` (`ledger.py:412-436`) sends `GET /api/credits/balance` with no budget, cap or blind check, whether or not the endpoint has been proven free, and records it only `if balance is not None` (`ledger.py:425`).
Probe: `budget=1, call_cap=1`, response without credit headers, balance endpoint 500 -> paths `['/api/monte_carlo/TEST', '/api/credits/balance']`, ledger entries: one. The second HTTP request is absent from the ledger.
Fix: record every meta request regardless of outcome, and either gate the fallback on `meta_free_verified` or reserve for it.

**F-5 (medium). Unknown costs are silently recorded as 0 or less.**
- `ledger.py:171`: `cost = max(0, before - balance_after)`. If the balance rose between two readings (top-up, or a stale `before` from an old run) the call is recorded as free. Probe: balances 1000 then 1490, no charged header -> `costs: [None, 0]`, `spent: 1` for two real calls.
- `ledger.py:172-173`: any status >= 400 without a charged header is recorded as cost 0 on the strength of a sentence in the SDK README. This is an assumption, not a measurement.
- `ledger.py:219-229`: `_int` truncates (`"0.5"` -> 0) and accepts negatives. Probe: `X-Credits-Charged: -50` -> `spent: -50`, which enlarges the budget.
- `ledger.py:100-105`: an unknown cost is counted at the largest cost seen, which is 1 if none has been seen.
Fix: treat a negative balance delta as unknown (`None`), clamp charged to >= 0, round up rather than truncate, and count unknown costs at the catalog maximum.

**F-6 (low). A non-finite header crashes the run.** `ledger.py:226` `int(float("inf"))` raises `OverflowError`, which is caught nowhere. Probe: `X-Credits-Remaining: inf` -> `OverflowError` out of `client.run`. Fix: catch `(ValueError, OverflowError)`.

**F-7 (medium). A directly constructed client has no ledger at all.** `client.py:194`, `207-214`: `ResearchClient(api_key)` passes `transport=None` to the SDK. Probe: `ResearchClient(KEY)._transport` is `None`. Only `from_env` installs `RecordingTransport` (`client.py:239-247`). The class is public and the tests construct it this way. Fix: build a default `RecordingTransport` in `__init__` when no transport and no `request` seam is supplied, or make the constructor private and document `from_env` as the only supported entry.

Test coverage note: `CreditLedger`/`RecordingTransport` appear in only two tests (`tests/test_client.py:201-222`). No test exercises the floor, an unknown price, a transport exception inside the recording transport, or the fallback path.

## G. Key handling — PASS

- `--status` prints only yes/no (`cli.py:149`, `155`). Run with a fake key: the value does not appear in the output.
- All adapter error messages are fixed strings (`client.py:103-174`, `199`, `202`, `217`); `UnsafeConfiguration` names the variable, never its value.
- `client.py:305-306` raises the adapter error after the `try/except` has ended, so `__context__` is `None`, not merely suppressed. Probe with the fake key echoed in 401, 404, 422 and 503 bodies: key absent from `str`, `repr` and `__dict__`; `__cause__` and `__context__` are `None`.
- Ledger entries hold tool, ticker, status, balances and header names only (`ledger.py:51-63`).
- `tools/probe.py:181` prints the exception class name and status only; `tools/ship_check.py` prints counts and shapes.
- `tests/test_errors.py:21-31` (`assert_sanitized`) walks `__cause__`/`__context__`; it is unchanged from the base commit and passes.

Notes: (1) `client.py:298-299` re-raises unclassified SDK errors unchanged, with the SDK's own message and body. In 0.14.2 the only such raises are in `register_account` paths (SDK `client.py:84`, `91`), which are unreachable here, so this is latent. (2) The key is kept on `ResearchClient._api_key` (`client.py:204`) in addition to the SDK's copy; it is used only at `client.py:263`.

## H. Quality gate — PASS

| Command | Result |
| --- | --- |
| `python -m pytest --basetemp=.test-tmp -q` | `211 passed in 2.37s` (0 skipped, 0 failed) |
| `python -m ruff check .` | `All checks passed!` |
| `python -m ruff format --check .` | `30 files already formatted` |
| `python -m pip check` | `No broken requirements found.` |
| `python tools\scan_secrets.py` | `Secret scan passed: no findings.` |
| `python -m pre_commit validate-config` | exit 0 |

`git diff c06bb13 -- tests/test_readonly.py tests/readonly_scan.py tests/test_secret_scanner.py tools/scan_secrets.py` is empty. `tests/test_errors.py` is also unchanged. `tests/conftest.py` changed only in the `sdk_contract` fixture (skip replaced by a binding to the real client and real SDK exceptions); the `offline_only` fixture is untouched.

Note: the editable install in `.venv` still reports distribution version 0.0.1 (`pip show`), while `pyproject.toml:7` and `--version` say 0.1.0. Re-run `pip install -e ".[dev]"` before shipping.

## I. Docs accuracy — FAIL

Verified true: the `--help` block (`README.md:69-99`) matches real output byte for byte; exit codes 0/2/3 for help, status, version, bad ticker, negative budget, unknown tool, `--ledger` with `--no-ledger`, missing key and x402 (`README.md:127-131`); "211 passed, 0 skipped" (`README.md:186`); scanner exit codes (`README.md:206`); hook list (`README.md:218` vs `.pre-commit-config.yaml`); SDK metadata statements (`README.md:21`, `23` vs SDK `METADATA:4`, `7`, `114-116`); six-tool table and GET/POST claim (`README.md:27-36`); library example signature (`README.md:139`).

False or misleading:

| Location | Claim | Finding | Fix |
| --- | --- | --- | --- |
| `README.md:166` | "every retry is made by the adapter and is counted in the ledger" | False for connection-error and timeout attempts (F-3: 6 requests, 0 entries). | Fix F-3, or state the exception. |
| `README.md:149` | "Every request goes through the credit ledger, including retries." | The balance and catalog GETs skip `authorize` (F-4); a directly constructed client has no ledger (F-7). | Fix F-4 and F-7, or qualify. |
| `README.md:88`, `117` | `--max-credits`: "Credit cap for this run." | Can be exceeded (F-1). | Fix F-1, or say it is a pre-send estimate when prices are unknown. |
| `README.md:89`, `118` | `--min-balance`: "Stop if the account balance would drop below N." | Not enforced on the first request of a fresh ledger (F-2). | Fix F-2. |
| `README.md:156` | "reserves the tool's catalog price when one is loaded" | True, but the CLI never loads the catalog unless `tools/probe.py` has marked the ledger file. Not disclosed. | Load the catalog in `from_env`, or document it. |
| `README.md:158` | "If that also fails to give a balance, the ledger becomes blind" | Not when `X-Credits-Charged` is present (`ledger.py:190`). Also no recovery path is documented: `blind` is persisted and never cleared (see J-4). | Correct the sentence; document recovery. |
| `README.md:168` | "calls only the six read-only SDK methods" | Omits the two raw credit-endpoint GETs. | Add them. |
| `README.md:128` | Exit 1 is "any other adapter error" | Unhandled non-adapter exceptions (normalizer `ValueError`, `OverflowError`, corrupt ledger JSON) also exit 1, with a traceback and without printing completed results, contrary to `README.md:111`. | See J-5. |
| `README.md:17` | HTML comment "owner may replace with the approved wording drafted earlier" | Leftover placeholder in a shipping README. | Resolve or remove. |
| `README.md:119-121` | `--total-credits` "across runs" | Silently meaningless with `--no-ledger`; the default ledger path is relative to the current directory, so runs from different directories do not share a budget. Unverifiable as written. | Reject the combination; document the path. |
| `RECON.md:79` | "there is no balance endpoint" | Contradicted by `ledger.py:43` and SDK `METADATA:136-137`. | Correct. |
| `tests/fixtures/README.md:3` | "No provider calls were made." | Contradicted by the next line (shapes come from a live probe). | Reword. |
| `CLAUDE.md:40` | "If a response has no balance header, the ledger goes blind" | Outdated; there is now an endpoint fallback. | Update or drop the file from the release. |
| `VERIFICATION.md` | "No ... SDK client"; "51 passed, 19 skipped"; path `C:\Projects\ALPACA\...` | A 16 Nov record that no longer describes this branch; `tests/README.md:132` still points readers to it. | Mark as historical or replace with current results. |

## J. Other defects, ranked

1. **High — budget overshoot with unknown prices.** F-1. `ledger.py:88-90`, `129`, `134`; `client.py:248`, `258`.
2. **High — transport-exception attempts invisible to the ledger and the call cap.** F-3. `ledger.py:391`.
3. **Medium — balance floor skipped while the balance is unknown.** F-2. `ledger.py:140`.
4. **Medium — a blind ledger is permanent and misreported.** `blind` is persisted (`ledger.py:210`), reloaded (`ledger.py:76`) and assigned `True` at one place only (`ledger.py:191`); nothing ever clears it. One 503 without credit headers while the balance endpoint is also failing (probe F5) blinds the file, the retry is refused as `CreditBudgetExceeded` (CLI exit 4, "credit problem") although the cause was an outage, and every later run with that ledger is refused until the user edits the JSON by hand. Fix: on start, if blind, attempt one balance read and clear the flag on success; do not blind on status >= 500.
5. **Medium — a normalizer error after a billed call crashes the CLI and discards completed results.** `normalize.py:209` raises `ValueError` for a top-level list on a non-wrapped tool; `cli.py:234` catches only `AdapterError`, so `_emit` is never reached. Probe: `iv_radar` returning `[1, 2]` -> `ValueError`, 5 credits spent. Fix: wrap normalizer failures in `UpstreamError` in `client.run`, and emit partial results in a `finally`.
6. **Medium — `missing_fields` is wrong for `ai_prediction`.** `normalize.py:207` takes the union of keys across records, so a field absent from some records is not reported. The repo's own fixture `tests/fixtures/ai_prediction_missing_field.json` (which omits `model_name` from `data[0]`) normalizes to `missing_fields: ()`. Fix: report a field as missing if any record lacks it (intersection), and add that fixture to `test_missing_one_field`.
7. **Low — `OverflowError` on a non-finite credit header; negative charges accepted.** F-6, F-5. `ledger.py:219-229`.
8. **Low — ledger file is not safe for concurrent runs.** Each process loads the file once (`ledger.py:73-77`) and rewrites it whole through a fixed `ledger.tmp` (`ledger.py:204-215`); two simultaneous CLI runs lose each other's entries, which undercounts `--total-credits`. A corrupt file raises an uncaught `JSONDecodeError`/`TypeError` at `ledger.py:74-75`.
9. **Low — `ALLOWED_SDK_METHODS` is never enforced.** `tools.py:42`, `client.py:254`. Add `assert spec.sdk_method in ALLOWED_SDK_METHODS`.
10. **Low — `Result.error` is dead.** Nothing sets it (`types.py:30`; `client.run` raises instead), so `result.ok` is always `True` and the CLI branch at `cli.py:166-167` is unreachable. An HTTP 200 whose body reports failure (for example `analyze_stock` with `failedTools`) is reported as success.
11. **Low — one failing ticker aborts the whole run.** `cli.py:230-237`: a 404 for one symbol ends a multi-ticker run with exit 5. Also, commit `6f214cb` records 38 credits for one pass over the six tools; if that reflects tool prices, the documented default `hpsilab NVDA` (`--tool all`, `--max-credits 20`) cannot complete. I could not verify per-tool prices without opening `.credits/`, so this is unconfirmed.

## Overall: FAIL

Blocking items:

- **F** — credit ledger: cap can be exceeded (F-1), floor skipped (F-2), failed attempts unrecorded (F-3), fallback request bypasses checks (F-4), unknown costs recorded as 0 or negative (F-5), no ledger on direct construction (F-7).
- **I** — README statements about the ledger at lines 88-89, 117-118, 149, 158, 166 and 168 are false or incomplete; placeholder at line 17; contradictions in `RECON.md`, `tests/fixtures/README.md`, `CLAUDE.md`, `VERIFICATION.md`.
- **J** — items 1 to 6 (two high, four medium).

Items A1-A6, B, C, D, E, G and H pass. Nothing found allows an order, a payment in real money, or disclosure of the key.
