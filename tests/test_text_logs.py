import pytest
from fastapi.testclient import TestClient
from app.api import app
from app.log_input import MAX_UPLOAD_BYTES
from app.schemas import FixProposal

client = TestClient(app)


@pytest.mark.parametrize('encoding', ['utf-8', 'utf-8-sig', 'utf-16', 'cp1251'])
@pytest.mark.parametrize('suffix', ['log', 'txt', 'LOG'])
def test_text_log_reaches_analysis(monkeypatch, encoding, suffix):
    text = '2026-11-20 ERROR Ошибка соединения\r\nTraceback:\r\n  TimeoutError'
    captured = []
    def analyze(data, repo_root=None):
        captured.append(data)
        return 'Анализ выполнен'
    monkeypatch.setattr('app.api.analyze_log', analyze)
    response = client.post('/analyze', files={'file': (f'vm.{suffix}', text.encode(encoding), 'application/octet-stream')})
    assert response.status_code == 200
    assert captured == [{'log_format': 'text', 'message': text}]


@pytest.mark.parametrize('raw,status', [(b'', 400), (b'   ', 400), (b'abc\x00def', 400), (b'x' * 12001, 413), (b'x' * (MAX_UPLOAD_BYTES + 1), 413)], ids=['empty', 'spaces', 'binary', 'text_limit', 'upload_limit'])
@pytest.mark.parametrize('endpoint', ['/analyze', '/propose-fix'])
def test_rejects_unusable_text_without_model(monkeypatch, tmp_path, raw, status, endpoint):
    def unexpected(*args, **kwargs):
        pytest.fail('Invalid input must not reach model')
    monkeypatch.setattr('app.api.analyze_log', unexpected)
    response = client.post(endpoint, params={'repo': str(tmp_path)}, files={'file': ('vm.log', raw)})
    assert response.status_code == status


def test_text_proposal_uses_same_log_and_does_not_write(monkeypatch, tmp_path):
    text = 'ERROR subtract(5, 4) returned 9 instead of 1\n'
    captured = []
    def analyze(data, **kwargs):
        captured.append(data)
        return 'Причина: сложение'
    def propose(data, root, **kwargs):
        captured.append(data)
        return FixProposal(path='calculator.py', explanation='Вычитание', old_text='a + b', new_text='a - b')
    monkeypatch.setattr('app.api.analyze_log', analyze)
    monkeypatch.setattr('app.api.propose_fix', propose)
    response = client.post('/propose-fix', params={'repo': str(tmp_path)}, files={'file': ('vm.log', text)})
    assert response.status_code == 200
    assert captured == [{'log_format': 'text', 'message': text}] * 2
    assert not list(tmp_path.iterdir())


def test_unsupported_file():
    response = client.post('/analyze', files={'file': ('file.exe', b'abc')})
    assert response.status_code == 400


def test_frontend_accepts_text():
    html = client.get('/').text
    assert 'accept=".json,.log,.txt,' in html
