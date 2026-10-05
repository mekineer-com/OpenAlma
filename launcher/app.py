"""FastAPI app for the OpenAlma launcher."""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import webbrowser
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import policy
import chat_import
import services
import setup_install
import settings
import soul

ROOT = Path(__file__).resolve().parent
LAUNCHER_ID = "openalma-launcher"
templates = Jinja2Templates(directory=str(ROOT / "templates"))

CONFIG_LABELS: dict[str, str] = {
    "memu-server-config": "mcp-memu-server/config.json",
    "channels-config": "CHANNELS_HOME/config.json",
}

app = FastAPI(title="OpenAlma")
app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")


@app.middleware("http")
async def browser_mutations(request: Request, call_next):
    if request.method not in {"GET", "HEAD"}:
        host = getattr(app.state, "launcher_host", "127.0.0.1").lower()
        origin = request.headers.get("origin")
        site = request.headers.get("sec-fetch-site")
        trusted = host in {"0.0.0.0", "::"} or request.url.hostname in {host, "127.0.0.1", "localhost", "::1"}
        if (not trusted or origin is not None and origin != f"{request.url.scheme}://{request.url.netloc}"
                or site is not None and site not in {"same-origin", "none"}):
            return JSONResponse(status_code=403, content={"detail": "Use the OpenAlma launcher page for this action"})
    return await call_next(request)


@app.get("/favicon.svg", include_in_schema=False)
def favicon() -> FileResponse:
    return FileResponse(ROOT.parent / "docs" / "favicon.svg", media_type="image/svg+xml")


@app.get("/launcher/identity", include_in_schema=False)
def launcher_identity() -> dict[str, str | int]:
    return {"application": LAUNCHER_ID, "protocol": 1}


@app.get("/launcher/update-readiness", include_in_schema=False)
def launcher_update_readiness() -> dict[str, object]:
    active = [
        spec.label for spec in services.all_services()
        if _runtime_active(services.status(spec))
    ]
    return {"application": LAUNCHER_ID, "active_services": active}


@app.post("/launcher/window-position", include_in_schema=False)
def launcher_window_position(x: int, y: int) -> dict[str, bool]:
    paths = settings.read_paths()
    paths["window_position"] = {"x": x, "y": y}
    settings.write_paths(paths)
    return {"ok": True}


def _editable_configs(apps_root: Path | None) -> dict[str, Path]:
    """Resolve user-facing config files against active process paths."""
    out = {"channels-config": settings.channels_home() / "config.json"}
    if apps_root is not None:
        out["memu-server-config"] = apps_root / "mcp-memu-server" / "config.json"
    return out


def _find_service(name: str) -> services.ServiceSpec:
    for s in services.all_services():
        if s.name == name and services.is_installed(s):
            return s
    raise HTTPException(status_code=404, detail=f"Unknown service: {name}")


def _resolve_soul(soul_id: str, use_existing: bool) -> str:
    try:
        return services.resolve_soul(soul_id, use_existing)
    except services.SoulAlreadyExists as exc:
        raise HTTPException(
            status_code=409,
            detail={"reason": "existing_exact", "message": str(exc)},
        ) from exc
    except services.SoulServiceUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _runtime_active(row: dict) -> bool:
    return bool(
        row.get("running") or row.get("stuck") or row.get("orphaned") or row.get("blocked")
        or row.get("stoppable") or row.get("force_stoppable") or row.get("state") in {"stopping", "active"}
    )


def _row_with_setup(runtime: dict, setup: dict) -> dict:
    if _runtime_active(runtime):
        runtime["detail"] = "; ".join(filter(None, (runtime.get("detail"), setup.get("detail"))))
        runtime["startable"] = False
        return runtime
    return setup


