"""FastAPI app for the memU stack launcher."""
from __future__ import annotations

import subprocess
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

import policy
import services
import settings
import soul

ROOT = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(ROOT / "templates"))

CONFIG_LABELS: dict[str, str] = {
    "memu-server-config": "mcp-memu-server/config.json",
    "hermes-config": "~/.hermes/config.yaml",
    "hermes-persona": "~/.hermes/SOUL.md  (Hermes persona, not our soul)",
}

app = FastAPI(title="memU Stack")


def _editable_configs(apps_root: Path | None) -> dict[str, Path]:
    """Resolve user-facing config file paths against the active apps_root."""
    out: dict[str, Path] = {
        "hermes-config": Path.home() / ".hermes" / "config.yaml",
        "hermes-persona": Path.home() / ".hermes" / "SOUL.md",
    }
    if apps_root is not None:
        out["memu-server-config"] = apps_root / "mcp-memu-server" / "config.json"
    return out


def _find_service(name: str) -> services.ServiceSpec:
    for s in services.all_services():
        if s.name == name:
            return s
    raise HTTPException(status_code=404, detail=f"Unknown service: {name}")


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    apps_root = settings.apps_root()
    specs = services.all_services()
    rows = [
        ({
            "name": s.name,
            "label": s.label,
            "supports_terminal": s.supports_terminal,
        } | services.status(s))
        for s in specs
    ]
    chats = policy.list_whatsapp_chats()
    current = policy.read_channel_settings()
    chat_rows = [
        {
            "id": str(c.get("id", "")),
            "name": str(c.get("name", "")),
            "type": str(c.get("type", "")),
            "policy": str(current.get(str(c.get("id", "")), {}).get("policy") or "full"),
            "memorize": bool(current.get(str(c.get("id", "")), {}).get("memorize", True)),
        }
        for c in chats
    ]
    editable_paths = _editable_configs(apps_root)
    editable = [
        {"key": k, "label": CONFIG_LABELS.get(k, k), "path": str(p)}
        for k, p in editable_paths.items()
    ]
    active_soul = soul.read_active_soul_id()
    soul_ids = soul.list_soul_ids()
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "services": rows,
            "chats": chat_rows,
            "policies": policy.ALL_POLICIES,
            "active_soul": active_soul,
            "soul_ids": soul_ids,
            "editable_configs": editable,
            "apps_root": str(apps_root) if apps_root else "",
            "needs_setup": apps_root is None,
        },
    )


@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request) -> HTMLResponse:
    apps_root = settings.apps_root()
    stored = settings.read_paths().get("apps_root") or ""
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "apps_root_active": str(apps_root) if apps_root else "",
            "apps_root_stored": str(stored),
            "settings_path": str(settings.SETTINGS_PATH),
        },
    )


@app.post("/settings")
def settings_save(apps_root: str = Form(default="")) -> RedirectResponse:
    current = settings.read_paths()
    new_root = apps_root.strip()
    if new_root:
        current["apps_root"] = new_root
    else:
        current.pop("apps_root", None)
    settings.write_paths(current)
    return RedirectResponse("/", status_code=303)


@app.get("/logs/{service_name}", response_class=HTMLResponse)
def logs(request: Request, service_name: str, lines: int = 200) -> HTMLResponse:
    spec = _find_service(service_name)
    try:
        text = spec.log_path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        text = ""
    tail = "\n".join(text.splitlines()[-lines:])
    return templates.TemplateResponse(
        request,
        "logs.html",
        {
            "service": spec.name,
            "label": spec.label,
            "log_path": str(spec.log_path),
            "content": tail,
            "lines": lines,
        },
    )


@app.post("/service/{service_name}/start")
def service_start(
    service_name: str,
    show_terminal: str = Form(default=""),
) -> dict:
    spec = _find_service(service_name)
    services.start(spec, show_terminal=bool(show_terminal))
    return {"ok": True, **services.status(spec)}


@app.post("/service/{service_name}/stop")
def service_stop(service_name: str) -> dict:
    spec = _find_service(service_name)
    services.stop(spec)
    return {"ok": True, **services.status(spec)}


@app.get("/service/{service_name}/status")
def service_status(service_name: str) -> dict:
    spec = _find_service(service_name)
    return services.status(spec)


@app.post("/whatsapp/pair-bridge")
def whatsapp_pair_bridge() -> dict:
    if not services.launch_whatsapp_bridge_pairing():
        raise HTTPException(status_code=500, detail="Could not open a terminal for hermes whatsapp")
    spec = _find_service("hermes-gateway")
    return {"ok": True, **services.status(spec)}


@app.post("/policy")
async def policy_save(request: Request) -> RedirectResponse:
    form = await request.form()
    updates: dict[str, dict[str, bool | str]] = {}
    for key, val in form.items():
        if isinstance(key, str) and key.startswith("policy[") and key.endswith("]"):
            chat_id = key[len("policy["):-1]
            if val in policy.ALL_POLICIES:
                memorize = f"memorize[{chat_id}]" in form
                updates[chat_id] = {
                    "policy": val,
                    "memorize": memorize,
                }
    if updates:
        policy.write_channel_settings(updates)
    return RedirectResponse("/", status_code=303)


@app.post("/soul")
def soul_save(soul_id: str = Form(default="")) -> RedirectResponse:
    soul.set_active_soul_id(soul_id)
    return RedirectResponse("/", status_code=303)


@app.post("/edit/{key}")
def edit_config(key: str) -> RedirectResponse:
    target = _editable_configs(settings.apps_root()).get(key)
    if target is None:
        raise HTTPException(status_code=404, detail=f"Unknown config: {key}")
    subprocess.Popen(["xdg-open", str(target)], start_new_session=True)
    return RedirectResponse("/", status_code=303)
