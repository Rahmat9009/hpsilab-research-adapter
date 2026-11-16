# Synthetic fixture inventory

Every response value in this directory is fabricated. No provider calls were made.

| Research method | Empty | Full | Missing one field |
| --- | --- | --- | --- |
| ai_prediction | ready: {} | schema pending | schema pending |
| iv_radar | ready: {} | schema pending | schema pending |
| option_pressure | ready: {} | schema pending | schema pending |
| monte_carlo | ready: {} | schema pending | schema pending |
| analyze_stock | ready: {} | schema pending | schema pending |
| pretrade_risk_scan | ready: {} | schema pending | schema pending |

Six response files exist; twelve are intentionally absent until Faisal supplies
actual response structures. `_manifest.json` records all 18 expected paths,
their status, and the absence of verified full-response compatibility. It is
test inventory metadata, not an API response or guessed provider schema.

For each method, the eventual full response must preserve the documented API
structure with all content replaced by fabricated data. The missing-field
variant must differ by exactly one omitted documented field. Record that field
and the schema version when the real structures are available. Add schema
validation before marking compatibility verified.

The research method named `pretrade_risk_scan` never authorizes trading.