def _setup_aware_status(spec: services.ServiceSpec, root: Path, *, verify_runtime: bool = True) -> dict:
    runtime = services.status(spec)
    if spec.name == "memu-server":
        if _runtime_active(runtime):
            update = setup_install.read_pending_release(root)
            if update:
                runtime["detail"] = "; ".join(filter(None, (
                    runtime.get("detail"), f"Core release {update} ready; Stop before updating",
                )))
            return runtime
        issue = setup_install.core_issue(root, verify_runtime=verify_runtime)
        setup = setup_install.setup_status(root, verify_runtime=verify_runtime, known_issue=issue)
        release = setup_install.release_issue("memu-server", root)
        return _row_with_setup(runtime, setup) if issue or setup_install.read_pending_release(root) or release else runtime
    setup = setup_install.optional_setup_status(spec.name, root)
    if not setup["ready"]:
        return _row_with_setup(runtime, setup)
    if setup["guidance"]:
        runtime["detail"] = "; ".join(filter(None, (runtime.get("detail"), setup["guidance"])))
    return runtime


def _require_startable_setup(service_name: str) -> None:
    root = settings.apps_root()
    if root is None:
        raise HTTPException(status_code=409, detail="Install core and restart OpenAlma first")
    try:
        issue = setup_install.start_issue(service_name, root)
    except setup_install.SetupError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if issue:
        raise HTTPException(status_code=409, detail=issue)


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    apps_root = settings.apps_root()
    setup_root = apps_root or settings.setup_apps_root()
    specs = services.all_services() if apps_root else (
        services.services_for_root(setup_root) if setup_root else []
    )
    install_in_progress = bool(setup_root) and any(
        setup_install.operation_status(setup_root, spec.name)["state"] == "running" for spec in specs
    )
    if apps_root is None:
        core = next((spec for spec in specs if spec.name == "memu-server"), None)
        rows = [
            {"name": core.name, "label": core.label} | setup_install.setup_status(setup_root)
        ] if core is not None else []
        not_installed = [
            {"name": spec.name, "label": spec.label, "install_enabled": False}
            for spec in specs if spec.name != "memu-server"
        ]
    else:
        rows = []
        not_installed = []
        for spec in specs:
            if spec.name == "iris-server":
                iris = {"name": spec.name, "label": spec.label} | _setup_aware_status(
                    spec, setup_root, verify_runtime=not install_in_progress,
                )
                (
                    rows
                    if iris.get("installed_package") or iris.get("running") or not iris.get("installation_known", True)
                    else not_installed
                ).append(iris)
                continue
            if services.is_installed(spec):
                rows.append(
                    {"name": spec.name, "label": spec.label} | _setup_aware_status(
                        spec, setup_root, verify_runtime=not install_in_progress,
                    )
                )
                continue
            if not services.is_installed(spec) and spec.name != "memu-server":
                setup = setup_install.optional_setup_status(spec.name, setup_root)
                not_installed.append({"name": spec.name, "label": spec.label} | setup)
    owner_id: str | None = None
    owner_error = ""
    try:
        owner_id = services.read_owner()
    except services.OwnerServiceUnavailable as exc:
        owner_error = str(exc)
    soul_ids: list[str] = []
    soul_error = ""
    try:
        soul_ids = services.list_souls()
    except (services.SoulServiceUnavailable, ValueError) as exc:
        soul_error = str(exc)
    memorize = [
        {**(services.memorize_pending(sid, owner_id) or {"error": "Memory status unavailable"}), "soul_id": sid}
        for sid in soul_ids
    ] if owner_id else []
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "services": rows,
            "not_installed_services": not_installed,
            "open_not_installed": any(
                row.get("open_not_installed") for row in not_installed
            ),
            "install_running": any(row.get("install_running") for row in rows + not_installed),
            "memorize": memorize,
            "soul_ids": soul_ids,
            "soul_error": soul_error,
            "apps_root": str(apps_root) if apps_root else "",
            "setup_root": str(setup_root) if setup_root else "",
            "needs_setup": apps_root is None,
            "owner_id": owner_id,
            "owner_error": owner_error,
            "launcher_update": setup_install.launcher_update(),
            "services_active": any(_runtime_active(row) for row in rows + not_installed),
        },
    )


@app.get("/memorize/status")
def memorize_status() -> dict:
    try:
        owner_id = services.read_owner()
        return {"souls": [
            {**(services.memorize_pending(sid, owner_id) or {"error": "Memory status unavailable"}), "soul_id": sid}
            for sid in services.list_souls()
        ] if owner_id else []}
    except (services.SoulServiceUnavailable, services.OwnerServiceUnavailable, ValueError) as exc:
        return {"souls": [], "error": str(exc)}


