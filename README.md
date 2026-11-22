# HPSILab Research Adapter

A read-only Python command-line tool and library that wraps six HPSILab research tools through the `hpsilab-mcp` 0.14.2 SDK. It runs each tool for one or more tickers, normalizes the responses into a common result type, and records credit use in a local ledger so that spending can be capped.

> **Notice**
>
> This is an independent integration. It is not an official HPSILab product, and HPSILab has not endorsed it.
>
> The adapter is for research and analysis only. It is read-only. It never generates, approves, submits or executes real-money orders, directly or through another service. HPSILab outputs must never generate, approve, authorize, route or execute trades, directly or indirectly.
>
> HPSILab accepts no responsibility for real-money trades, losses or their consequences.
>
> This repository has no broker or Mizan integration and must remain separate from Mizan's risk checks, proposals and authorization.

## About HPSILab

<!-- About HPSILab: owner may replace with the approved wording drafted earlier -->

HPSILab operates the research API that this adapter calls. Website: https://hpsilab.com

The adapter uses the `hpsilab-mcp` Python SDK, version 0.14.2, published on PyPI. The package metadata lists the author as Haiyun Hu and describes the SDK as a Python SDK for the HPSILab quantitative finance API (options analytics, IV surface modeling, Monte Carlo simulation, and AI-driven predictions).

Usage of the HPSILab API is metered in Credits. The SDK README states that Credits are spent on SDK and MCP calls, that one Credit is one unit of fresh compute, and that a call that fails is never charged.

## Tools

The CLI runs six research tools. Each one maps to one read-only SDK method. All six use HTTP GET in the SDK. The adapter never calls a `generate_*` method, which is a POST.

| CLI tool name | SDK method | Description |
| --- | --- | --- |
| `analyze_stock` | `analyze_stock` | Runs the `analyze_stock` method. |
| `ai_prediction` | `get_ai_prediction` | Runs the `get_ai_prediction` method. This is the only method called with `include_metadata=True`. |
| `iv_radar` | `get_iv_radar` | Runs the `get_iv_radar` method. |
| `option_pressure` | `get_option_pressure` | Runs the `get_option_pressure` method. |
| `pretrade_risk_scan` | `get_pretrade_risk_scan` | Runs the `get_pretrade_risk_scan` method. Research output only; it grants no trading authority. |
| `monte_carlo` | `get_monte_carlo` | Runs the `get_monte_carlo` method. |

## Install

Requirements: Python 3.12 or later.

```powershell
cd C:\path\to\hpsilab-research-adapter
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install .
```

This installs the adapter and the plain `hpsilab-mcp==0.14.2` SDK, with its dependencies.

**Never install `hpsilab-mcp[x402]`, and never set `HPSILAB_X402_PRIVATE_KEY`. The x402 payment path pays real USDC per call. The adapter refuses to run if `HPSILAB_X402_PRIVATE_KEY` is set.**

## Configure

The adapter reads the API key from the `HPSILAB_API_KEY` environment variable. Set it in the shell you run the tool from:

```powershell
$env:HPSILAB_API_KEY = "<your-key>"
```

Do not write the key into a file in this repository, and do not commit it. If the variable is missing, the adapter raises `AuthError` before it creates the SDK client, and the CLI exits with code 3.

`--status` reports only whether the key is set (`yes` or `no`). It never prints the value and makes no network calls.

## Usage

Real output of `hpsilab --help`:

```
usage: hpsilab [-h]
               [--tool {all,analyze_stock,ai_prediction,iv_radar,option_pressure,pretrade_risk_scan,monte_carlo}]
               [--json] [--max-credits N] [--min-balance N]
               [--total-credits N] [--ledger PATH | --no-ledger] [--status]
               [--version]
               [TICKER ...]

HPSILab research-only CLI. Research and analysis only. The tool is read-only:
it never generates, approves, submits or executes orders.
Independent integration, not an official or endorsed HPSILab product.

positional arguments:
  TICKER                ticker symbol(s), for example NVDA MSFT

options:
  -h, --help            show this help message and exit
  --tool {all,analyze_stock,ai_prediction,iv_radar,option_pressure,pretrade_risk_scan,monte_carlo}
                        research tool to run (default: all)
  --json                print a JSON array, not text
  --max-credits N       credit cap for this run (default: 20)
  --min-balance N       stop if the account balance would drop below N
                        (default: none)
  --total-credits N     total credit budget across runs (default: none)
  --ledger PATH         credit ledger file (default: .credits/ledger.json)
  --no-ledger           do not persist a credit ledger
  --status              show configuration status, no network access
  --version             show program's version number and exit

Live runs need HPSILAB_API_KEY in the environment. Use --status to check
configuration without any network access. Every live request is counted
against the credit budget (see --max-credits, --min-balance, --total-credits).
```

Examples. Both make live requests and spend Credits, so set a key first:

```powershell
hpsilab NVDA --tool analyze_stock
hpsilab AAPL SPY --tool all --json
```

Tickers are case-insensitive and are converted to upper case. A ticker starts with a letter and may contain letters, digits, `.` and `-`, up to 10 characters in total. `--tool all` is the default. Each ticker and tool pair is one planned request, so `AAPL SPY --tool all` plans 12 requests.

Text output prints one block per result. `--json` prints a JSON array of the same results. If a run stops with an error, the results already completed are printed first, and the error message goes to stderr.

### Credit flags

| Flag | Default | Meaning |
| --- | --- | --- |
| `--max-credits N` | 20 | Credit cap for this run. |
| `--min-balance N` | none | Stop if the account balance would drop below N. |
| `--total-credits N` | none | Total credit budget across runs, enforced from the persisted ledger. |
| `--ledger PATH` | `.credits/ledger.json` | Ledger file that records every request. Cannot be combined with `--no-ledger`. |
| `--no-ledger` | off | Do not persist a ledger. The per-run limits still apply in memory. |

