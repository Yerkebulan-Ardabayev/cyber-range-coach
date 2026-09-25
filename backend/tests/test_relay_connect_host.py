from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from cyber_range_coach.errors import AppError
from cyber_range_coach.models import LinuxHost
from cyber_range_coach.routers import targets
from cyber_range_coach.schemas import NetworkInterface
from cyber_range_coach.services.network import source_address_toward

LAN = NetworkInterface(address="192.168.10.11", private=True, loopback=False)
WSL = NetworkInterface(address="172.24.64.1", private=True, loopback=False)


def _request(client: TestClient, advertised: str | None = None) -> SimpleNamespace:
    state = client.app.state
    settings = SimpleNamespace(relay_advertised_host=advertised)
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(settings=settings, db=state.db)))


def _add_wsl_host(client: TestClient) -> None:
    with client.app.state.db.session_factory() as session:
        session.add(
            LinuxHost(
                name="WSL Ubuntu",
                host="127.0.0.1",
                port=22,
                relay_source_ip="172.24.64.22",
                username="student",
                runner_username="range-runner",
                encrypted_private_key="test",
                public_key="test",
                encrypted_runner_private_key="test",
                runner_public_key="test",
            )
        )
        session.commit()


def test_relay_host_is_the_interface_routed_to_the_vm_not_the_first_private(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _add_wsl_host(client)
    asked: list[str] = []

    def route(peer: str) -> str:
        asked.append(peer)
        return "172.24.64.1"

    monkeypatch.setattr(targets, "local_interfaces", lambda: [LAN, WSL])
    monkeypatch.setattr(targets, "source_address_toward", route)
    assert targets._connect_host(_request(client)) == "172.24.64.1"
    assert asked == ["172.24.64.22"]


def test_public_or_missing_route_falls_back_to_private_interface(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _add_wsl_host(client)
    monkeypatch.setattr(targets, "local_interfaces", lambda: [LAN, WSL])
    monkeypatch.setattr(targets, "source_address_toward", lambda _peer: "8.8.4.4")
    assert targets._connect_host(_request(client)) == "192.168.10.11"
    monkeypatch.setattr(targets, "source_address_toward", lambda _peer: None)
    assert targets._connect_host(_request(client)) == "192.168.10.11"


def test_without_linux_vm_route_is_not_guessed(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def route(_peer: str) -> str:
        raise AssertionError("no VM configured, nothing to route to")

    monkeypatch.setattr(targets, "local_interfaces", lambda: [LAN])
    monkeypatch.setattr(targets, "source_address_toward", route)
    assert targets._connect_host(_request(client)) == "192.168.10.11"


def test_configured_host_wins(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _add_wsl_host(client)
    monkeypatch.setattr(targets, "source_address_toward", lambda _peer: "172.24.64.1")
    assert targets._connect_host(_request(client, "10.9.8.7")) == "10.9.8.7"


def test_no_private_interface_is_an_explicit_error(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(targets, "local_interfaces", lambda: [])
    with pytest.raises(AppError) as error:
        targets._connect_host(_request(client))
    assert error.value.code == "relay_host_unknown"


def test_source_address_toward_uses_os_routing() -> None:
    assert source_address_toward("127.0.0.1") == "127.0.0.1"
    assert source_address_toward("::1") is None
    assert source_address_toward("not-an-ip") is None
