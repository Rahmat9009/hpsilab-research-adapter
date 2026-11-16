"""Run gitleaks offline; never forward raw scanner output or secret values."""

import argparse
import json
import shutil
import subprocess
import tempfile
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def scan(source: Path, *, staged: bool = False) -> int:
    """Return 0 for clean, 1 for findings, or 2 for a blocked/failed scanner."""
    executable = shutil.which("gitleaks")
    if executable is None:
        print("BLOCKED: gitleaks is unavailable. Install an approved local gitleaks 8.x binary.")
        return 2
    with tempfile.TemporaryDirectory(prefix="hpsilab-scan-") as temporary:
        report = Path(temporary) / "redacted.json"
        mode = ["protect", "--staged"] if staged else ["detect", "--no-git"]
        command = [
            executable,
            *mode,
            "--source",
            str(source),
            "--config",
            str(ROOT / ".gitleaks.toml"),
            "--redact",
            "--no-banner",
            "--report-format",
            "json",
            "--report-path",
            str(report),
        ]
        # gitleaks is static and has no online verification mode enabled here.
        # Its stdout/stderr are deliberately discarded to avoid accidental disclosure.
        try:
            completed = subprocess.run(command, capture_output=True, check=False, timeout=120)
        except (OSError, subprocess.TimeoutExpired):
            print("BLOCKED: gitleaks could not complete. No scanner output was displayed.")
            return 2
        if completed.returncode not in (0, 1):
            print("BLOCKED: gitleaks failed. No scanner output was displayed.")
            return 2
        if completed.returncode == 1:
            try:
                findings = json.loads(report.read_text(encoding="utf-8"))
                if not isinstance(findings, list) or not findings:
                    raise ValueError("Expected a nonempty findings list")
            except (OSError, ValueError):
                print("BLOCKED: gitleaks returned an invalid findings report.")
                return 2
            print(f"Secret scan failed: {len(findings)} finding(s). Secret values are suppressed.")
            return 1
        print("Secret scan passed: no findings.")
        return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run a working-tree scan, staged-index scan, or synthetic detection probe."""
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--staged", action="store_true", help="scan Git's staged index")
    modes.add_argument(
        "--self-test", action="store_true", help="detect a nonfunctional test canary"
    )
    args = parser.parse_args(argv)
    if args.self_test:
        with tempfile.TemporaryDirectory(prefix="hpsilab-canary-") as temporary:
            source = Path(temporary)
            # Construct at runtime so no complete canary is committed or allowlisted.
            canary = "HPSILAB_" + "SYNTHETIC_SECRET_" + "OFFLINETEST00000000000000"
            (source / "synthetic.txt").write_text(canary + "\n", encoding="utf-8")
            result = scan(source)
        if result == 1:
            print("Scanner self-test passed: synthetic canary detected without exposing its value.")
            return 0
        if result == 0:
            print("Scanner self-test FAILED: the synthetic canary was missed.")
            return 1
        return result
    return scan(ROOT, staged=args.staged)


if __name__ == "__main__":
    raise SystemExit(main())
