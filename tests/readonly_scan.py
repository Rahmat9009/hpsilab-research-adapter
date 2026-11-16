"""Small AST policy checker used only by the offline safety tests.

This detects syntactically visible imports, references and selected literal
reflection. It is not a sandbox, data-flow proof, or a complete runtime policy.
"""

import ast
import os
import tokenize
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

BROKER_MODULES = frozenset(
    {
        "alpaca",
        "alpaca_trade_api",
        "ib_insync",
        "ib_async",
        "ibapi",
        "ibkr",
        "kiteconnect",
        "zerodha",
        "ccxt",
        "metatrader5",
    }
)
ORDER_NAMES = frozenset({"submit_order", "place_order", "execute_order"})
EXCLUDED_DIRECTORIES = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "tests",
        "docs",
        "node_modules",
        "site-packages",
        "vendor",
        "third_party",
        "build",
        "dist",
        "generated",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        ".tox",
        ".nox",
        ".test-tmp",
        ".wheelhouse",
        ".reports",
        "__pypackages__",
    }
)


@dataclass(frozen=True)
class Finding:
    rule: str
    line: int

    def __str__(self) -> str:
        # Do not include source text; it might contain a credential.
        return f"{self.rule} at line {self.line}"


def excluded_directory(name: str) -> bool:
    name = name.casefold()
    return (
        name in EXCLUDED_DIRECTORIES
        or name == "venv"
        or name.startswith((".venv", "venv-", "venv."))
        or name.endswith(".egg-info")
    )


def production_sources(root: Path) -> Iterator[Path]:
    """Walk the whole repository, including Python outside src/, without links."""
    root = root.resolve()

    def fail_on_error(error: OSError) -> None:
        raise error

    for directory, directories, files in os.walk(root, followlinks=False, onerror=fail_on_error):
        for name in directories:
            path = Path(directory) / name
            if not excluded_directory(name) and path.is_symlink():
                raise ValueError("Production directory symlinks require explicit safety review")
        directories[:] = sorted(name for name in directories if not excluded_directory(name))
        for name in sorted(files):
            lower_name = name.casefold()
            if not lower_name.endswith(".py") or lower_name.endswith(("_pb2.py", "_pb2_grpc.py")):
                continue
            path = Path(directory) / name
            if path.is_symlink():
                raise ValueError("Production source symlinks require explicit safety review")
            yield path


def scan_text(source: str) -> set[Finding]:
    """Inspect executable AST nodes; ignore comments, docstrings and string inventories."""
    tree = ast.parse(source)
    findings: set[Finding] = set()
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for item in node.names:
                aliases[item.asname or item.name.split(".")[0]] = (
                    item.name if item.asname else item.name.split(".")[0]
                )
        elif isinstance(node, ast.ImportFrom):
            for item in node.names:
                aliases[item.asname or item.name] = ".".join(
                    part for part in (node.module, item.name) if part
                )

    def dotted(node: ast.AST) -> str:
        if isinstance(node, ast.Name):
            return aliases.get(node.id, node.id)
        if isinstance(node, ast.Attribute):
            parent = dotted(node.value)
            return f"{parent}.{node.attr}" if parent else node.attr
        return ""

    def check_module(module: str, node: ast.AST) -> None:
        root = module.split(".")[0].casefold()
        if root in BROKER_MODULES:
            findings.add(Finding("forbidden-broker-import", node.lineno))
        if root == "mizan" or root.startswith("mizan_"):
            findings.add(Finding("cross-project-isolation", node.lineno))

    def check_order(name: str, node: ast.AST) -> None:
        if name.casefold() in ORDER_NAMES:
            findings.add(Finding("forbidden-order-reference", node.lineno))

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for item in node.names:
                check_module(item.name, node)
        elif isinstance(node, ast.ImportFrom):
            check_module(node.module or "", node)
            for item in node.names:
                check_module(".".join(filter(None, (node.module, item.name))), node)
                check_order(item.name, node)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            check_order(node.name, node)
        elif isinstance(node, ast.Name):
            check_order(node.id, node)
            # Also catch aliases imported under a different name.
            check_order(dotted(node).split(".")[-1], node)
            check_module(dotted(node), node)
        elif isinstance(node, ast.Attribute):
            check_order(node.attr, node)
            check_module(dotted(node), node)
        elif isinstance(node, ast.Call):
            function = dotted(node.func)
            if function in {"__import__", "builtins.__import__", "importlib.import_module"}:
                if node.args and isinstance(node.args[0], ast.Constant):
                    module = node.args[0].value
                    if isinstance(module, str):
                        check_module(module.lstrip("."), node)
            if function in {"getattr", "setattr", "builtins.getattr", "builtins.setattr"}:
                if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
                    name = node.args[1].value
                    if isinstance(name, str):
                        check_order(name, node)
    return findings


def scan_file(path: Path) -> set[Finding]:
    # Honor PEP 263 encoding declarations; syntax/decoding errors fail closed.
    with tokenize.open(path) as source:
        return scan_text(source.read())
