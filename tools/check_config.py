"""Check local Ollama availability without starting inference."""

import httpx
from app.config import get_settings


def main() -> int:
    settings = get_settings()
    print(f"model={settings.ollama_model}")
    print(f"server={settings.ollama_base_url}")
    try:
        with httpx.Client(timeout=5, trust_env=False) as client:
            response = client.get(f"{settings.ollama_base_url}/api/tags")
            response.raise_for_status()
            names = {item["name"] for item in response.json()["models"]}
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as error:
        print(f"Ollama недоступен: {error}")
        print("Установите и запустите Ollama: https://ollama.com/download/windows")
        return 1
    if settings.ollama_model not in names:
        print(f"Модель не найдена. Выполните: ollama pull {settings.ollama_model}")
        return 1
    print("Ollama доступен, модель скачана. Скорость и качество требуют отдельной проверки.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
