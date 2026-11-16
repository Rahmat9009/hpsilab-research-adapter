# HPSILab Research Adapter

Standalone Python 3.12+ command-line research adapter scaffold.

HPSILab outputs must never generate, approve, authorize, route or execute trades,
directly or indirectly. This repository has no broker or Mizan integration and
must remain separate from Mizan's risk checks, proposals and authorization.

## Current scope

The installed `hpsilab` command supports `--help`, `--version` and `--status`.
Running it without arguments displays help. It uses argparse and the standard
library; it reads no API credentials and makes no SDK or network calls.

Research, analyze, options and credits commands remain unimplemented until
Faisal confirms the actual approved SDK interface. Proposed command examples
are not treated as provider capabilities. No web interface or server is included.

## Offline setup and verification

Use an existing Python 3.12+ interpreter. Supply dependencies in a trusted local
wheel directory; do not enable package indexes while offline.

```powershell
cd C:\Projects\ALPACA\hpsilab-research-adapter
& 'C:\Users\ru765\AppData\Local\Programs\Python\Python312\python.exe' -m venv .venv
$adapterPython = '.\.venv\Scripts\python.exe'
& $adapterPython -m pip install --no-index --find-links .wheelhouse setuptools wheel 'pytest>=8.3,<9' 'ruff>=0.15,<1' 'pre-commit>=4,<5'
& $adapterPython -m pip install --no-index --no-build-isolation -e '.[dev]'
& $adapterPython -m hpsilab_research_adapter --help
& $adapterPython -m hpsilab_research_adapter --status
& $adapterPython -m pytest --basetemp=.test-tmp -v
```

The local `.wheelhouse/` and `.venv/` are ignored and are not distributed.
No HPSILab key is required. See [tests/README.md](tests/README.md) for the SDK
handoff, exact verification commands, and blocked work. See
[VERIFICATION.md](VERIFICATION.md) for the actual results of this scaffold.

## Ownership and boundaries

Faisal owns the production SDK authentication, six approved research wrappers,
response normalization, errors/retries, caching/credit protection, and final CLI.
This scaffold supplies fixture infrastructure, offline error contracts, static
research-boundary checks, and pre-commit gitleaks configuration.

Six fabricated empty response fixtures are present. Twelve full/missing-field
fixtures and all response-shape compatibility checks await Faisal's schemas.
Error tests are explicitly skipped until the real implementation and an agreed
test binding are supplied; they are not evidence that retries already work.

Install a trusted local gitleaks 8.x binary before enabling commits through the
configured hooks. No secret-scanner success is claimed when the tool is missing.

No remote is configured. Do not publish or push without explicit authorization.
