# Offline test infrastructure

Python 3.12+, pytest, ruff and pre-commit are configured in `pyproject.toml`.
Install from a trusted local wheelhouse using the commands in the root README.
All setup and checks for this scaffold were performed without network access.

## Rerun verification

From the repository root in PowerShell:

```powershell
$adapterPython = '.\.venv\Scripts\python.exe'
& $adapterPython -m pytest tests/test_readonly.py --basetemp=.test-tmp -v
& $adapterPython -m pytest tests/test_errors.py --basetemp=.test-tmp -v
& $adapterPython -m pytest --basetemp=.test-tmp -v
& $adapterPython -m ruff check .
& $adapterPython -m ruff format --check .
& $adapterPython -m pip check
& $adapterPython tools/scan_secrets.py
& $adapterPython tools/scan_secrets.py --self-test
& $adapterPython -m pre_commit validate-config
```

The autouse fixture in `conftest.py` rejects Python socket connections, outgoing
datagrams and common DNS lookups, and removes ambient HPSILab environment values.
The error module rejects real `time.sleep` calls. Retry sleep must be mocked.
These are test safeguards; they do not isolate arbitrary native code or child
processes. The gitleaks child process performs only static local scans.

## Error contracts: blocked on Faisal

`test_errors.py` contains the six requested error scenarios plus upstream
authentication rejection, four 5xx statuses, unexpected-error propagation,
backoff ordering and exception-chain credential redaction. Rate limits and
repeated 5xx failures require exactly three attempts and two backoff calls.
Credit exhaustion and authentication rejection require one attempt, no backoff;
a missing key requires zero requests and no backoff.

All SDK-dependent cases currently skip with an explicit BLOCKED reason. There
is no fake production client or test implementation of retries or normalization.

Before enabling them, agree the TEST-ONLY `SDKContract` handoff in
`tests/sdk_contract.py`. It is not an approved public SDK API. Replace only the
blocked fixture in `tests/conftest.py` with callbacks that bind the REAL client:

1. Identify the existing public client and approved research invocation.
2. Map the actual exception classes: `RateLimited`, `CreditsExhausted`,
   `Timeout`, `UpstreamError`, `AuthError`.
3. Inject the request mock beneath the production retry loop and inject the
   actual backoff/sleep seam. Disable caches. Never wrap the mock in new retry
   or error translation code just to satisfy these tests.
4. Create actual SDK failure instances for rate limit, credits, timeout,
   authentication, and HTTP 500/502/503/504, using fabricated messages/metadata.
5. Provide a success response and expected normalized result from documented
   response shapes, with every value fabricated.
6. Agree whether timeouts are immediate or retryable. The requirements specify
   `Timeout` and a three-attempt upper bound but do not specify an exact timeout
   retry policy. Set the agreed expected attempt count (1, 2 or 3) in the binding.
7. Ensure `api_key=None` explicitly exercises missing authentication without
   reading external credentials. Construct the real client inside the callable
   returned by the test binding so constructor errors can be asserted.

No production client constructor, import path, SDK error shape, environmental
key name, response schema, or final command set has been invented.

## Fixtures: six empty responses ready, twelve shapes pending

`fixtures/_manifest.json` tracks all 18 planned paths and marks the twelve
absent full/missing-field files as `schema_pending`. It is inventory metadata,
not an HPSILab response. The six existing response fixtures contain exactly
`{}`. Each response-shape compatibility case is explicitly skipped.

When Faisal provides structures, create full responses preserving that structure
and replacing EVERY value with fabricated content. Derive each missing-field
response from its full counterpart by deleting exactly one documented field.
Record the omitted field and schema version, add actual shape validation, and
update the manifest and pending tests together. Do not paste real responses,
market values, credentials, account identifiers or personal data into this repo.
No full-response compatibility is currently verified.

`pretrade_risk_scan` is a research method name; it grants no trading authority.

## Static research boundary and its limits

`readonly_scan.py` recursively enumerates repository Python files, including
tooling and Python outside `src/`. `test_readonly.py` rejects broker imports,
forbidden operation references/definitions, and Mizan imports/references.
It handles import aliases, selected literal dynamic imports and literal
`getattr`/`setattr` operation names. Policy inventories in strings, comments,
and docstrings are allowed. Syntax/encoding errors fail closed. Source-directory
and source-file symlinks require explicit review.

Exclusions are explicit in `EXCLUDED_DIRECTORIES`: tests/docs, virtual
environments, dependency folders, Git metadata, caches, build/generated folders
and known protobuf-generated Python filenames. Source enumeration regression
tests check both exclusions and unexpected nested production directories.

These checks do not prove the absence of every runtime trading pathway.
Computed import strings, arbitrary reflection, runtime code generation, native
extensions, subprocesses, non-Python code and unreviewed generated/dependency
code require separate review. They also cannot prove how another project uses
exported research data. Maintain the strict separation from Mizan in design,
code review and use.

## Secret scanning and pre-commit

Install an approved local gitleaks 8.x binary on PATH; do not download it while
offline. The Python development extra supplies pre-commit, not the external
gitleaks executable.

`.gitleaks.toml` extends gitleaks' default credential rules. It excludes only
local dependency/cache/build artifacts. Production code, tests, fixtures and
documentation are scanned. There is no baseline or blanket source/fixture
allowlist. A synthetic-only canary rule verifies the local detection path.
The canary is constructed only in a temporary file, is nonfunctional, and is
never committed. Raw scanner output and secret values are always suppressed.

`tools/scan_secrets.py` scans the working tree by default. `--staged` scans
the actual Git staged index; this catches staged values even if working files
were subsequently changed. Exit codes: 0 clean, 1 findings, 2 blocked/tool error.
`--self-test` returns 0 only when the synthetic canary is detected; a missing
scanner is a blocked result, never a pass.

After the tool is available, activate the project environment in this shell
and run/install the local hooks:

```powershell
$env:PATH = (Resolve-Path '.\.venv\Scripts').Path + ';' + $env:PATH
python -m pre_commit run --all-files
python -m pre_commit install
```

All hooks use `repo: local` and `language: system`, so pre-commit does not
download environments. Hooks run staged secret scanning, AST boundary tests
and ruff. Before an initial commit, stage the intended files so the staged scan
has content. Install the hook for subsequent commits even when gitleaks is
unavailable: it will fail closed until the binary is supplied. See the recorded
verification status before relying on this scaffold's scanner configuration.
