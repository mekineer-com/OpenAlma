"""Soul selector helpers for the memU stack launcher."""
from __future__ import annotations

from pathlib import Path
import tempfile

try:
    import yaml
except ModuleNotFoundError as exc:  # pragma: no cover
    yaml = None  # type: ignore[assignment]
    _YAML_IMPORT_ERROR = exc
else:
    _YAML_IMPORT_ERROR = None

HERMES_CONFIG_PATH = Path.home() / ".hermes" / "config.yaml"


def _load_config() -> dict:
    if yaml is None:
        raise RuntimeError(
            "PyYAML is required for soul selection. Install launcher dependencies from "
            "launcher/requirements.txt."
        ) from _YAML_IMPORT_ERROR
    try:
        raw = HERMES_CONFIG_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"Failed to read {HERMES_CONFIG_PATH}: {exc}") from exc
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise RuntimeError(f"Invalid YAML in {HERMES_CONFIG_PATH}: {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise RuntimeError(f"Expected mapping at top level in {HERMES_CONFIG_PATH}")
    return data


def _write_config(config: dict) -> None:
    if yaml is None:
        raise RuntimeError(
            "PyYAML is required for soul selection. Install launcher dependencies from "
            "launcher/requirements.txt."
        ) from _YAML_IMPORT_ERROR
    HERMES_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    dumped = yaml.safe_dump(
        config,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
    )
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=str(HERMES_CONFIG_PATH.parent),
        delete=False,
    ) as tmp:
        tmp.write(dumped)
        tmp_path = Path(tmp.name)
    tmp_path.replace(HERMES_CONFIG_PATH)


def _soul_agents(config: dict) -> list[dict]:
    soul_mode = config.get("soul_mode")
    if not isinstance(soul_mode, dict):
        return []
    agents = soul_mode.get("agents")
    if not isinstance(agents, dict):
        return []
    out: list[dict] = []
    for agent_cfg in agents.values():
        if not isinstance(agent_cfg, dict):
            continue
        role = str(agent_cfg.get("role") or "").strip().lower()
        if role == "soul":
            out.append(agent_cfg)
    return out


def read_active_soul_id() -> str:
    config = _load_config()
    agents = _soul_agents(config)
    if not agents:
        return ""
    first = agents[0]
    return str(first.get("soul_id") or "").strip()


def list_soul_ids() -> list[str]:
    config = _load_config()
    out: set[str] = set()
    for agent_cfg in _soul_agents(config):
        soul_id = str(agent_cfg.get("soul_id") or "").strip()
        if soul_id:
            out.add(soul_id)
    return sorted(out, key=lambda value: value.lower())


def set_active_soul_id(soul_id: str) -> None:
    selected = str(soul_id or "").strip()
    if not selected:
        raise RuntimeError("Soul ID cannot be empty")

    config = _load_config()
    soul_mode = config.get("soul_mode")
    if not isinstance(soul_mode, dict):
        soul_mode = {}
        config["soul_mode"] = soul_mode
    agents = soul_mode.get("agents")
    if not isinstance(agents, dict):
        agents = {}
        soul_mode["agents"] = agents

    updated = False
    for agent_cfg in agents.values():
        if not isinstance(agent_cfg, dict):
            continue
        role = str(agent_cfg.get("role") or "").strip().lower()
        if role != "soul":
            continue
        agent_cfg["soul_id"] = selected
        updated = True

    if not updated:
        main_cfg = agents.get("main")
        if not isinstance(main_cfg, dict):
            main_cfg = {}
            agents["main"] = main_cfg
        main_cfg["enabled"] = bool(main_cfg.get("enabled", True))
        main_cfg["role"] = "soul"
        main_cfg["soul_id"] = selected

    _write_config(config)
