"""Exercise the real ChatOllama adapter against a local protocol fixture, not a model."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

from app.agent import analyze_log, propose_fix
from app.config import Settings
from app.fixes import apply_approved_fix
import pytest


@pytest.fixture
def ollama_server():
    requests = []
    responses = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append(payload)
            message = responses.pop(0)
            body = json.dumps({"model": "qwen3:8b", "message": message, "done": True}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.end_headers()
            self.wfile.write(body + b"\n")

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield Settings(_env_file=None, ollama_base_url=f"http://127.0.0.1:{server.server_port}"), requests, responses
    server.shutdown()
    server.server_close()
    thread.join()


def test_real_adapter_search_read_and_approved_fix(ollama_server, tmp_path):
    settings, requests, responses = ollama_server
    source = tmp_path / "service.py"
    source.write_text("TIMEOUT = 60\n", encoding="utf-8")
    docs_path = tmp_path / "rx262"
    docs_path.mkdir()
    (docs_path / "timeouts.htm").write_text(
        "<html><head><title>Настройка таймаутов Directum RX</title></head>"
        "<body><div id='idcontent'><p>Таймаут подключения к сервису.</p></div></body></html>",
        encoding="utf-8",
    )
    settings.directum_docs_path = docs_path
    responses.extend([
        {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "search_code_in_repo", "arguments": {"query": "TIMEOUT"}}}]},
        {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "read_git_file", "arguments": {"path": "service.py"}}}]},
        {"role": "assistant", "content": "Причина: TIMEOUT = 60 в service.py."},
        {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "read_git_file", "arguments": {"path": "service.py"}}}]},
        {"role": "assistant", "content": json.dumps({"path": "service.py", "explanation": "Увеличить таймаут", "old_text": "TIMEOUT = 60", "new_text": "TIMEOUT = 120"})},
    ])
    assert "service.py" in analyze_log({"message": "timeout"}, tmp_path, settings)
    proposal = propose_fix({"message": "timeout"}, tmp_path, settings)
    assert source.read_text() == "TIMEOUT = 60\n"
    assert all(request["model"] == "qwen3:8b" and request["think"] is False for request in requests)
    assert requests[0]["options"]["num_ctx"] == 8192
    assert {tool["function"]["name"] for tool in requests[0]["tools"]} == {
        "read_git_file", "search_code_in_repo", "list_repository_files",
        "search_directum_documentation",
    }
    assert any(message["role"] == "tool" and "TIMEOUT = 60" in message["content"] for message in requests[2]["messages"])
    with pytest.raises(PermissionError):
        apply_approved_fix(tmp_path, proposal.path, proposal.old_text, proposal.new_text, False)
    assert source.read_text() == "TIMEOUT = 60\n"
    assert apply_approved_fix(tmp_path, proposal.path, proposal.old_text, proposal.new_text, True) == "service.py"
    assert source.read_text() == "TIMEOUT = 120\n"
    assert {item.name for item in tmp_path.iterdir()} == {"service.py", "rx262"}
