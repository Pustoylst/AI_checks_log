"""Check local configuration before connecting to GigaChat."""

from app.config import get_settings


def main() -> int:
    """Report whether the required local settings are present."""

    settings = get_settings()
    print(f"scope={settings.gigachat_scope}")
    print(f"model={settings.gigachat_model}")
    print(f"fallback_model={settings.gigachat_fallback_model}")
    print(f"verify_ssl_certs={settings.gigachat_verify_ssl_certs}")

    if not settings.has_gigachat_credentials:
        print("credentials=missing")
        print("Set GIGACHAT_CREDENTIALS in .env before testing API access.")
        return 1

    print("credentials=configured")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
