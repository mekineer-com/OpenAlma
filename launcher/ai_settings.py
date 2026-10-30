"""Shared AI setup fields and metadata-only context suggestions."""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request


OPENROUTER_URL = "https://openrouter.ai/api/v1"
NANOGPT_URLS = {"https://nano-gpt.com/api/v1", "https://api.nano-gpt.com/api/v1"}
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
MISTRAL_URL = "https://api.mistral.ai/v1"
XAI_URL = "https://api.x.ai/v1"


def _missing(value: object) -> bool:
    return not str(value or "").strip() or str(value).strip().startswith("YOUR_")


def describe(config: dict) -> dict:
    llm = config.get("llm", {})
    if not isinstance(llm, dict):
        raise ValueError("llm must be a JSON object.")
    embedding = llm.get("embedding", {})
    if not isinstance(embedding, dict):
        raise ValueError("llm.embedding must be a JSON object.")
    fields = []

    def field(name, label, value, *, secret=False, number=False, missing=None):
        fields.append({"name": name, "label": label,
                       "value": "" if secret else value if value is not None else "",
                       "type": "password" if secret else "number" if number else "text",
                       "missing": _missing(value) if missing is None else missing,
                       "saved": secret and not _missing(value)})

    cli = bool(config.get("claude_code"))
    if not cli:
        field("base_url", "API address", llm.get("base_url") or "https://api.openai.com/v1")
        field("chat_api_key", "chat API key", llm.get("api_key"), secret=True,
              missing=llm.get("api_key") != "" and _missing(llm.get("api_key")))
        field("chat_model", "chat model", llm.get("chat_model"))
    field("embedding_api_key", "embedding API key", embedding.get("api_key"), secret=True)
    capacity_name = "claude_code_context_window_tokens" if cli else "context_window_tokens"
    capacity = config.get(capacity_name) if cli else llm.get(capacity_name)
    field(capacity_name, "your model's context-window size", capacity, number=True,
          missing=type(capacity) is not int or capacity <= 0)
    missing = [row["label"] for row in fields if row["missing"]]
    labels = ", ".join(missing[:-1]) + ", and " + missing[-1] if len(missing) > 2 else " and ".join(missing)
    return {"fields": fields, "message": f"to enter {labels}." if missing else "",
            "cli": cli, "keyless": llm.get("api_key") == "", "error": ""}


def changes_from_form(form: dict, config: dict) -> dict:
    description = describe(config)
    allowed = {row["name"] for row in description["fields"]}
    if not description["cli"]:
        allowed.add("keyless")
    if set(form) - allowed:
        raise ValueError("Unknown AI setting submitted. Reload the page and try again.")
    changes: dict = {}
    llm: dict = {}
    for name, raw in form.items():
        value = str(raw).strip()
        if name == "keyless":
            if value != "true":
                raise ValueError("Invalid keyless choice.")
            if str(form.get("chat_api_key", "")).strip():
                raise ValueError("Choose either a chat API key or keyless access, not both.")
            llm["api_key"] = ""
        elif name.endswith("context_window_tokens"):
            if not value.isascii() or not value.isdecimal() or int(value) <= 0:
                raise ValueError("Context-window size must be a positive whole number.")
            if name == "claude_code_context_window_tokens":
                changes[name] = int(value)
            else:
                llm[name] = int(value)
        elif name in {"chat_api_key", "embedding_api_key"}:
            if not value:
                continue  # Blank password inputs never erase a saved secret.
            if _missing(value):
                raise ValueError("Replace the example API key with your own key.")
            if "\n" in value or "\r" in value:
                raise ValueError("API keys must be a single line.")
            if name == "embedding_api_key":
                llm["embedding"] = {"api_key": value}
            else:
                llm["api_key"] = value
        elif name == "base_url":
            try:
                url = urllib.parse.urlsplit(value)
                valid = url.scheme in {"http", "https"} and url.hostname and not (
                    url.username or url.password or url.query or url.fragment)
                url.port  # urlsplit otherwise accepts malformed ports.
            except ValueError:
                valid = False
            if not valid:
                raise ValueError("API address must be an HTTP or HTTPS URL without credentials or a query.")
            llm[name] = value.rstrip("/")
        else:
            if _missing(value):
                raise ValueError("Enter a chat model.")
            llm[name] = value
    previous = config.get("llm", {})
    if ("base_url" in llm and llm["base_url"] != str(previous.get("base_url") or "https://api.openai.com/v1").rstrip("/")
            and "api_key" not in llm and not _missing(previous.get("api_key"))):
        raise ValueError("Changing the API address requires an explicit API key or keyless choice.")
    if llm:
        changes["llm"] = llm
    return changes


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _model_metadata(request: urllib.request.Request) -> dict:
    try:
        with urllib.request.build_opener(_NoRedirect()).open(request, timeout=10) as response:
            payload = response.read(1_000_001)
    except (urllib.error.URLError, OSError, UnicodeError, ValueError) as exc:
        raise ValueError("Could not read provider metadata. Check the connection and key, or enter the size manually.") from exc
    if len(payload) > 1_000_000:
        raise ValueError("Model metadata is too large. Enter the context size manually.")
    try:
        data = json.loads(payload)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Could not read provider metadata. Enter the context size manually.") from exc
    if not isinstance(data, dict):
        raise ValueError("Could not read provider metadata. Enter the context size manually.")
    return data


