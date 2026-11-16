"""Research boundary checks plus regression examples for the AST checker."""

from pathlib import Path

import pytest
import readonly_scan
from readonly_scan import production_sources, scan_file, scan_text

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def findings():
    sources = list(production_sources(ROOT))
    assert sources, "Safety coverage must not pass with an empty production-source inventory"
    return [(path.relative_to(ROOT), finding) for path in sources for finding in scan_file(path)]


@pytest.mark.parametrize(
    "rule",
    ["forbidden-broker-import", "forbidden-order-reference", "cross-project-isolation"],
)
def test_production_research_boundary(findings, rule: str) -> None:
    violations = [f"{path}: {finding}" for path, finding in findings if finding.rule == rule]
    assert not violations, "\n".join(violations)


@pytest.mark.parametrize(
    "source",
    [
        "import alpaca",
        "import alpaca_trade_api as broker",
        "from ib_insync import IB",
        "import ib_async",
        "from ibapi.client import EClient",
        "import kiteconnect",
        "import ccxt.async_support as exchange",
        "import MetaTrader5",
        "from importlib import import_module as load\nload('alpaca.trading')",
        "__import__('ibapi.client')",
        "from . import mizan",
        "from mizan.execution import engine",
        "import mizan.authorization as auth",
        "import mizan_core",
        "import importlib as loader\nloader.import_module('mizan.execution')",
        "def submit_order():\n    pass",
        "async def execute_order():\n    pass",
        "broker.place_order()",
        "callback = broker.submit_order",
        "callback = execute_order",
        "from somewhere import submit_order as callback",
        "getattr(broker, 'place_order')()",
        "setattr(broker, 'execute_order', handler)",
    ],
)
def test_checker_rejects_prohibited_executable_code(source: str) -> None:
    assert scan_text(source), "A prohibited executable construct escaped AST inspection"


@pytest.mark.parametrize(
    "source",
    [
        "# import alpaca\n# submit_order()",
        '"""Mizan and place_order are prohibited here."""',
        "FORBIDDEN = {'submit_order', 'place_order', 'execute_order', 'mizan', 'alpaca'}",
        "def pretrade_risk_scan():\n    return {}",
        "def analyze_stock(symbol):\n    return symbol",
        "message = 'No broker integration; mizan.execution is forbidden'",
    ],
)
def test_checker_allows_research_and_nonexecutable_inventories(source: str) -> None:
    assert not scan_text(source)


@pytest.mark.parametrize("source", ["def broken(", "import"])
def test_syntax_errors_fail_closed(source: str) -> None:
    with pytest.raises(SyntaxError):
        scan_text(source)


def test_recursive_source_inventory_excludes_only_declared_artifacts(tmp_path: Path) -> None:
    included = [
        "src/adapter/deep/client.py",
        "tools/check.py",
        "unexpected/deep/worker.py",
        "unexpected/UPPER.PY",
    ]
    excluded = [
        "tests/test_example.py",
        "docs/example.py",
        ".venv/Lib/client.py",
        ".venv-old/Lib/client.py",
        "node_modules/pkg/client.py",
        "vendor/client.py",
        "site-packages/client.py",
        "build/client.py",
        "dist/client.py",
        "generated/client.py",
        ".git/client.py",
        "__pycache__/client.py",
        "src/adapter/messages_pb2.py",
        ".test-tmp/client.py",
    ]
    for name in included + excluded:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("pass\n", encoding="utf-8")
    actual = {path.relative_to(tmp_path).as_posix() for path in production_sources(tmp_path)}
    assert actual == set(included)


def test_production_inventory_includes_package_and_tooling() -> None:
    actual = {path.relative_to(ROOT).as_posix() for path in production_sources(ROOT)}
    assert "src/hpsilab_research_adapter/cli.py" in actual
    assert "tools/scan_secrets.py" in actual


def test_unreadable_production_directory_fails_closed(tmp_path, monkeypatch) -> None:
    def denied_scandir(path):
        raise PermissionError("synthetic unreadable production directory")

    with monkeypatch.context() as scoped:
        scoped.setattr(readonly_scan.os, "scandir", denied_scandir)
        with pytest.raises(PermissionError):
            list(production_sources(tmp_path))
