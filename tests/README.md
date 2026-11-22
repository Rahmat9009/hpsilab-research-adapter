# Offline test infrastructure

Python 3.12+, pytest, ruff and pre-commit are configured in `pyproject.toml`.
Install from the commands in the root README. The test suite runs offline.

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

## Error contracts

`test_errors.py` runs against the real `ResearchClient`, bound in the
`sdk_contract` fixture in `conftest.py`. The binding constructs the real client
and raises real `hpsilab_mcp` exceptions beneath the production retry loop. The
request mock and the sleep mock are injected at those seams.

The file covers the six requested error scenarios plus upstream authentication
rejection, four 5xx statuses, unexpected-error propagation, backoff ordering and
exception-chain credential redaction. Rate limits and repeated 5xx failures
require exactly three attempts and two backoff calls. Credit exhaustion and
authentication rejection require one attempt, no backoff. A missing key requires
zero requests and no backoff.

Timeouts make 1 attempt. This is the owner's decision: a timed-out request may
already have been billed, so it is not repeated. The binding sets
`timeout_attempts=1` to match `policy.TIMEOUT_ATTEMPTS`.

The `sdk_contract` binding must stay thin. Its callbacks may adapt the existing
client and SDK. They must not add retry logic, error translation or a fake
client to make a test pass. `tests/sdk_contract.py` documents the seam itself.
It is a test-only specification, not a public SDK API.

## Fixtures: six empty responses ready, twelve shapes pending

`fixtures/` holds six synthetic response files, one per research method. Each
contains exactly `{}`. `fixtures/_manifest.json` lists all 18 planned paths
(empty, full and missing-field variants for each method) and marks the twelve
full and missing-field files as `schema_pending`. It is inventory metadata, not
an HPSILab response.

`schemas/` holds one `*.shape.json` file per method. These record keys and types
only, never values, and were built from probed response shapes. They are not
used as full-response fixtures.

Each full-response compatibility case is explicitly skipped until the documented
response structure for that method is available. When it is, create the full
response with the same structure and replace EVERY value with fabricated content.
Derive each missing-field response from its full counterpart by deleting exactly
one documented field. Record the omitted field and the schema version, add shape
validation, and update the manifest and the pending tests together. Do not paste
real responses, market values, credentials, account identifiers or personal data
into this repo. No full-response compatibility is currently verified.

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
scanner is a blocked result, never a pass. The self-test prints one line for the
canary finding it expects; that line is not a failure.

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
