"""Shared AI setup fields and metadata-only context suggestions."""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request


OPENROUTER_URL = "https://openrouter.ai/api/v1"


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


def suggest_context(base_url: str, model: str, api_key: str) -> int:
    if base_url.rstrip("/") != OPENROUTER_URL:
        raise ValueError("Auto-fill currently supports the direct OpenRouter API only. Enter this connection's size manually.")
    parts = model.split("/")
    if len(parts) != 2 or not all(parts) or any(part in {".", ".."} for part in parts):
        raise ValueError("Enter the exact OpenRouter model ID, including its author.")
    if "\n" in api_key or "\r" in api_key:
        raise ValueError("API keys must be a single line.")
    path = "/".join(urllib.parse.quote(part, safe="") for part in parts)
    request = urllib.request.Request(f"{OPENROUTER_URL}/models/{path}/endpoints",
                                     headers={"Authorization": f"Bearer {api_key}"} if api_key else {})
    try:
        with urllib.request.build_opener(_NoRedirect()).open(request, timeout=10) as response:
            payload = response.read(1_000_001)
    except (urllib.error.URLError, OSError, UnicodeError, ValueError) as exc:
        raise ValueError("Could not read provider metadata. Check the connection and key, or enter the size manually.") from exc
    if len(payload) > 1_000_000:
        raise ValueError("Model metadata is too large. Enter the context size manually.")
    try:
        data = json.loads(payload).get("data")
    except (UnicodeError, json.JSONDecodeError, AttributeError) as exc:
        raise ValueError("Could not read provider metadata. Enter the context size manually.") from exc
    if not isinstance(data, dict) or data.get("id") != model:
        raise ValueError("Provider metadata did not match the requested model.")
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
