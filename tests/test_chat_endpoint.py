'''
Tests for POST /api/chat's request validation. No prior coverage existed.

The AI-off path is exercised directly (real, no network) since it returns
before touching any AI client. The prompt-construction/AI-on path is already
covered by tests/test_ai_connections.py's stub-model tests.

License: MIT  (https://opensource.org/license/mit)
'''


def test_ai_off_returns_friendly_message_not_an_error(client, tmp_path, monkeypatch):
    import app
    monkeypatch.setattr(app, "USER_CONFIG_PATH", str(tmp_path / "user_config.json"))
    resp = client.post("/api/chat", json={"message": "set location to Chicago"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ai"] is False
    assert "AI is switched off" in body["say"]


def test_empty_message_is_rejected(client):
    assert client.post("/api/chat", json={"message": ""}).status_code == 400
    assert client.post("/api/chat", json={}).status_code == 400
    assert client.post("/api/chat").status_code == 400


def test_overlong_message_is_rejected(client):
    resp = client.post("/api/chat", json={"message": "x" * 2001})
    assert resp.status_code == 400


def test_malformed_json_is_rejected_not_500(client):
    resp = client.post("/api/chat", data="not json", content_type="application/json")
    assert resp.status_code == 400
