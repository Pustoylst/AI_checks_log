"""Application entry point placeholder for the next implementation stage."""

from app.config import get_settings


def main() -> None:
    """Print the configured model without exposing credentials."""

    settings = get_settings()
    credential_state = "configured" if settings.has_gigachat_credentials else "missing"
    print(f"GigaChat model: {settings.gigachat_model}")
    print(f"GigaChat credentials: {credential_state}")


if __name__ == "__main__":
    main()
