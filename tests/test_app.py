from fastapi.testclient import TestClient

from app.main import create_app


def test_health():
    app = create_app(start_bot=False)
    client = TestClient(app)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
