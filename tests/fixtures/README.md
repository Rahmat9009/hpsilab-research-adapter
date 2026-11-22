# Synthetic fixture inventory

Every response value in this directory is fabricated. The shapes they follow come from a live probe (`schemas/`), but no provider value was copied into a fixture.
Shapes come from a live probe of hpsilab-mcp 0.14.2 (keys and JSON types only);
no provider values were copied.

| Research method | Empty | Full | Missing one field (omitted) |
| --- | --- | --- | --- |
| ai_prediction | `{}` | synthetic, shape-checked | synthetic; omits `model_name` from `data[0]` |
| iv_radar | `{}` | synthetic, shape-checked | synthetic; omits `count` |
| option_pressure | `{}` | synthetic, shape-checked | synthetic; omits `max_pain` |
| monte_carlo | `{}` | synthetic, shape-checked | synthetic; omits `volatility` |
| analyze_stock | `{}` | synthetic, shape-checked | synthetic; omits `summary` |
| pretrade_risk_scan | `{}` | synthetic, shape-checked | synthetic; omits `regime` |

`_manifest.json` records all 18 paths, each shape source, and the omitted field
for every missing-field variant. Its `full_response_compatibility_verified` flag
is set only when `tests/test_fixtures.py` passes.

`tests/test_fixtures.py` checks that each full fixture conforms to its probed
shape, and that each missing-field fixture equals its full fixture minus exactly
the recorded field. It also checks that the recorded field is a non-optional key
of the shape, and that no fixture value is a real-looking ticker (`NVDA`, `AAPL`,
`SPY`).

`ai_prediction` is a top-level array, so its missing-field variant omits the key
from the first record (`data[0]`) rather than from the top level.

The research method named `pretrade_risk_scan` never authorizes trading.
