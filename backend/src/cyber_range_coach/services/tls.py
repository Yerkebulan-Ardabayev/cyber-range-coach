from __future__ import annotations

import ipaddress
import os
import socket
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from ..config import Settings
from .network import local_interfaces
from .secrets import SecretProtector

CA_CERT = "cyber-range-coach-ca.crt"
CA_KEY = "cyber-range-coach-ca.key.enc"
SERVER_CERT = "cyber-range-coach.crt"
SERVER_KEY = "cyber-range-coach.key.enc"


def generate_certificates(
    settings: Settings,
    protector: SecretProtector,
    *,
    force: bool = False,
) -> dict[str, str]:
    settings.certificates_dir.mkdir(parents=True, exist_ok=True)
    paths = [
        settings.certificates_dir / CA_CERT,
        settings.certificates_dir / CA_KEY,
        settings.certificates_dir / SERVER_CERT,
        settings.certificates_dir / SERVER_KEY,
    ]
    existing = [path.exists() for path in paths]
    if all(existing) and not force:
        return {
            "ca_certificate": str(settings.certificates_dir / CA_CERT),
            "server_certificate": str(settings.certificates_dir / SERVER_CERT),
            "fingerprint": certificate_fingerprint(settings),
            "changed": "false",
        }
    if any(existing) and not force:
        raise FileExistsError(
            "Комплект сертификатов неполон. Проверьте его до явной перегенерации"
        )
    now = datetime.now(UTC)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Cyber Range Coach Local CA")])
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_encipherment=False,
                key_cert_sign=True,
                key_agreement=False,
                content_commitment=False,
                data_encipherment=False,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(ca_key, hashes.SHA256())
    )
    server_key, server_cert = _issue_server_certificate(ca_key, ca_name, now)
    ca_pem = ca_cert.public_bytes(serialization.Encoding.PEM)
    server_pem = server_cert.public_bytes(serialization.Encoding.PEM)
    ca_private = ca_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    server_private = server_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    (settings.certificates_dir / CA_CERT).write_bytes(ca_pem)
    (settings.certificates_dir / SERVER_CERT).write_bytes(server_pem)
    (settings.certificates_dir / CA_KEY).write_text(protector.protect(ca_private), encoding="utf-8")
    (settings.certificates_dir / SERVER_KEY).write_text(
        protector.protect(server_private), encoding="utf-8"
    )
    for path in (settings.certificates_dir / CA_KEY, settings.certificates_dir / SERVER_KEY):
        os.chmod(path, 0o600)
    return {
        "ca_certificate": str(settings.certificates_dir / CA_CERT),
        "server_certificate": str(settings.certificates_dir / SERVER_CERT),
        "fingerprint": certificate_fingerprint(settings),
        "changed": "true",
    }


def _issue_server_certificate(
    ca_key: rsa.RSAPrivateKey, ca_name: x509.Name, now: datetime
) -> tuple[rsa.RSAPrivateKey, x509.Certificate]:
    server_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    host_name = socket.gethostname()
    alt_names: list[x509.GeneralName] = [x509.DNSName("localhost"), x509.DNSName(host_name)]
    for interface in local_interfaces():
        try:
            alt_names.append(x509.IPAddress(ipaddress.ip_address(interface.address)))
        except ValueError:
            continue
    server_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, host_name)])
    server_cert = (
        x509.CertificateBuilder()
        .subject_name(server_name)
        .issuer_name(ca_name)
        .public_key(server_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=825))
        .add_extension(x509.SubjectAlternativeName(alt_names), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )
    return server_key, server_cert


def lan_addresses_missing_from_certificate(settings: Settings) -> set[str]:
    current = {
        interface.address
        for interface in local_interfaces()
        if interface.private and not interface.loopback and ":" not in interface.address
    }
    return current - certificate_ip_addresses(settings)


def reissue_server_certificate(settings: Settings, protector: SecretProtector) -> dict[str, str]:
    """New server certificate for the current addresses, signed by the existing CA.

    DHCP moves the laptop (spec 11.3 Zh). Keeping the CA means devices that
    already trust it (Mac, phone) need no action; only the server leaf changes.
    """
    ca_cert = x509.load_pem_x509_certificate((settings.certificates_dir / CA_CERT).read_bytes())
    ca_key = serialization.load_pem_private_key(
        protector.unprotect((settings.certificates_dir / CA_KEY).read_text(encoding="utf-8")),
        password=None,
    )
    if not isinstance(ca_key, rsa.RSAPrivateKey):
        raise ValueError("Ключ локального CA имеет неожиданный тип")
    server_key, server_cert = _issue_server_certificate(ca_key, ca_cert.subject, datetime.now(UTC))
    server_private = server_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    (settings.certificates_dir / SERVER_CERT).write_bytes(
        server_cert.public_bytes(serialization.Encoding.PEM)
    )
    server_key_path = settings.certificates_dir / SERVER_KEY
    server_key_path.write_text(protector.protect(server_private), encoding="utf-8")
    os.chmod(server_key_path, 0o600)
    return {"fingerprint": certificate_fingerprint(settings), "changed": "true"}


def ensure_certificate_covers_lan(settings: Settings, protector: SecretProtector) -> bool:
    """Reissue the server certificate when the LAN address is not in it. True if reissued."""
    if not settings.lan_mode or not (settings.certificates_dir / SERVER_CERT).exists():
        return False
    if not lan_addresses_missing_from_certificate(settings):
        return False
    reissue_server_certificate(settings, protector)
    return True


def certificate_fingerprint(settings: Settings) -> str:
    return certificate_file_fingerprint(settings.certificates_dir / SERVER_CERT, hashes.SHA256())


def certificate_file_fingerprint(path: Path, algorithm: hashes.HashAlgorithm) -> str:
    if not path.exists():
        return "DEV-NO-TLS"
    certificate = x509.load_pem_x509_certificate(path.read_bytes())
    digest = certificate.fingerprint(algorithm).hex().upper()
    return ":".join(digest[index : index + 2] for index in range(0, len(digest), 2))


def certificate_ip_addresses(settings: Settings) -> set[str]:
    path = settings.certificates_dir / SERVER_CERT
    if not path.exists():
        return set()
    certificate = x509.load_pem_x509_certificate(path.read_bytes())
    try:
        extension = certificate.extensions.get_extension_for_class(x509.SubjectAlternativeName)
    except x509.ExtensionNotFound:
        return set()
    return {str(address) for address in extension.value.get_values_for_type(x509.IPAddress)}


def materialize_server_key(settings: Settings, protector: SecretProtector) -> tuple[Path, Path]:
    encrypted_path = settings.certificates_dir / SERVER_KEY
    certificate_path = settings.certificates_dir / SERVER_CERT
    if not encrypted_path.exists() or not certificate_path.exists():
        raise FileNotFoundError("TLS-сертификат ещё не создан")
    key = protector.unprotect(encrypted_path.read_text(encoding="utf-8"))
    runtime_key = settings.runtime_dir / "server-key.pem"
    runtime_key.write_bytes(key)
    os.chmod(runtime_key, 0o600)
    return certificate_path, runtime_key


def remove_materialized_key(path: Path | None) -> None:
    if path and path.exists():
        data = path.read_bytes()
        path.write_bytes(b"\0" * len(data))
        path.unlink(missing_ok=True)
