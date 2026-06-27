# OpenAlma Launcher

A small local web UI that starts, stops, and configures the four services in OpenAlma:

- `mcp-memu-server` (memory engine)
- `hermes-agent` gateway (WhatsApp/SillyTavern bridge to the soul)
- WhatsApp bridge (Baileys/Node)
- SillyTavern

It also includes a GUI for the per-chat WhatsApp policy file (`~/.hermes/memu.json`)
and shortcuts to open the rarely-edited config files in your default editor.

## Setup

```sh
cd memu-local-stack/launcher
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Run

```sh
.venv/bin/python run.py
```

The launcher serves on `http://127.0.0.1:8765` and opens a chromeless window
(Chrome / Edge / Brave / Chromium / Vivaldi). If no Chromium-family browser is
installed, it falls back to opening the URL in your default browser.

Flags:

- `--port N` — listen on a different port (default `8765`)
- `--no-browser` — don't auto-open the UI

## Start menu shortcut (Linux)

```sh
cp memu-stack.desktop ~/.local/share/applications/
update-desktop-database ~/.local/share/applications/ 2>/dev/null || true
```

## Notes

- The launcher tracks PIDs in `~/.cache/openalma-launcher/`. Stopping the
  launcher does not stop the services it started — they keep running.
- `~/.hermes/SOUL.md` is the *Hermes persona file* (a hermes-agent convention),
  not the memU soul concept. They share a name only by accident.
