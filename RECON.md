# Phase 0 recon: 2026-11-22

Branch `feat/adapter-v1`, taken from `test/hpsilab-fixtures-safety` at `c06bb13`. The
GitHub default branch is `test/hpsilab-fixtures-safety`, and there is no `main`
branch on the remote. The repository is private, and Faisal has write access.

## File tree at the base commit

```
.gitattributes .gitignore .gitleaks.toml .pre-commit-config.yaml
README.md VERIFICATION.md pyproject.toml
src/hpsilab_research_adapter/{__init__,__main__,cli}.py
tests/{conftest,sdk_contract,readonly_scan}.py
tests/test_{cli,errors,fixtures,readonly,secret_scanner}.py
tests/fixtures/{_manifest.json,README.md,<6 tools>_empty.json}
tools/scan_secrets.py
```

The package is `src/hpsilab_research_adapter/`. The brief's `adapter/` paths map to it.

## Baseline (Python 3.12.4, fresh `.venv`, hpsilab-mcp 0.14.2 from PyPI)

| Check | Result |
| --- | --- |
| pytest | 52 passed, 18 skipped, 0 failed |
| ruff check / format --check | pass / pass (16 files) |
| pip check | pass |
| `tools/scan_secrets.py` (gitleaks present locally) | pass, no findings |
| `python -m hpsilab_research_adapter --status` | runs |

VERIFICATION.md (16 Nov) recorded 51 passed and 19 skipped. The difference is that
gitleaks is installed on this machine, so the scanner integration test now runs.

## The 18 skips

* **12 in `tests/test_errors.py`.** The `sdk_contract` fixture in `conftest.py`
  skips them with "BLOCKED: Faisal's client...". They cover 429 once then success,
  429 three times, credits and auth failing immediately, the timeout policy, 500,
  502, 503 and 504 three times each, a missing key, an unexpected error, and
  backoff ordering.
* **6 in `tests/test_fixtures.py::test_full_and_missing_response_compatibility_is_pending`.**
  These wait for the full and missing-field fixtures, which need real shapes.

## Contracts Rahmat's tests already fix

* Errors: `AuthError`, `RateLimited`, `CreditsExhausted`, `Timeout`, `UpstreamError`.
* 429 and 5xx: exactly 3 requests and 2 sleeps, with request/sleep/request/sleep/request ordering.
* Credits and auth failures: 1 request and 0 sleeps. A missing key: 0 requests.
* Timeout attempts are an open decision, 1 to 3. We use `policy.TIMEOUT_ATTEMPTS = 1`.
* An unexpected exception propagates as the same object and is not retried.
* No exception chain may contain the credential (`assert_sanitized` walks
  `__cause__` and `__context__`).
* The `request` mock goes under the retry loop, and `sleep` is a seam we inject.
  `time.sleep` is forbidden in the tests. Caches must be disabled.
* `make_failure` must build **real** SDK exceptions, from `hpsilab_mcp.errors`.
* `conftest.offline_only` blocks sockets and DNS and deletes every `HPSILAB*`
  environment variable.
* The read-only AST scan covers all production `.py` files, `tools/` included. It
  rejects broker imports and `submit_order`, `place_order` and `execute_order`,
  plus Mizan imports.
* `test_cli.py` currently requires `research|analyze|options|credits` to exit 2,
  and requires `--status` to print "pending". Phase 3 D has to update these tests
  together with the CLI. That is an agreed change to the tests, not a weakening of them.

## Pre-commit

These are local system hooks: a gitleaks staged scan, the read-only boundary
pytest, ruff check, and ruff format. Nothing is downloaded.

## SDK facts verified in the hpsilab-mcp 0.14.2 source

* The SDK builds a paying wallet from `HPSILAB_X402_PRIVATE_KEY` (`payments.wallet_from_env`)
  even without the extra. The adapter refuses to run if it is set, and passes
  `payment_mode=CREDITS_ONLY`.
* There is no retry for timeouts, connection errors, 429 or 5xx. The only retry
  is a single 402 retry, which needs a wallet. Retries are therefore ours alone.
* A 401 opens the SDK's auth circuit breaker, after which every call raises
  `HpsiMcpConfigError`. The client also has a breaker for insufficient credits.
* The SDK never reads `X-Credits-Remaining` and has no balance method. (Its README,
  read later, documents `GET /api/credits/balance` and `/api/credits/catalog`, which
  the ledger now uses.) We capture the header through `HpsiMcpClient(transport=...)` (`ledger.RecordingTransport`).
* `include_metadata` exists only on `get_ai_prediction`.
* With no key and no wallet, the SDK sends `X-HPSILAB-Payment-Mode: anonymous`.
  We raise `AuthError` before constructing the client.
