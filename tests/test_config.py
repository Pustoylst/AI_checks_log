from app.config import Settings


def test_default_gigachat_settings() -> None:
    settings = Settings(_env_file=None)

    assert settings.gigachat_scope == "GIGACHAT_API_PERS"
    assert settings.gigachat_model == "GigaChat-2-Max"
    assert settings.gigachat_fallback_model == "GigaChat-2"
    assert settings.gigachat_verify_ssl_certs is False


def test_credentials_are_optional_for_log_only_mode() -> None:
    settings = Settings(_env_file=None)

    assert settings.has_gigachat_credentials is False
