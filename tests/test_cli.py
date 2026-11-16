"""Verify the only enabled CLI behavior is offline scaffold help/status."""

import pytest

from hpsilab_research_adapter.cli import main


def test_help_describes_research_scaffold(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as caught:
        main(["--help"])
    assert caught.value.code == 0
    output = capsys.readouterr().out
    assert "research-only" in output
    assert "offline" in output
    assert "response schemas" in output


def test_status_is_explicit_about_pending_implementation(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["--status"]) == 0
    assert "SDK client, research commands, and response schemas pending" in capsys.readouterr().out


@pytest.mark.parametrize("command", ["research", "analyze", "options", "credits"])
def test_unconfirmed_commands_are_unavailable(command: str) -> None:
    with pytest.raises(SystemExit) as caught:
        main([command])
    assert caught.value.code == 2
