"""Exercise the real local model with an in-memory text upload."""
from fastapi.testclient import TestClient
from app.api import app


def main():
    text = ('2026-11-20 12:34:56 ERROR Connection to database failed\n'
            'System.TimeoutException: Connection timed out after 30 seconds\n'
            '   at Database.OpenConnection()\n')
    with TestClient(app) as client:
        response = client.post('/analyze', files={'file': ('example.log', text.encode('utf-8'), 'text/plain')})
    print('HTTP', response.status_code)
    if response.status_code != 200:
        raise RuntimeError(response.text)
    result = response.json()['result']
    assert result.strip(), 'Empty analysis'
    print(result)
    print('PASS real .log upload and local model analysis; no source files written')


if __name__ == '__main__':
    main()
