"""Validate the fixture inventory without guessing a provider response shape."""

import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
METHODS = (
    "ai_prediction",
    "iv_radar",
    "option_pressure",
    "monte_carlo",
    "analyze_stock",
    "pretrade_risk_scan",
)


def manifest() -> dict:
    return json.loads((FIXTURES / "_manifest.json").read_text(encoding="utf-8"))


def test_manifest_tracks_all_eighteen_expected_response_fixtures() -> None:
    inventory = manifest()
    assert set(inventory["methods"]) == set(METHODS)
    expected = {
        f"{method}_{variant}.json"
        for method in METHODS
        for variant in ("full", "missing_field", "empty")
    }
    actual = {
        entry["file"]
        for method in inventory["methods"].values()
        for entry in method["variants"].values()
    }
    assert actual == expected
    assert inventory["full_response_compatibility_verified"] is False


@pytest.mark.parametrize("method", METHODS)
def test_empty_response_is_fabricated_empty_json(method: str) -> None:
    item = manifest()["methods"][method]
    assert item["schema_status"] == "pending"
    assert item["variants"]["empty"]["status"] == "synthetic_ready"
    path = FIXTURES / item["variants"]["empty"]["file"]
    assert json.loads(path.read_text(encoding="utf-8")) == {}


@pytest.mark.schema_pending
@pytest.mark.parametrize("method", METHODS)
def test_full_and_missing_response_compatibility_is_pending(method: str) -> None:
    item = manifest()["methods"][method]
    for variant in ("full", "missing_field"):
        entry = item["variants"][variant]
        assert entry["status"] == "schema_pending"
        assert not (FIXTURES / entry["file"]).exists(), "Update manifest and schema checks together"
    pytest.skip(
        f"BLOCKED: {method} full/missing fixtures require Faisal's documented response shape"
    )
