# OpenAlma Launcher

The Iris MiniApp Server has its own Start/Stop row. The memU Server row separately shows the phone sitting as display-only Iris status; the launcher never controls the phone session.

A small local web UI that starts, stops, and configures the local OpenAlma services:

- `mcp-memu-server` (memory engine)
- Iris MiniApp Server
- Atomic Mind Map
- Hermes Channels
- SillyTavern

It also includes a GUI for the per-chat WhatsApp policy file (`CHANNELS_HOME/memu.json`)
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
- The active soul lives in the channels config
  (`hermes-channels/data/config.json`: `soul_id`, `souls`,
  `reply_prefix_template`). The retired hermes-agent had its own "SOUL.md"
  persona file — unrelated to the memU soul concept; they shared a name only
  by accident.
