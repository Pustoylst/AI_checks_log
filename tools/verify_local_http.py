"""Read-only smoke check against the running project server."""
import argparse
import httpx


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    with httpx.Client(base_url=args.url, timeout=15, trust_env=False) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert "Qwen3 8B" in page.text
        assert 'src="https://' not in page.text
        assert 'href="https://' not in page.text
        script = client.get("/static/app.js")
        assert script.status_code == 200
        assert "newText.textContent = payload.new_text" in script.text
        response = client.post("/analyze", files={"file": ("log.json", '{"message":"smoke check"}', "application/json")})
        assert response.status_code == 502, response.text
        assert "Ollama" in response.json()["detail"]
        print("PASS: local page/assets served; no external page assets; literal code preview; unavailable Ollama reported as HTTP 502")
        print("NOT CHECKED: browser rendering/interactions; real Qwen3 inference")


if __name__ == "__main__":
    main()
