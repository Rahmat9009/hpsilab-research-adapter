"""Verify clean/finding behavior with nonfunctional synthetic data only."""

import importlib.util
import shutil
import tempfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "scan_secrets.py"
SPEC = importlib.util.spec_from_file_location("offline_secret_scan", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
scanner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(scanner)


def test_missing_gitleaks_fails_closed(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr(scanner.shutil, "which", lambda name: None)
    assert scanner.scan(SCRIPT.parent) == 2
    assert "BLOCKED" in capsys.readouterr().out


@pytest.mark.secret_scanner
def test_gitleaks_detects_synthetic_canary_and_accepts_clean_directory(capsys) -> None:
    if shutil.which("gitleaks") is None:
        pytest.skip("BLOCKED: gitleaks binary is not installed; no scanner pass is claimed")
    with tempfile.TemporaryDirectory(prefix="hpsilab-clean-probe-") as temporary:
        source = Path(temporary)
        assert scanner.scan(source) == 0
        canary = "HPSILAB_" + "SYNTHETIC_SECRET_" + "OFFLINETEST00000000000000"
        (source / "synthetic.txt").write_text(canary + "\n", encoding="utf-8")
        assert scanner.scan(source) == 1
        assert canary not in capsys.readouterr().out
    assert scanner.main(["--self-test"]) == 0
