# Changelog

This is an independent, unverified third-party integration. It is not an official
HPSILab product, and HPSILab has not verified or endorsed it.

## 0.2.0

- Credit ledger: every read, check, record and save now runs under a lock file next to
  the ledger (`<ledger>.lock`), so two processes sharing one ledger no longer overwrite
  each other's entries. A lock that cannot be taken within 10 seconds refuses the
  request before anything is sent.
- Credit ledger: a damaged or hand-edited ledger file (for example a negative or
  non-numeric cost) is treated as unreadable and refuses every request (fails closed).
- Credit ledger: a learned cost of 0 no longer lowers the reserved price of a tool when
  the catalog has no price for it; the reserve stays at the unknown-price reserve.
- New `hpsilab_research_adapter.thesis` module: judges the six normalized results
  against a thesis the user states (ticker, direction, horizon in days) with fixed,
  documented rules, labelling each value `supports`, `challenges`, `neutral` or
  `context`. Missing and unparseable evidence is listed, never guessed. Research only.
  See `docs/THESIS.md`.
- New `tools/thesis_demo.py`: a hand-run, single-ticker live pass with fixed credit
  limits (40 per run, 190 total, balance floor 1800). It refuses before any request is
  sent when the thesis, ledger or budget is unusable. New `--ledger PATH` option uses a
  given ledger file directly. The report JSON it writes now also records the credits
  used for the run.
- New `tools/thesis_summary.py`: prints a share-safe Markdown summary of a thesis
  report JSON. It contains field names, stance labels, rule text, counts and reasons,
  and no value observed in any HPSILab response.
- The command-line program is now named `hpsilab-research`.
- `LICENSE` is the standard MIT text.
- Wording across the repository: an independent, unverified third-party integration;
  not an official HPSILab product; not verified or endorsed by HPSILab.
- Test suite: 386 tests, all offline.

## 0.1.0

- Initial read-only adapter around the `hpsilab-mcp` 0.14.2 SDK for six research tools:
  `analyze_stock`, `ai_prediction`, `iv_radar`, `option_pressure`,
  `pretrade_risk_scan` and `monte_carlo`.
- Credits-only mode; refuses to run if `HPSILAB_X402_PRIVATE_KEY` is set.
- Command-line interface with per-run, total and balance-floor credit limits, JSON
  output and defined exit codes.
- Persistent credit ledger, retry policy (3 attempts for 429, 5xx and connection
  errors; 1 for timeouts) and a common normalized `Result` type.
- Offline test suite, read-only boundary scan, secret scanning and pre-commit
  configuration.