@app.post("/memorize/retry")
def memorize_retry(soul_id: str) -> dict:
    try:
        owner_id = services.read_owner()
        if soul_id not in services.list_souls() or not owner_id:
            raise HTTPException(status_code=404, detail="Soul not found")
        status = services.memorize_pending(soul_id, owner_id)
        if status.get("memorize_running") or status.get("consolidation_running"):
            raise HTTPException(status_code=409, detail="Memory work is still running")
        conversation_id = str(status.get("retry_conversation_id") or "").strip()
        if status.get("retry_operation") == "memorize":
            return services.retry_memorize(soul_id, owner_id)
        if status.get("retry_operation") == "consolidation" and conversation_id:
            return services.retry_consolidation(conversation_id, soul_id, owner_id)
        raise HTTPException(status_code=409, detail="No failed memory work is ready to retry")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (services.OwnerServiceUnavailable, services.SoulServiceUnavailable, RuntimeError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _echo_scope(soul_id: str, label: str = "") -> tuple[Path, dict]:
    root = settings.apps_root()
    if root is None:
        raise HTTPException(status_code=409, detail="Configure the Apps root first")
    try:
        owner_id = services.read_owner()
        if not owner_id:
            raise HTTPException(status_code=409, detail="Establish your OpenAlma identity first")
        if soul_id not in services.list_souls():
            raise HTTPException(status_code=404, detail="Select an existing Soul")
    except (services.OwnerServiceUnavailable, services.SoulServiceUnavailable) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return chat_import.source_path(root), {"user_id": owner_id, "soul_id": soul_id, "label": label.strip()}


def _echo_request(path: str, payload: dict | None = None, *, timeout: float = 2) -> dict:
    try:
        return services._mcp_request(path, payload, timeout=timeout)
    except urllib.error.HTTPError as exc:
        raise HTTPException(status_code=exc.code, detail=services._http_error_detail(exc)) from exc
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=503, detail="memU Server is unavailable; check status before retrying") from exc


@app.get("/echo", response_class=HTMLResponse)
def echo_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "echo.html", {
        "page_title": "Echo - OpenAlma", "setup_title": "Echo: Chat Importer",
        "setup_logo": "/static/echo-logo.svg",
    })


@app.get("/echo/chats")
def echo_chats(soul_id: str) -> dict:
    path, scope = _echo_scope(soul_id)
    return {"chats": chat_import.list_chats(path, user_id=scope["user_id"], soul_id=soul_id)}


@app.post("/echo/soul")
def echo_soul(soul_id: str = Form(), use_existing: bool = Form(default=False)) -> dict:
    return {"soul_id": _resolve_soul(soul_id, use_existing)}


