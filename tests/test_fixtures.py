"""Validate synthetic response fixtures against the probed hpsilab-mcp shapes.

Every fixture value is fabricated. The shape files record keys and JSON types only.
"""

import copy
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).parent
FIXTURES = ROOT / "fixtures"
SCHEMAS = ROOT.parent / "schemas"
METHODS = (
    "ai_prediction",
    "iv_radar",
    "option_pressure",
    "monte_carlo",
    "analyze_stock",
    "pretrade_risk_scan",
)
REAL_LOOKING_TICKERS = frozenset({"NVDA", "AAPL", "SPY"})


def manifest() -> dict:
    return json.loads((FIXTURES / "_manifest.json").read_text(encoding="utf-8"))


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _shape(method: str) -> dict:
    return _load(SCHEMAS / f"{method}.shape.json")


def _entry(method: str, variant: str) -> dict:
    return manifest()["methods"][method]["variants"][variant]


def _is_scalar(value: Any, type_name: str) -> bool:
    if type_name == "string":
        return isinstance(value, str)
    if type_name == "boolean":
        return isinstance(value, bool)
    if type_name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if type_name == "number":
        return isinstance(value, int | float) and not isinstance(value, bool)
    if type_name == "null":
        return value is None
    raise ValueError(f"unknown scalar type: {type_name!r}")


def conforms(value: Any, node: Any) -> bool:
    """Return True when value matches one node of a probed shape file."""
    if isinstance(node, str):
        return _is_scalar(value, node)
    if "anyOf" in node:
        return any(conforms(value, branch) for branch in node["anyOf"])
    kind = node["type"]
    if kind == "object":
        if not isinstance(value, dict):
            return False
        keys = node["keys"]
        required = set(keys) - set(node.get("optional_keys", ()))
        if not required <= set(value) or not set(value) <= set(keys):
            return False
        return all(conforms(value[name], child) for name, child in keys.items() if name in value)
    if kind == "array":
        if not isinstance(value, list):
            return False
        items = node.get("items")
        # items null means the probe only observed an empty array, so any list is accepted.
        return items is None or all(conforms(item, items) for item in value)
    if kind == "map":
        if not isinstance(value, dict):
            return False
        return all(conforms(item, node["values"]) for item in value.values())
    raise ValueError(f"unknown node type: {kind!r}")


def _without_omitted_field(full: Any, entry: dict) -> Any:
    expected = copy.deepcopy(full)
    record = expected[0] if entry.get("omitted_location") == "data[0]" else expected
    assert entry["omitted_field"] in record
    del record[entry["omitted_field"]]
    return expected


def _string_values(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _string_values(item)
    elif isinstance(value, list):
        for item in value:
            yield from _string_values(item)


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
    assert inventory["full_response_compatibility_verified"] is True


@pytest.mark.parametrize("method", METHODS)
def test_empty_response_is_fabricated_empty_json(method: str) -> None:
    item = manifest()["methods"][method]
    assert item["schema_status"] == "probed"
    assert item["variants"]["empty"]["status"] == "synthetic_ready"
    path = FIXTURES / item["variants"]["empty"]["file"]
    assert json.loads(path.read_text(encoding="utf-8")) == {}


@pytest.mark.parametrize("method", METHODS)
def test_full_response_conforms_to_probed_shape(method: str) -> None:
    entry = _entry(method, "full")
    assert entry["status"] == "synthetic_ready"
    full = _load(FIXTURES / entry["file"])
    assert conforms(full, _shape(method)["data"])


@pytest.mark.parametrize("method", METHODS)
def test_missing_response_is_full_minus_exactly_the_recorded_field(method: str) -> None:
    full = _load(FIXTURES / _entry(method, "full")["file"])
    entry = _entry(method, "missing_field")
    assert entry["status"] == "synthetic_ready"
    missing = _load(FIXTURES / entry["file"])
    assert missing == _without_omitted_field(full, entry)


@pytest.mark.parametrize("method", METHODS)
def test_recorded_omitted_field_is_a_non_optional_key_of_the_shape(method: str) -> None:
    entry = _entry(method, "missing_field")
    data = _shape(method)["data"]
    if data["type"] == "array":
        assert entry.get("omitted_location") == "data[0]"
        node = data["items"]
    else:
        assert "omitted_location" not in entry
        node = data
    assert entry["omitted_field"] in node["keys"]
    assert entry["omitted_field"] not in node.get("optional_keys", [])


@pytest.mark.parametrize("method", METHODS)
def test_missing_response_no_longer_conforms_to_probed_shape(method: str) -> None:
    missing = _load(FIXTURES / _entry(method, "missing_field")["file"])
    assert not conforms(missing, _shape(method)["data"])


@pytest.mark.parametrize("path", sorted(FIXTURES.glob("*.json")), ids=lambda p: p.name)
def test_no_fixture_value_is_a_real_looking_ticker(path: Path) -> None:
    leaks = REAL_LOOKING_TICKERS & set(_string_values(_load(path)))
    assert not leaks, f"{path.name} contains real-looking ticker values"
