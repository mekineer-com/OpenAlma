import io
import json
import sys
import urllib.error
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "launcher"))
import ai_settings
import app
import services


@pytest.fixture
def configured(tmp_path, monkeypatch):
    path = tmp_path / "mcp-memu-server/config.json"
    path.parent.mkdir()
    config = {"llm": {"provider": "openai", "base_url": ai_settings.OPENROUTER_URL,
                      "chat_model": "fictional/model", "api_key": "fictional-chat-secret",
                      "context_window_tokens": None,
                      "embedding": {"api_key": "fictional-embedding-secret", "base_url": "https://fictional.invalid/embed"},
                      "step_models": {"memory_extract": "fictional/other"}}, "keep": True}
    path.write_text(json.dumps(config))
    monkeypatch.setattr(app.settings, "apps_root", lambda: tmp_path)
    monkeypatch.setattr(app.settings, "setup_apps_root", lambda: None)
    monkeypatch.setattr(app.settings, "next_apps_root", lambda _stored: None)
    monkeypatch.setattr(app.settings, "read_paths", lambda: {})
    monkeypatch.setattr(app.services, "all_services", lambda: [])
    monkeypatch.setattr(app.services, "read_owner", lambda: None)
    monkeypatch.setattr(app.services, "list_souls", lambda: [])
    monkeypatch.setattr(app.services, "host_prerequisites", lambda *_args: {"rows": []})
    monkeypatch.setattr(app.setup_install, "launcher_update", lambda: None)
    def offline(*_args, **_kwargs):
        pytest.fail("Tests must not contact a live service")
    monkeypatch.setattr(app.services.urllib.request, "urlopen", offline)
    monkeypatch.setattr(ai_settings.urllib.request, "build_opener", offline)
    return path, config, TestClient(app.app, base_url="http://127.0.0.1")


def test_shared_form_missing_banner_and_full_settings_without_secrets(configured):
    path, config, client = configured
    home = client.get("/").text
    settings = client.get("/settings").text
    assert 'action="/settings/ai"' in home and 'action="/settings/ai"' in settings
    assert 'name="context_window_tokens"' in home
    assert 'name="chat_model"' not in home
    assert 'name="chat_model"' in settings
    assert 'name="embedding_api_key"' not in home
    assert 'name="embedding_api_key"' in settings
    for secret in ("fictional-chat-secret", "fictional-embedding-secret"):
        assert secret not in home + settings
    assert client.post("/settings/ai", data={"context_window_tokens": "64000"}).json() == {"ok": True}
    assert "AI setup needed." not in client.get("/").text
    assert json.loads(path.read_text())["llm"]["step_models"] == config["llm"]["step_models"]
    assert json.loads(path.with_name("config.json.orig").read_text()) == config


@pytest.mark.parametrize("running", [False, True])
def test_save_preserves_nested_settings_and_blank_keys(configured, monkeypatch, running):
    path, original, client = configured
    spec = services.ServiceSpec("memu-server", "memU Server", [], path.parent, path.parent / "log", path.parent / "pid")
    monkeypatch.setattr(app.services, "all_services", lambda: [spec])
    monkeypatch.setattr(app.services, "_runtime_state", lambda _: services.RuntimeState(running=running))
    calls = []
    monkeypatch.setattr(app.services, "_mcp_request", lambda route, body: calls.append((route, body)))
    response = client.post("/settings/ai", data={"embedding_api_key": "fictional-new-secret", "chat_api_key": ""})
    assert response.status_code == 200
    assert "fictional-new-secret" not in response.text
    if running:
        # The live server's existing merge_model_config merges embedding siblings.
        assert calls == [("/config", {"llm": {"embedding": {"api_key": "fictional-new-secret"}}})]
        assert json.loads(path.read_text()) == original
    else:
        saved = json.loads(path.read_text())
        assert saved["llm"]["embedding"] == {"api_key": "fictional-new-secret", "base_url": "https://fictional.invalid/embed"}
        assert saved["llm"]["api_key"] == original["llm"]["api_key"]
        assert saved["llm"]["step_models"] == original["llm"]["step_models"]
        assert saved["keep"] is True


@pytest.mark.parametrize("data", [
    {"context_window_tokens": "0"}, {"context_window_tokens": "-1"},
    {"context_window_tokens": "true"}, {"context_window_tokens": "1.5"},
    {"base_url": "file:///fictional"}, {"base_url": "https://user:secret@fictional.invalid"},
    {"base_url": "https://fictional.invalid:notaport/v1"},
    {"base_url": "https://fictional.invalid:99999/v1"},
    {"base_url": "https://other.invalid/v1", "chat_api_key": ""},
    {"chat_api_key": "fictional\nsecret"},
    {"chat_model": "YOUR_MODEL"}, {"unknown": "value"},
    {"keyless": "true", "chat_api_key": "fictional-conflict"}, {"keyless": "bad"},
])
def test_invalid_form_never_writes(configured, data):
    path, _config, client = configured
    before = path.read_bytes()
    assert client.post("/settings/ai", data=data).status_code == 400
    assert path.read_bytes() == before
    assert not path.with_name("config.json.orig").exists()