### Exit codes

| Code | Meaning | Errors that map to it |
| --- | --- | --- |
| 0 | Success. Also used by `--help`, `--status` and `--version`. | None |
| 1 | Any other adapter error. This is a fallback; every adapter error class listed in this README has its own code. | Other `AdapterError` |
| 2 | Usage error, for example an invalid ticker, a negative budget or an unknown `--tool`. | argparse errors |
| 3 | Authentication or configuration problem. | `AuthError` (key missing, or HPSILab rejected it), `UnsafeConfiguration` (`HPSILAB_X402_PRIVATE_KEY` is set) |
| 4 | Credit problem. | `CreditsExhausted` (the account cannot pay for the call), `CreditBudgetExceeded` (a local cap, the total budget or the balance floor would be crossed; refused before sending) |
| 5 | Upstream problem that persisted after the retry policy. | `RateLimited`, `Timeout`, `UpstreamError` |

### Library example

```python
from hpsilab_research_adapter.client import ResearchClient

with ResearchClient.from_env(ledger_path=None, max_credits=10, call_cap=6) as client:
    result = client.run("analyze_stock", "NVDA")  # returns a Result
    if result.ok:
        print(result.tool, result.ticker, sorted(result.data))
```

`ResearchClient.from_env(...)` reads `HPSILAB_API_KEY` and raises `AuthError` if it is missing. `client.run(tool, ticker)` takes one of the six CLI tool names and returns a `Result` (from `hpsilab_research_adapter.types`) with the fields `tool`, `ticker`, `data`, `horizon`, `source_fields`, `missing_fields` and `error`. On failure it raises the adapter error for that case instead.

## Credits and safety

Billing is in Credits. Every request goes through the credit ledger, including retries. Before a request is sent, the ledger checks:

- the per-run credit budget (`--max-credits`),
- the optional total budget across runs (`--total-credits`),
- the optional balance floor (`--min-balance`),
- and the per-run call cap, which is the number of planned requests times the three attempt limit.

Before each request, the ledger reserves the tool's catalog price when one is loaded. Otherwise it reserves the largest per-call cost recorded so far, or 1 Credit if none is recorded.

After each response, the ledger reads `X-Credits-Charged` and `X-Credits-Remaining`. If the balance header is missing, the ledger calls `GET /api/credits/balance`. If that also fails to give a balance, the ledger becomes blind: it refuses every later request while it stays blind.

Retry policy:

- HTTP 429, HTTP 5xx and connection errors: up to 3 attempts in total, with backoff between attempts.
- Timeouts: 1 attempt only. A timed-out request may already have been billed, so it is not repeated.
- Credit and authentication errors: never retried.

Failed calls are not charged, per the SDK README. The SDK itself does not retry, so every retry is made by the adapter and is counted in the ledger.

The adapter calls only the six read-only SDK methods listed above. It does not place, submit, route or execute orders, and it has no broker integration.

## Development

Install the development extras into the project virtual environment:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

### Tests

The test suite runs offline and makes no network calls:

```powershell
.\.venv\Scripts\python.exe -m pytest --basetemp=.test-tmp
```

The expected result is 168 passed and 6 skipped. The 6 skipped cases are the full and missing-field fixture checks, which wait for documented response structures. See [tests/README.md](tests/README.md) for details.

The offline suite guarantees the following:

- Socket connections, outgoing datagrams and DNS lookups are rejected.
- Every environment variable whose name contains `HPSILAB` is removed for each test.
- Real `time.sleep` calls are forbidden in the error-contract tests. Backoff is injected and mocked.
- An AST scan checks every production Python file for broker imports, forbidden operation names (`submit_order`, `place_order`, `execute_order`) and Mizan imports.

These are test safeguards. They do not isolate native code or child processes.

### Lint and formatting

```powershell
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
```

### Secret scanning

`tools/scan_secrets.py` runs gitleaks 8.x, which must already be installed and on `PATH`. It does not download anything. Exit codes: 0 clean, 1 findings, 2 blocked or tool error.

```powershell
.\.venv\Scripts\python.exe tools\scan_secrets.py            # working tree
.\.venv\Scripts\python.exe tools\scan_secrets.py --staged   # Git staged index
.\.venv\Scripts\python.exe tools\scan_secrets.py --self-test
```

`--self-test` checks that the scanner detects a synthetic canary. The canary is never committed, and scanner output and secret values are suppressed.

### Pre-commit hooks

The hooks are local system hooks. They do not download environments. They run the staged secret scan, the read-only boundary test, `ruff check` and `ruff format --check`.

```powershell
.\.venv\Scripts\python.exe -m pre_commit validate-config
.\.venv\Scripts\python.exe -m pre_commit install
```

### Live tools

`tools/probe.py` and `tools/ship_check.py` make live requests and spend Credits. A person runs them by hand. They are not part of the test suite. Their raw output goes to `.probe/`, and the credit ledger is `.credits/`. Both directories are git-ignored and must never be committed.

## Credits

- Rahmat Ullah: offline test infrastructure, error-contract and fixture specifications, read-only AST boundary checks, secret scanning and pre-commit setup.
- Mohammed Faisal Parvez: SDK integration, client, normalization, CLI.

HPSILab and the HPSILab name belong to their owner. This project is an independent integration.

## License

The adapter's own code is released under the MIT License. See [LICENSE](LICENSE). The license does not cover HPSILab's API, data, services or branding.
