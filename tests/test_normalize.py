"""Tests for the response normalizer. All values are fabricated."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from hpsilab_research_adapter.normalize import EXPECTED_FIELDS, normalize
from hpsilab_research_adapter.tools import TOOL_NAMES

SCHEMAS = Path(__file__).resolve().parent.parent / "schemas"

_TYPE_VALUES: dict[str, Any] = {
    "string": "fake",
    "integer": 1,
    "number": 0.5,
    "boolean": True,
    "null": None,
    "array": [],
    "object": {},
}


def _shape_data(tool: str) -> dict[str, Any]:
    return json.loads((SCHEMAS / f"{tool}.shape.json").read_text(encoding="utf-8"))["data"]


def _top_keys(tool: str) -> dict[str, Any]:
    data = _shape_data(tool)
    node = data["items"] if data["type"] == "array" else data
    return node["keys"]


def _fake_value(spec: Any) -> Any:
    kind = spec if isinstance(spec, str) else spec["type"]
    return _TYPE_VALUES[kind]


def full_response(tool: str) -> dict[str, Any]:
    return {key: _fake_value(spec) for key, spec in _top_keys(tool).items()}


HORIZON_TOOLS = {"monte_carlo": "horizon_days"}


class FakeMcpResult:
    def __init__(self, data: Any, metadata: Any) -> None:
        self.data = data
        self.metadata = metadata


def test_expected_fields_cover_exactly_the_tools() -> None:
    assert set(EXPECTED_FIELDS) == set(TOOL_NAMES)


@pytest.mark.parametrize("tool", TOOL_NAMES)
def test_expected_fields_match_schema(tool: str) -> None:
    data = _shape_data(tool)
    node = data["items"] if data["type"] == "array" else data
    optional = set(node.get("optional_keys", []))
    assert EXPECTED_FIELDS[tool] == frozenset(set(node["keys"]) - optional)


@pytest.mark.parametrize("tool", TOOL_NAMES)
def test_full_response(tool: str) -> None:
    raw = full_response(tool)
    if tool == "monte_carlo":
        raw["horizon_days"] = 30
    result = normalize(tool, "test", raw)
    assert result.tool == tool
    assert result.ticker == "TEST"
    assert result.error is None
    assert result.data == raw
    assert result.source_fields == tuple(sorted(raw))
    assert result.missing_fields == ()
    assert result.horizon == ("30" if tool == "monte_carlo" else None)


@pytest.mark.parametrize("tool", TOOL_NAMES)
def test_missing_one_field(tool: str) -> None:
    raw = full_response(tool)
    dropped = sorted(raw)[0]
    del raw[dropped]
    result = normalize(tool, "TEST", raw)
    assert result.missing_fields == (dropped,)
    assert dropped not in result.source_fields
    assert result.data == raw


def test_missing_horizon_key_gives_none() -> None:
    raw = full_response("monte_carlo")
    del raw["horizon_days"]
    assert normalize("monte_carlo", "TEST", raw).horizon is None
    raw["horizon_days"] = None
    assert normalize("monte_carlo", "TEST", raw).horizon is None


@pytest.mark.parametrize("tool", TOOL_NAMES)
@pytest.mark.parametrize("empty", [{}, None])
def test_empty_response(tool: str, empty: Any) -> None:
    result = normalize(tool, "TEST", empty)
    assert result.data == {}
    assert result.source_fields == ()
    assert result.missing_fields == tuple(sorted(EXPECTED_FIELDS[tool]))
    assert result.horizon is None
    assert result.error is None


def test_mcp_result_dict_data_with_metadata() -> None:
    raw = FakeMcpResult({"symbol": "TEST", "status": "fake"}, {"result_id": "fake-1"})
    result = normalize("option_pressure", "TEST", raw)
    assert result.data == {"symbol": "TEST", "status": "fake", "_metadata": {"result_id": "fake-1"}}
    assert result.source_fields == ("status", "symbol")
    assert "_metadata" not in result.source_fields
    assert "_metadata" not in result.missing_fields


def test_mcp_result_metadata_object_converted_to_dict() -> None:
    class Meta:
        def __init__(self) -> None:
            self.result_id = "fake-2"

    result = normalize("ai_prediction", "TEST", FakeMcpResult({"basis": "fake"}, Meta()))
    assert result.data["_metadata"] == {"result_id": "fake-2"}


def test_mcp_result_without_metadata_has_no_metadata_key() -> None:
    result = normalize("ai_prediction", "TEST", FakeMcpResult({"basis": "fake"}, None))
    assert "_metadata" not in result.data


def test_mcp_result_list_data_ai_prediction() -> None:
    items = [full_response("ai_prediction")]
    result = normalize("ai_prediction", "TEST", FakeMcpResult(items, {"result_id": "fake-3"}))
    assert result.data["items"] is items
    assert result.source_fields == tuple(sorted(items[0]))
    assert result.missing_fields == ()
    assert result.horizon is None


def test_mcp_result_empty_list_and_none_data() -> None:
    for payload in ([], None):
        result = normalize("ai_prediction", "TEST", FakeMcpResult(payload, None))
        assert result.data == {}
        assert result.source_fields == ()


@pytest.mark.parametrize("bad", [[], [1], "fake", 5, ("a",)])
def test_bad_raw_type_raises(bad: Any) -> None:
    with pytest.raises(ValueError):
        normalize("analyze_stock", "TEST", bad)


def test_mcp_result_list_with_non_object_items_raises() -> None:
    with pytest.raises(ValueError):
        normalize("ai_prediction", "TEST", FakeMcpResult([1, 2], None))


def test_unknown_tool_raises() -> None:
    with pytest.raises(ValueError):
        normalize("not_a_tool", "TEST", {})


def test_ticker_stripped_and_uppercased() -> None:
    assert normalize("iv_radar", "  tEsT ", {}).ticker == "TEST"


def test_values_untouched() -> None:
    nested = {"a": [1, 2, 3]}
    raw = {"status": "fake", "count": 1, "results": nested, "extra_fake": 0.123456789}
    result = normalize("iv_radar", "TEST", raw)
    assert result.data["results"] is nested
    assert result.data["extra_fake"] == 0.123456789
    assert result.data == raw
    assert result.source_fields == ("count", "extra_fake", "results", "status")
    assert result.missing_fields == ()


def test_input_not_mutated() -> None:
    raw = {"status": "fake"}
    normalize("iv_radar", "TEST", FakeMcpResult(raw, {"k": 1}))
    assert raw == {"status": "fake"}
