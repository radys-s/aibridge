from aibridge.adapters.security import RegexSecretScanner


def test_secret_scanner_reports_codes_without_secret_values() -> None:
    secret = "sk-proj-abcdefghijklmnopqrstuv"
    result = RegexSecretScanner().scan(f"token={secret}")

    assert result.safe is False
    assert "openai_key" in result.finding_codes
    assert secret not in repr(result)
