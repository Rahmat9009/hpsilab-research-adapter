"""Offline defaults and the explicitly blocked SDK integration seam."""

import os
import socket
from collections.abc import Iterator

import pytest
from sdk_contract import SDKContract


@pytest.fixture(autouse=True)
def offline_only(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Reject Python socket traffic/DNS and remove ambient HPSILab credentials."""

    def forbidden_network(*args: object, **kwargs: object) -> None:
        pytest.fail("Network access is forbidden in this offline test suite")

    for name in ("create_connection", "getaddrinfo", "gethostbyname", "gethostbyname_ex"):
        monkeypatch.setattr(socket, name, forbidden_network)
    for name in ("connect", "connect_ex", "sendto", "sendmsg"):
        if hasattr(socket.socket, name):
            monkeypatch.setattr(socket.socket, name, forbidden_network)
    for name in tuple(os.environ):
        if "HPSILAB" in name.upper():
            monkeypatch.delenv(name, raising=False)
    yield


@pytest.fixture
def sdk_contract() -> SDKContract:
    """Replace this skip with a binding to Faisal's real, mockable implementation."""
    pytest.skip(
        "BLOCKED: Faisal's client, exception classes, SDK failure types, synthetic response "
        "schemas and agreed injection seam are unavailable; see tests/README.md."
    )