def _echo_upload(file: UploadFile, soul_id: str, label: str, history_count: int,
                 all_history: bool, confirmed_new: bool, *, save: bool, preview_pending_start_day: str = "") -> dict:
    path, scope = _echo_scope(soul_id, label)
    try:
        messages, title, stats = chat_import.normalize_messages(json.load(file.file))
        if not messages:
            raise ValueError("The file has no text messages to import")
        count = len(messages) if all_history else history_count
        upload = chat_import.prepare_upload(path, **scope, messages=messages, history_count=count, title=title)
        scope["label"] = upload["label"]
        def dates(rows):
            days = [row["source_day"] for row in rows]
            return {"count": len(rows), "start": min(days, default=None), "end": max(days, default=None)}
        def duplicate_response():
            return {"conversation_id": upload["conversation_id"], "label": upload["label"], "saved": save,
                "total_messages": len(messages), "duplicates": upload["duplicates"], "stats": stats,
                "history": dates([]), "current": dates([]), "possible_overlap": False,
                "before_gap": "", "after_gap": "", "notice": "Messages already exist",
                "guidance": {"pending_start_day": None, "processed_start_day": None, "processed_end_day": None}}
        if not upload["messages"]:
            return duplicate_response()
        if save and not confirmed_new and not any(
            chat["label"].casefold() == scope["label"].casefold()
            for chat in chat_import.list_chats(path, user_id=scope["user_id"], soul_id=soul_id)
        ):
            raise HTTPException(status_code=409, detail="Confirm creation of this chat with the arrow first")
        guidance = _echo_request("/imports/validate", {**scope, "conversation_id": upload["conversation_id"],
            "title": title, "current_messages": [
                {key: row[key] for key in ("role", "content", "name", "timestamp", "source_day", "position")}
                for row in upload["messages"] if not row["historical"]
            ]}, timeout=60)
        if save and any(not row["historical"] for row in upload["messages"]) and (
                preview_pending_start_day != (guidance["pending_start_day"] or "")):
            raise HTTPException(status_code=409, detail="The current period changed. Preview again.")
        if save:
            upload = chat_import.store_upload(path, **scope, messages=messages, history_count=count, title=title)
            if not upload["messages"]:
                return duplicate_response()
            try:
                _echo_request("/imports/register", scope)
            except HTTPException as exc:
                raise HTTPException(status_code=exc.status_code,
                    detail="Source saved; registration incomplete. Use Register chat.") from exc
        incoming = dates(upload["messages"])
        processed_start, processed_end = guidance["processed_start_day"], guidance["processed_end_day"]
        return {"conversation_id": upload["conversation_id"], "label": upload["label"], "saved": save,
            "total_messages": len(messages), "duplicates": upload["duplicates"], "stats": stats,
            "history": dates([row for row in upload["messages"] if row["historical"]]),
            "current": dates([row for row in upload["messages"] if not row["historical"]]),
            "before_gap": messages[count - 1]["content"] if count else "",
            "after_gap": messages[count]["content"] if count < len(messages) else "",
            "possible_overlap": bool(processed_start and processed_end
                and incoming["start"] <= processed_end and incoming["end"] >= processed_start),
            "guidance": guidance, "notice": (
                "Merged new. Existing messages skipped." if upload["duplicates"] and any(not row["historical"] for row in upload["messages"])
                else "History saved. Existing messages skipped." if upload["duplicates"]
                else "Import stored.")}
    except (ValueError, UnicodeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/echo/preview")
def echo_preview(file: UploadFile, soul_id: str = Form(), label: str = Form(),
                 history_count: int = Form(default=0), all_history: bool = Form(default=True)) -> dict:
    return _echo_upload(file, soul_id, label, history_count, all_history, False, save=False)


@app.post("/echo/confirm")
def echo_confirm(file: UploadFile, soul_id: str = Form(), label: str = Form(),
                 history_count: int = Form(default=0), all_history: bool = Form(default=True),
                 confirmed_new: bool = Form(default=False), preview_pending_start_day: str = Form(default="")) -> dict:
    return _echo_upload(file, soul_id, label, history_count, all_history, confirmed_new, save=True,
                        preview_pending_start_day=preview_pending_start_day)


@app.post("/echo/{action}")
def echo_action(action: str, soul_id: str = Form(), label: str = Form()) -> dict:
    if action not in {"register", "process", "retry"}:
        raise HTTPException(status_code=404, detail="Unknown import action")
    _path, scope = _echo_scope(soul_id, label)
    return _echo_request(f"/imports/{action}", scope)


@app.get("/echo/status")
def echo_status(soul_id: str, label: str) -> dict:
    path, scope = _echo_scope(soul_id, label)
    chat = next((chat for chat in chat_import.list_chats(path, user_id=scope["user_id"], soul_id=soul_id)
                 if chat["label"].casefold() == scope["label"].casefold()), None)
    if chat is None:
        return {"stored": False}
    scope["label"] = chat["label"]
    try:
        result = _echo_request("/imports/status?" + urllib.parse.urlencode(scope))
    except HTTPException as exc:
        if exc.status_code == 409:
            return {"stored": True, "registered": False, "label": chat["label"]}
        raise
    return {**result, "stored": True, "registered": True, "label": chat["label"],
            "meter": services.memorize_pending(soul_id, scope["user_id"])}


@app.get("/echo/results")
def echo_results(soul_id: str) -> dict:
    _path, scope = _echo_scope(soul_id)
    query = urllib.parse.urlencode({"user_id": scope["user_id"], "soul_id": soul_id})
    categories = _echo_request("/categories?" + query)
    pending = _echo_request("/pending?" + query)
    return {"categories": categories["categories"], "soul_summaries": pending["soul_summaries"]}


@app.get("/hermes", response_class=HTMLResponse)
def hermes_page(request: Request) -> HTMLResponse:
    channels_configured = soul.CHANNELS_CONFIG_PATH.exists()
    chats = policy.list_whatsapp_chats()
    current, default_policy = (
        policy.ensure_channel_settings(chats)
        if channels_configured
        else (policy.read_channel_settings(), policy.read_default_policy())
    )
    chat_rows = []
    for c in chats:
        chat_id = str(c.get("id", ""))
        saved = policy.settings_for_chat(chat_id, current)
        chat_rows.append(
            {
                "id": chat_id,
                "name": str(c.get("name", "")),
                "type": str(c.get("type", "")),
                "policy": str(saved.get("policy") or default_policy),
                "memorize": bool(saved.get("memorize", default_policy != "excluded")),
            }
        )
    visible_chats = [c for c in chat_rows if c["policy"] != "excluded"]
    excluded_chats = [c for c in chat_rows if c["policy"] == "excluded"]
    active_soul = ""
    channels_error = ""
    try:
        active_soul = soul.read_active_soul_id()
    except RuntimeError as exc:
        channels_error = str(exc)
    soul_ids: list[str] = []
    soul_error = ""
    try:
        soul_ids = services.list_souls()
    except (services.SoulServiceUnavailable, ValueError) as exc:
        soul_error = str(exc)
    return templates.TemplateResponse(request, "hermes.html", {
        "page_title": "Hermes setup — OpenAlma",
        "chats": chat_rows,
        "visible_chats": visible_chats,
        "excluded_chats": excluded_chats,
        "channel_directory_path": str(policy.DIRECTORY_PATH),
        "policies": policy.ALL_POLICIES,
        "default_policy": default_policy,
        "active_soul": active_soul,
        "channels_configured": channels_configured,
        "channels_error": channels_error,
        "soul_ids": soul_ids, "soul_error": soul_error,
    })


@app.get("/iris", response_class=HTMLResponse)
def iris_page(request: Request) -> HTMLResponse:
    apps_root = settings.apps_root()
    iris_spec = next((spec for spec in services.all_services() if spec.name == "iris-server"), None)
    iris = services.status(iris_spec) if iris_spec else {}
    iris_setup = iris.get("setup") or services.mentra_readiness(apps_root)
    iris_connection = {}
    if apps_root:
        try:
            mentra = json.loads(
                (apps_root / "mcp-memu-server" / "config.json").read_text(encoding="utf-8")
            ).get("mentra") or {}
            iris_connection = {
                "base_url": str(mentra.get("public_base_url") or ""),
                "bearer": str(mentra.get("integration_bearer_token") or ""),
            }
        except (OSError, ValueError):
            pass
    return templates.TemplateResponse(request, "iris.html", {
        "page_title": "Iris setup", "iris": iris, "iris_setup": iris_setup,
        "iris_connection": iris_connection,
    })


@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request) -> HTMLResponse:
    apps_root = settings.apps_root()
    stored = settings.read_paths().get("apps_root") or ""
    candidate = settings.next_apps_root(stored)
    setup_root = settings.setup_apps_root()
    editable = [
        {"key": key, "label": CONFIG_LABELS.get(key, key)}
        for key in _editable_configs(apps_root)
    ]
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "apps_root_active": str(apps_root) if apps_root else "",
            "apps_root_stored": str(stored),
            "apps_root_invalid": bool(stored and candidate is None),
            "apps_root_setup_target": str(setup_root) if setup_root else "",
            "apps_root_pending": setup_root is not None and candidate is None,
            "apps_root_restart_required": candidate is not None and candidate != apps_root,
            "editable_configs": editable,
            "settings_path": str(settings.SETTINGS_PATH),
            "launcher_log_path": str(settings.LAUNCHER_LOG_PATH),
            "host_prerequisites": services.host_prerequisites(apps_root or setup_root),
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
    return RedirectResponse("/settings", status_code=303)


