"""The six approved read-only research tools. FROZEN CONTRACT (Phase 1).

Each entry maps a canonical tool name to the hpsilab-mcp 0.14.2 client method,
the fixture stem used in tests/fixtures/_manifest.json, and whether the SDK
method accepts include_metadata (only get_ai_prediction does in 0.14.2).
All six are HTTP GET in the SDK. No generate_* (POST) method is ever used.
"""

from __future__ import annotations

from dataclasses import dataclass

ANALYZE_STOCK = "analyze_stock"
AI_PREDICTION = "ai_prediction"
IV_RADAR = "iv_radar"
OPTION_PRESSURE = "option_pressure"
PRETRADE_RISK_SCAN = "pretrade_risk_scan"
MONTE_CARLO = "monte_carlo"


@dataclass(frozen=True)
class ToolSpec:
    name: str
    sdk_method: str
    fixture_stem: str
    supports_metadata: bool


TOOLS: dict[str, ToolSpec] = {
    spec.name: spec
    for spec in (
        ToolSpec(ANALYZE_STOCK, "analyze_stock", "analyze_stock", False),
        ToolSpec(AI_PREDICTION, "get_ai_prediction", "ai_prediction", True),
        ToolSpec(IV_RADAR, "get_iv_radar", "iv_radar", False),
        ToolSpec(OPTION_PRESSURE, "get_option_pressure", "option_pressure", False),
        ToolSpec(PRETRADE_RISK_SCAN, "get_pretrade_risk_scan", "pretrade_risk_scan", False),
        ToolSpec(MONTE_CARLO, "get_monte_carlo", "monte_carlo", False),
    )
}

TOOL_NAMES: tuple[str, ...] = tuple(TOOLS)
ALLOWED_SDK_METHODS: frozenset[str] = frozenset(spec.sdk_method for spec in TOOLS.values())

__all__ = [
    "AI_PREDICTION",
    "ALLOWED_SDK_METHODS",
    "ANALYZE_STOCK",
    "IV_RADAR",
    "MONTE_CARLO",
    "OPTION_PRESSURE",
    "PRETRADE_RISK_SCAN",
    "TOOLS",
    "TOOL_NAMES",
    "ToolSpec",
]