def _positive_limit(value: object) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError("Incomplete model limits; enter the context size manually.")
    return value


def suggest_context(base_url: str, model: str, api_key: str) -> int:
    base_url = base_url.rstrip("/")
    if not model or any(part in {"", ".", ".."} for part in model.split("/")):
        raise ValueError("Enter the exact provider model ID.")
    if "\n" in api_key or "\r" in api_key:
        raise ValueError("API keys must be a single line.")
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    encoded_model = urllib.parse.quote(model, safe="")
    if base_url == OPENROUTER_URL:
        parts = model.split("/")
        if len(parts) != 2:
            raise ValueError("Enter the exact OpenRouter model ID, including its author.")
        path = "/".join(urllib.parse.quote(part, safe="") for part in parts)
        url = f"{base_url}/models/{path}/endpoints"
    elif base_url in NANOGPT_URLS:
        url = f"{base_url}/models?detailed=true"
    elif base_url == GEMINI_URL:
        google_model = model.removeprefix("models/")
        url = "https://generativelanguage.googleapis.com/v1beta/models/" + urllib.parse.quote(google_model, safe="")
        headers = {"x-goog-api-key": api_key} if api_key else {}
    elif base_url == MISTRAL_URL:
        url = f"{base_url}/models/{encoded_model}"
    elif base_url == XAI_URL:
        url = f"{base_url}/language-models/{encoded_model}"
    else:
        raise ValueError("Auto-fill is unavailable for this API address. Enter the context size manually.")
    data = _model_metadata(urllib.request.Request(url, headers=headers))
    if base_url in NANOGPT_URLS:
        rows = data.get("data")
        data = next((row for row in rows if isinstance(row, dict) and row.get("id") == model), None) if isinstance(rows, list) else None
        if not data:
            raise ValueError("Model not found in this host's catalog. Enter its context size manually.")
        # NanoGPT reports an input bound: keep it as a conservative total allowance.
        return _positive_limit(data.get("context_length"))
    if base_url == GEMINI_URL:
        if data.get("name") != f"models/{google_model}":
            raise ValueError("Provider metadata did not match the requested model.")
        # Do not add outputTokenLimit: the existing budget already reserves output.
        return _positive_limit(data.get("inputTokenLimit"))
    if base_url == OPENROUTER_URL:
        data = data.get("data")
    identity_matches = isinstance(data, dict) and data.get("id") == model
    if isinstance(data, dict) and base_url in {MISTRAL_URL, XAI_URL}:
        identity_matches = identity_matches or (
            isinstance(data.get("id"), str) and bool(data["id"].strip())
            and isinstance(data.get("aliases"), list) and model in data["aliases"])
    if not identity_matches:
        raise ValueError("Provider metadata did not match the requested model.")
    if base_url == MISTRAL_URL:
        return _positive_limit(data.get("max_context_length"))
    if base_url == XAI_URL:
        return _positive_limit(data.get("context_length"))
    endpoints = data.get("endpoints")
    if not isinstance(endpoints, list) or not endpoints:
        raise ValueError("No endpoint limits were reported for this model.")
    limits = []
    for endpoint in endpoints:
        if not isinstance(endpoint, dict):
            raise ValueError("Incomplete endpoint limits; enter the context size manually.")
        values = [endpoint.get("context_length"), endpoint.get("max_prompt_tokens")]
        if any(type(value) is not int or value <= 0 for value in values):
            raise ValueError("Incomplete endpoint limits; enter the context size manually.")
        limits.append(min(values))
    return min(limits)
