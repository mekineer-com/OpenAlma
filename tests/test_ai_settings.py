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
    {"data": {"id": "fictional/model", "endpoints": [{"context_length": None, "max_prompt_tokens": 64000}]}},
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


@pytest.mark.parametrize("base_url, model, payload, metadata_url, auth_header", [
    ("https://nano-gpt.com/api/v1", "fictional/model", {"data": [
        {"id": "fictional/wrong", "context_length": 999999},
        {"id": "fictional/model", "context_length": 64000, "max_output_tokens": 8000}]},
        "https://nano-gpt.com/api/v1/models?detailed=true", "Authorization"),
    ("https://api.nano-gpt.com/api/v1", "fictional/model", {"data": [
        {"id": "fictional/model", "context_length": 64000}]},
        "https://api.nano-gpt.com/api/v1/models?detailed=true", "Authorization"),
    (ai_settings.GEMINI_URL, "fictional-model", {
        "name": "models/fictional-model", "inputTokenLimit": 64000, "outputTokenLimit": 8000},
        "https://generativelanguage.googleapis.com/v1beta/models/fictional-model", "X-goog-api-key"),
    (ai_settings.MISTRAL_URL, "fictional-model", {"id": "fictional-model", "max_context_length": 64000},
        "https://api.mistral.ai/v1/models/fictional-model", "Authorization"),
    (ai_settings.XAI_URL, "fictional-model", {"id": "fictional-model", "context_length": 64000},
        "https://api.x.ai/v1/models/fictional-model", "Authorization"),
])
def test_other_providers_use_their_own_metadata_without_writing(
        configured, monkeypatch, base_url, model, payload, metadata_url, auth_header):
    path, config, client = configured
    config["llm"].update(base_url=base_url, chat_model=model)
    path.write_text(json.dumps(config))
    before = path.read_bytes()
    calls = []

    def opened(request, timeout):
        calls.append(request)
        return io.BytesIO(json.dumps(payload).encode())

    monkeypatch.setattr(ai_settings.urllib.request, "build_opener", lambda *_args: SimpleNamespace(open=opened))
    result = client.post("/settings/ai/context", data={"base_url": base_url + "/", "chat_model": model})
    assert result.json() == {"context_window_tokens": 64000}
    assert calls[0].full_url == metadata_url
    expected = "fictional-chat-secret" if auth_header == "X-goog-api-key" else "Bearer fictional-chat-secret"
    assert calls[0].get_header(auth_header) == expected
    assert "fictional-chat-secret" not in result.text
    assert path.read_bytes() == before
    assert not path.with_name("config.json.orig").exists()

    # Incomplete limits never become a guessed allowance or another host's data.
    row = payload["data"][-1] if "data" in payload else payload
    field = "inputTokenLimit" if base_url == ai_settings.GEMINI_URL else "max_context_length" if base_url == ai_settings.MISTRAL_URL else "context_length"
    row[field] = None
    assert client.post("/settings/ai/context", data={"base_url": base_url, "chat_model": model}).status_code == 400
    assert len(calls) == 2
    row[field] = 64000
    row["name" if base_url == ai_settings.GEMINI_URL else "id"] = "fictional/wrong-model"
    assert client.post("/settings/ai/context", data={"base_url": base_url, "chat_model": model}).status_code == 400
    assert len(calls) == 3


def test_nanogpt_hosts_do_not_share_catalogs_or_saved_credentials(configured, monkeypatch):
    path, config, client = configured
    config["llm"].update(base_url="https://nano-gpt.com/api/v1")
    path.write_text(json.dumps(config))
    calls = []

    def opened(request, timeout):
        calls.append(request)
        return io.BytesIO(json.dumps({"data": [{"id": "fictional/other", "context_length": 32000}]}).encode())

    monkeypatch.setattr(ai_settings.urllib.request, "build_opener", lambda *_args: SimpleNamespace(open=opened))
    result = client.post("/settings/ai/context", data={
        "base_url": "https://api.nano-gpt.com/api/v1", "chat_model": "fictional/model"})
    assert result.status_code == 400
    assert "Model not found" in result.json()["detail"]
    assert len(calls) == 1
    assert calls[0].full_url == "https://api.nano-gpt.com/api/v1/models?detailed=true"
    assert calls[0].get_header("Authorization") is None


@pytest.mark.parametrize("base_url, field", [
    (ai_settings.MISTRAL_URL, "max_context_length"), (ai_settings.XAI_URL, "context_length")])
@pytest.mark.parametrize("canonical, aliases, expected", [
    ("fictional-canonical", ["fictional-latest"], 64000),
    ("fictional-canonical", ["fictional-other"], None),
    ("fictional-canonical", "fictional-latest", None),
    ("", ["fictional-latest"], None),
])
def test_provider_aliases_must_be_explicit_and_well_formed(configured, monkeypatch, base_url, field, canonical, aliases, expected):
    _path, _config, client = configured
    payload = {"id": canonical, "aliases": aliases, field: 64000}
    monkeypatch.setattr(ai_settings.urllib.request, "build_opener", lambda *_args: SimpleNamespace(
        open=lambda *_args, **_kwargs: io.BytesIO(json.dumps(payload).encode())))
    result = client.post("/settings/ai/context", data={"base_url": base_url, "chat_model": "fictional-latest"})
    assert result.status_code == (200 if expected else 400)
    if expected:
        assert result.json() == {"context_window_tokens": expected}


