from cyber_range_coach.services.ai import Redactor


def test_redactor_removes_credentials_and_anonymizes_lab_addresses() -> None:
    raw = (
        "Authorization: Bearer top-secret-token\n"
        "Cookie: session=abc123\n"
        "target=http://192.168.10.10:3000/path user=test@example.com "
        "api_key=" + "s" + "k-live-secretvalue"
    )
    result = Redactor().redact(raw)
    assert "top-secret-token" not in result.text
    assert "session=abc123" not in result.text
    assert "192.168.10.10" not in result.text
    assert "test@example.com" not in result.text
    assert ("s" + "k-live-secretvalue") not in result.text
    assert result.count >= 5
    assert result.safe is True


def test_redactor_removes_project_keys_jwt_and_quoted_passwords() -> None:
    project_key = "s" + "k-proj-0123456789abcdefgh"
    vendor_key = "s" + "k-ant-api03-0123456789abcdefgh"
    jwt = "ey" + "JhbGciOiJIUzI1NiJ9." + "ey" + "JzdWIiOiJ0ZXN0dXNlciJ9.abcdefghijklmnop"
    quoted = 'password="two words remain secret"'
    result = Redactor().redact("\n".join((project_key, vendor_key, jwt, quoted)))
    for secret in (project_key, vendor_key, jwt, "two words remain secret"):
        assert secret not in result.text
    assert result.safe is True