@app.post("/install/{service_name}")
def install_service(service_name: str) -> RedirectResponse:
    root = settings.setup_apps_root() if service_name == "memu-server" else settings.apps_root()
    if root is None:
        raise HTTPException(status_code=400, detail="Install core and restart OpenAlma first")
    spec = next((item for item in services.services_for_root(root) if item.name == service_name), None)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"Unknown service: {service_name}")
    if _runtime_active(services.status(spec)):
        raise HTTPException(status_code=409, detail=f"Stop {spec.label} before changing its installation")
    try:
        if service_name == "memu-server":
            setup_install.begin_core_install(root)
        else:
            setup_install.begin_optional_install(service_name, root)
    except setup_install.SetupConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except setup_install.SetupError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RedirectResponse("/", status_code=303)


@app.post("/install/memu-server/recover")
def recover_core() -> RedirectResponse:
    root = settings.setup_apps_root()
    if root is None:
        raise HTTPException(status_code=400, detail="OpenAlma Apps root is unavailable")
    if active := launcher_update_readiness()["active_services"]:
        raise HTTPException(status_code=409, detail="Stop all OpenAlma services before recovery: " + ", ".join(active))
    try:
        setup_install.begin_core_recovery(root)
    except setup_install.SetupConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except setup_install.SetupError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RedirectResponse("/", status_code=303)


