import pytest
from pydantic import ValidationError
from app.config import Settings


def test_default_local_settings():
    settings = Settings(_env_file=None)
    assert settings.ollama_model == "qwen3:8b"
    assert settings.ollama_base_url == "http://127.0.0.1:11434"
    assert settings.ollama_num_ctx == 8192
    assert settings.ollama_timeout_seconds == 180


@pytest.mark.parametrize("url", ["https://example.org", "http://192.168.1.2:11434", "http://user:pass@localhost:11434", "http://localhost/api"])
def test_reject_remote_inference(url):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, ollama_base_url=url)


@pytest.mark.parametrize("url", ["http://localhost:11434", "http://127.0.0.1:11434/", "http://[::1]:11434"])
def test_accept_loopback(url):
    assert Settings(_env_file=None, ollama_base_url=url).ollama_base_url == url.rstrip("/")