def test_first_setup_shows_provider_address_and_saves_selected_provider(configured):
    path, config, client = configured
    config["llm"].update(base_url="https://api.openai.com/v1", chat_model="YOUR_MODEL", api_key="YOUR_KEY")
    path.write_text(json.dumps(config))
    html = client.get("/").text
    assert 'name="base_url" type="text"' in html
    assert 'name="chat_model"' in html
    result = client.post("/settings/ai", data={"base_url": "https://nano-gpt.com/api/v1",
        "chat_model": "fictional/model", "chat_api_key": "fictional-nano-key", "context_window_tokens": "64000"})
    assert result.status_code == 200
    assert json.loads(path.read_text())["llm"]["base_url"] == "https://nano-gpt.com/api/v1"
    assert "AI setup needed." not in client.get("/").text

    saved = json.loads(path.read_text())
    saved["llm"]["chat_model"] = "YOUR_MODEL"
    path.write_text(json.dumps(saved))
    html = client.get("/").text
    assert 'name="chat_api_key" type="password" value=""' in html
    assert 'name="keyless"' in html
    assert "fictional-nano-key" not in html


def test_openrouter_null_prompt_cap_uses_required_context_bound(configured, monkeypatch):
    _path, _config, client = configured
    payload = {"data": {"id": "fictional/model", "endpoints": [
        {"context_length": 128000, "max_prompt_tokens": None},
        {"context_length": 64000, "max_prompt_tokens": 48000}]}}
    monkeypatch.setattr(ai_settings.urllib.request, "build_opener", lambda *_args: SimpleNamespace(
        open=lambda *_args, **_kwargs: io.BytesIO(json.dumps(payload).encode())))
    result = client.post("/settings/ai/context", data={"base_url": ai_settings.OPENROUTER_URL, "chat_model": "fictional/model"})
    assert result.json() == {"context_window_tokens": 48000}


def test_unchecked_keyless_requires_a_key_without_erasing_config(configured):
    path, config, client = configured
    config["llm"]["api_key"] = ""
    path.write_text(json.dumps(config))
    before = path.read_bytes()
    result = client.post("/settings/ai", data={"chat_api_key": ""})
    assert result.status_code == 400
    assert "choose keyless" in result.json()["detail"]
    assert path.read_bytes() == before


def test_backups_keep_original_and_latest_three_numbered_copies(configured):
    path, _config, client = configured
    original = path.read_bytes()
    for size in range(32000, 32007):
        assert client.post("/settings/ai", data={"context_window_tokens": str(size)}).status_code == 200
    assert path.with_name("config.json.orig").read_bytes() == original
    numbered = sorted(path.parent.glob("config.json_*.orig"))
    assert [p.name for p in numbered] == ["config.json_5.orig", "config.json_6.orig", "config.json_7.orig"]
    assert [json.loads(p.read_text())["llm"]["context_window_tokens"] for p in numbered] == [32003, 32004, 32005]


def test_save_shows_live_server_refusal_and_blank_lookup_model(configured, monkeypatch):
    _path, _config, client = configured
    def refused(_changes):
        raise urllib.error.HTTPError("http://fictional.invalid/config", 400, "Bad Request", {},
                                     io.BytesIO(b'{"detail":"Fictional configuration refusal"}'))
    monkeypatch.setattr(app, "_save_memu_config", refused)
    result = client.post("/settings/ai", data={"context_window_tokens": "64000"})
    assert result.json()["detail"] == "Fictional configuration refusal"
    result = client.post("/settings/ai/context", data={"base_url": ai_settings.OPENROUTER_URL, "chat_model": ""})
    assert result.status_code == 400
    assert result.json()["detail"] == "Enter the exact provider model ID."


def test_refused_save_keeps_existing_backup_history(configured, monkeypatch):
    path, _config, client = configured
    for number in range(2, 6):
        path.with_name(f"config.json_{number}.orig").write_text("fictional snapshot")
    path.with_name("config.json.orig").write_text("fictional original")
    spec = services.ServiceSpec("memu-server", "memU Server", [], path.parent, path.parent / "log", path.parent / "pid")
    monkeypatch.setattr(app.services, "all_services", lambda: [spec])
    monkeypatch.setattr(app.services, "_runtime_state", lambda _: services.RuntimeState(running=True))
    def refused(*_args):
        raise urllib.error.HTTPError("http://fictional.invalid/config", 400, "Bad Request", {}, io.BytesIO(b'{}'))
    monkeypatch.setattr(app.services, "_mcp_request", refused)
    assert client.post("/settings/ai", data={"context_window_tokens": "64000"}).status_code == 400
    for number in range(2, 6):
        assert path.with_name(f"config.json_{number}.orig").read_text() == "fictional snapshot"