@app.get("/install/{service_name}/status")
def install_service_status(service_name: str) -> dict:
    root = settings.setup_apps_root() if service_name == "memu-server" else settings.apps_root()
    if root is None:
        return {"state": "unavailable"}
    if service_name == "memu-server":
        return setup_install.setup_status(root)
    try:
        return setup_install.optional_setup_status(service_name, root)
    except setup_install.SetupError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown service: {service_name}") from exc


@app.get("/install/{service_name}/logs", response_class=HTMLResponse)
def install_service_logs(request: Request, service_name: str) -> HTMLResponse:
    root = settings.setup_apps_root() or settings.apps_root()
    labels = {
        spec.name: spec.label for spec in services.services_for_root(root)
    } if root else {}
    if service_name not in labels:
        raise HTTPException(status_code=404, detail=f"Unknown service: {service_name}")
    return templates.TemplateResponse(
        request,
        "logs.html",
        {
            "service": f"{service_name}-install",
            "label": f"{labels[service_name]} installation",
            "log_path": str(setup_install.install_log_path(service_name)),
            "content": setup_install.install_log(service_name),
            "lines": 0,
        },
    )


@app.post("/launcher/quit")
def launcher_quit(request: Request) -> dict[str, bool]:
    shutdown = getattr(request.app.state, "request_shutdown", None)
    if shutdown is None:
        raise HTTPException(status_code=503, detail="Launcher shutdown is unavailable")
    shutdown()
    return {"ok": True}


@app.get("/logs/{service_name}", response_class=HTMLResponse)
def logs(request: Request, service_name: str, lines: int = 200) -> HTMLResponse:
    if service_name == "launcher":
        label, log_path = "OpenAlma Launcher", settings.LAUNCHER_LOG_PATH
    else:
        spec = _find_service(service_name)
        label, log_path = spec.label, spec.log_path
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        text = ""
    tail = "\n".join(text.splitlines()[-lines:])
    return templates.TemplateResponse(
        request,
        "logs.html",
        {
            "service": service_name,
            "label": label,
            "log_path": str(log_path),
            "content": tail,
            "lines": lines,
        },
    )


@app.post("/service/{service_name}/start")
def service_start(service_name: str, soul_id: str = "", device_session_id: str = "") -> dict:
    spec = _find_service(service_name)
    _require_startable_setup(service_name)
    try:
        target = None
        if service_name == "iris-server" and (soul_id or device_session_id):
            if not soul_id or not device_session_id:
                raise ValueError("Iris Update/Repair requires its Soul and Phone ID")
            target = {"soul_id": soul_id, "device_session_id": device_session_id}
        if target:
            services.start(spec, install_target=target)
        else:
            services.start(spec)
    except services.ServiceStoppingError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, **services.status(spec)}


@app.post("/service/{service_name}/open")
def service_open(service_name: str) -> dict[str, bool]:
    spec = _find_service(service_name)
    if not spec.open_url:
        raise HTTPException(status_code=404, detail=f"{spec.label} has no page to open")
    if not webbrowser.open_new_tab(spec.open_url):
        raise HTTPException(status_code=503, detail="The default browser could not be opened")
    return {"ok": True}