def test_keyless_and_cli_active_fields(configured):
    path, config, client = configured
    assert client.post("/settings/ai", data={"keyless": "true"}).status_code == 200
    assert json.loads(path.read_text())["llm"]["api_key"] == ""
    config["claude_code"] = True
    config["claude_code_context_window_tokens"] = None
    config["llm"]["embedding"]["api_key"] = "YOUR_GEMINI_API_KEY"
    path.write_text(json.dumps(config))
    html = client.get("/").text
    assert 'name="embedding_api_key"' in html
    assert 'name="claude_code_context_window_tokens"' in html
    assert 'name="chat_model"' not in client.get("/settings").text
    assert 'data-ai-autofill' not in html
    assert client.post("/settings/ai", data={"claude_code_context_window_tokens": "200000"}).status_code == 200
    assert client.post("/settings/ai", data={"context_window_tokens": "200000"}).status_code == 400
    assert client.post("/settings/ai", data={"keyless": "true"}).status_code == 400


def test_url_validation_uses_the_config_inside_the_save_lock(configured, monkeypatch):
    from contextlib import contextmanager
    from threading import RLock

    path, config, client = configured
    config["llm"]["api_key"] = ""
    path.write_text(json.dumps(config))
    lock = RLock()
    changed = False

    @contextmanager
    def another_save_won_first():
        nonlocal changed
        with lock:
            if not changed:
                changed = True
                latest = json.loads(path.read_text())
                latest["llm"]["api_key"] = "fictional-concurrent-secret"
                path.write_text(json.dumps(latest))
            yield

    class SaveLock:
        def __enter__(self):
            self.context = another_save_won_first()
            return self.context.__enter__()

        def __exit__(self, *args):
            return self.context.__exit__(*args)

    monkeypatch.setattr(app, "_CONFIG_WRITE_LOCK", SaveLock())
    response = client.post("/settings/ai", data={"base_url": "https://other.invalid/v1"})
    assert response.status_code == 400
    assert json.loads(path.read_text())["llm"]["base_url"] == ai_settings.OPENROUTER_URL


def test_metadata_suggests_minimum_without_writing_and_handles_keys(configured, monkeypatch):
    path, _config, client = configured
    before = path.read_bytes()
    calls = []
    def opened(request, timeout):
        calls.append((request, timeout))
        return io.BytesIO(json.dumps({"data": {"id": "fictional/model", "endpoints": [
            {"context_length": 128000, "max_prompt_tokens": 120000},
            {"context_length": 64000, "max_prompt_tokens": 32000},
        ]}}).encode())
    monkeypatch.setattr(ai_settings.urllib.request, "build_opener", lambda *_args: SimpleNamespace(open=opened))
    data = {"base_url": ai_settings.OPENROUTER_URL, "chat_model": "fictional/model"}
    assert client.post("/settings/ai/context", data=data).json() == {"context_window_tokens": 32000}
    request, timeout = calls[-1]
    assert request.full_url == ai_settings.OPENROUTER_URL + "/models/fictional/model/endpoints"
    assert request.get_header("Authorization") == "Bearer fictional-chat-secret"
    assert timeout == 10
    assert client.post("/settings/ai/context", data={**data, "keyless": "true"}).status_code == 200
    assert calls[-1][0].get_header("Authorization") is None
    assert client.post("/settings/ai/context", data={**data, "chat_api_key": "fictional-new"}).status_code == 200
    assert calls[-1][0].get_header("Authorization") == "Bearer fictional-new"
    assert path.read_bytes() == before
    assert not path.with_name("config.json.orig").exists()


@pytest.mark.parametrize("url", ["http://openrouter.ai/api/v1", "https://openrouter.ai.evil.invalid/api/v1",
    "https://openrouter.ai:443/api/v1", "https://secret@openrouter.ai/api/v1", "https://openrouter.ai/api/v2"])
def test_metadata_rejects_other_addresses_without_network(configured, url):
    _path, _config, client = configured
    result = client.post("/settings/ai/context", data={"base_url": url, "chat_model": "fictional/model"})
    assert result.status_code == 400
    assert "fictional-chat-secret" not in result.text


@pytest.mark.parametrize("payload", [[], {}, {"data": {"id": "wrong", "endpoints": []}},
    {"data": {"id": "fictional/model", "endpoints": []}},
    {"data": {"id": "fictional/model", "endpoints": [{"context_length": 64000, "max_prompt_tokens": None}]}},
    {"data": {"id": "fictional/model", "endpoints": [{"context_length": 64000, "max_prompt_tokens": True}]}}])
def test_metadata_does_not_guess_from_incomplete_limits(configured, monkeypatch, payload):
    _path, _config, client = configured
    monkeypatch.setattr(ai_settings.urllib.request, "build_opener", lambda *_args: SimpleNamespace(
        open=lambda *_args, **_kwargs: io.BytesIO(json.dumps(payload).encode())))
    result = client.post("/settings/ai/context", data={"base_url": ai_settings.OPENROUTER_URL, "chat_model": "fictional/model"})
    assert result.status_code == 400
    assert "context_window_tokens" not in result.json()


@pytest.mark.parametrize("error", [urllib.error.URLError("fictional-chat-secret"), ValueError("fictional-chat-secret")])
def test_metadata_errors_are_sanitized_and_redirects_not_followed(configured, monkeypatch, error):
    _path, _config, client = configured
    def opened(*_args, **_kwargs):
        raise error
    monkeypatch.setattr(ai_settings.urllib.request, "build_opener", lambda *_args: SimpleNamespace(open=opened))
    result = client.post("/settings/ai/context", data={"base_url": ai_settings.OPENROUTER_URL, "chat_model": "fictional/model"})
    assert result.status_code == 400
    assert "fictional-chat-secret" not in result.text
    assert ai_settings._NoRedirect().redirect_request(None, None, 302, "", {}, "https://fictional.invalid") is None
