# OpenAlma Launcher

Mentra Iris has a permanent Services row for installation and phone status. Its temporary installer serves port 6789 only while installing/updating; it is not the conversation server. The launcher does not remotely stop phone conversations. memU Stop is blocked while any Iris sitting/start claim is busy, or its status is unknown.

A small local web UI that starts, stops, and configures the local OpenAlma services:

- `mcp-memu-server` (memory engine)
- Mentra Iris private installer
- Atomic Mind Map
- Hermes Channels
- SillyTavern

It also includes a GUI for the per-chat WhatsApp policy file (`CHANNELS_HOME/memu.json`)
and shortcuts to open the rarely-edited config files in your default editor.

## Setup

```sh
cd openalma/launcher
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

- Iris connection settings belong to `mcp-memu-server/config.json`: `mentra.public_base_url` and `mentra.integration_bearer_token`. Settings checks host health and private ingress; static earcons are intentionally public. "Host ready" is not proof that the phone is connected.
- Install takes an explicit user, soul and phone ID in Settings. Repair uses the server's existing installation record, never Channels identity. Install/Update/Repair generates Iris `.env.local` from these inputs before building; editing that artifact does not affect host readiness. An existing artifact gets a one-time `.orig` backup.
- Deploy the status endpoint, launcher, and Iris release wrapper together: status now requires the existing bearer. No phone bundle update is needed for this host-side change.

- The launcher tracks PIDs in `~/.cache/openalma-launcher/`. Stopping the
  launcher does not stop the services it started — they keep running.
- The active soul lives in the channels config
  (`hermes-channels/data/config.json`: `soul_id`, `souls`,
  `reply_prefix_template`). The retired hermes-agent had its own "SOUL.md"
  persona file — unrelated to the memU soul concept; they shared a name only
  by accident.