@app.post("/iris/install")
def iris_install(
    soul_id: str = Form(), device_session_id: str = Form(), use_existing: bool = Form(default=False),
) -> RedirectResponse:
    spec = _find_service("iris-server")
    _require_startable_setup("iris-server")
    target = {"soul_id": soul_id, "device_session_id": device_session_id}
    try:
        services.raise_if_stopping(spec)
        services.iris_install_env(target)
        target["soul_id"] = _resolve_soul(soul_id, use_existing)
        services.start(spec, install_target=target)
    except services.ServiceStoppingError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except services.OwnerServiceUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RedirectResponse("/iris", status_code=303)


@app.get("/souls")
def souls() -> dict:
    try:
        return {"souls": services.list_souls()}
    except services.SoulServiceUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/owner")
def owner() -> dict:
    try:
        return {"user_id": services.read_owner()}
    except services.OwnerServiceUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/service/{service_name}/stop")
def service_stop(service_name: str, confirm_unknown: bool = False) -> dict:
    spec = _find_service(service_name)
    try:
        services.stop(spec, confirm_unknown=confirm_unknown)
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except services.StopConfirmationRequired as exc:
        raise HTTPException(status_code=428, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"ok": True, **services.status(spec)}


@app.post("/service/{service_name}/force-stop")
def service_force_stop(service_name: str, confirmed: bool = False) -> dict:
    spec = _find_service(service_name)
    if not confirmed:
        raise HTTPException(
            status_code=428,
            detail="Force Stop may interrupt an active conversation or lose unfinished work. Continue?",
        )
    try:
        services.force_stop(spec)
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"ok": True, **services.status(spec)}


@app.get("/service/{service_name}/status")
def service_status(service_name: str) -> dict:
    spec = _find_service(service_name)
    root = settings.apps_root()
    if root is None:
        raise HTTPException(status_code=409, detail="Install core and restart OpenAlma first")
    return _setup_aware_status(spec, root, verify_runtime=False)


@app.get("/whatsapp/pair-status")
def whatsapp_pair_status() -> dict:
    return services.whatsapp_pair_status()


@app.post("/policy")
async def policy_save(request: Request) -> RedirectResponse:
    form = await request.form()
    default_policy = form.get("default_policy")
    if isinstance(default_policy, str) and default_policy in policy.ALL_POLICIES:
        policy.write_default_policy(default_policy)
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
    return RedirectResponse("/hermes", status_code=303)


@app.post("/soul")
def soul_save(soul_id: str = Form(default=""), use_existing: bool = Form(default=False)) -> RedirectResponse:
    channels = services.status(_find_service("channels-daemon"))
    if (
        channels.get("running")
        or channels.get("stuck")
        or channels.get("orphaned")
        or channels.get("state") == "stopping"
    ):
        raise HTTPException(status_code=409, detail="Stop Hermes Channels before changing its Soul")
    soul.set_active_soul_id(_resolve_soul(soul_id, use_existing))
    return RedirectResponse("/hermes", status_code=303)


@app.post("/owner")
def owner_save(
    user_id: str = Form(),
    soul_id: str = Form(default=""),
    confirmed: bool = Form(default=False),
) -> RedirectResponse:
    if not confirmed:
        raise HTTPException(status_code=400, detail="Confirm the spelling of your name")
    try:
        services.create_owner(user_id)
        if soul_id.strip():
            _resolve_soul(soul_id, False)
    except services.OwnerServiceUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return RedirectResponse("/", status_code=303)


@app.post("/first-soul")
def first_soul_save(soul_id: str = Form(), confirmed: bool = Form(default=False)) -> RedirectResponse:
    if not confirmed:
        raise HTTPException(status_code=400, detail="Confirm the spelling of the Soul's name")
    _resolve_soul(soul_id, False)
    return RedirectResponse("/", status_code=303)


@app.post("/edit/{key}")
def edit_config(key: str) -> RedirectResponse:
    target = _editable_configs(settings.apps_root()).get(key)
    if target is None:
        raise HTTPException(status_code=404, detail=f"Unknown config: {key}")
    webbrowser.open(target.resolve().as_uri())
    return RedirectResponse("/", status_code=303)
