from __future__ import annotations

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes

from cyber_range_coach.schemas import NetworkInterface
from cyber_range_coach.services import tls
from cyber_range_coach.services.commands import CommandResult
from cyber_range_coach.services.docker import DockerDiscovery
from cyber_range_coach.services.tls import (
    CA_CERT,
    SERVER_CERT,
    certificate_file_fingerprint,
    certificate_ip_addresses,
    ensure_certificate_covers_lan,
    generate_certificates,
)


def _lan(address: str) -> list[NetworkInterface]:
    return [
        NetworkInterface(address="127.0.0.1", private=True, loopback=True),
        NetworkInterface(address=address, private=True, loopback=False),
    ]


def test_new_dhcp_address_reissues_site_certificate_with_same_ca(client, monkeypatch) -> None:
    settings = client.app.state.settings
    settings.lan_mode = True
    protector = client.app.state.protector
    monkeypatch.setattr(tls, "local_interfaces", lambda: _lan("192.168.10.10"))
    generate_certificates(settings, protector)
    ca_before = certificate_file_fingerprint(settings.certificates_dir / CA_CERT, hashes.SHA256())
    assert "192.168.10.10" in certificate_ip_addresses(settings)

    assert ensure_certificate_covers_lan(settings, protector) is False

    monkeypatch.setattr(tls, "local_interfaces", lambda: _lan("192.168.10.11"))
    assert ensure_certificate_covers_lan(settings, protector) is True
    assert "192.168.10.11" in certificate_ip_addresses(settings)
    ca_after = certificate_file_fingerprint(settings.certificates_dir / CA_CERT, hashes.SHA256())
    assert ca_after == ca_before, "devices already trust this CA; it must not change"
    ca = x509.load_pem_x509_certificate((settings.certificates_dir / CA_CERT).read_bytes())
    site = x509.load_pem_x509_certificate((settings.certificates_dir / SERVER_CERT).read_bytes())
    site.verify_directly_issued_by(ca)
    assert ensure_certificate_covers_lan(settings, protector) is False


def test_without_lan_mode_nothing_is_reissued(client, monkeypatch) -> None:
    settings = client.app.state.settings
    settings.lan_mode = False
    monkeypatch.setattr(tls, "local_interfaces", lambda: _lan("192.168.10.10"))
    generate_certificates(settings, client.app.state.protector)
    monkeypatch.setattr(tls, "local_interfaces", lambda: _lan("192.168.10.11"))
    assert ensure_certificate_covers_lan(settings, client.app.state.protector) is False


class _Runner:
    def __init__(self, result: CommandResult) -> None:
        self.result = result

    async def run(self, *_args, **_kwargs) -> CommandResult:
        return self.result


@pytest.mark.asyncio
async def test_docker_check_shows_the_real_reason() -> None:
    timed_out = DockerDiscovery(_Runner(CommandResult(("docker",), 124, "", "command timed out")))
    ok, detail = await timed_out.available()
    assert ok is False and "не ответил за отведённое время" in detail
    refused = DockerDiscovery(
        _Runner(CommandResult(("docker",), 1, "", "error during connect: open //./pipe/dockerDesktopLinuxEngine\nmore"))
    )
    ok, detail = await refused.available()
    assert ok is False and "dockerDesktopLinuxEngine" in detail and "more" not in detail
