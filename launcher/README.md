# OpenAlma Launcher

Mentra Iris has a permanent Services row for installation and phone status. Its temporary installer serves port 6789 only while installing/updating; it is not the conversation server. The launcher does not remotely stop phone conversations. memU Stop is blocked while any Iris sitting/start claim is busy. Unknown status requires an explicit interruption-risk confirmation, so a hung server or broken credential cannot trap the operator.

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

- On first use, confirm your name and, when no Souls exist, the first Soul's name together. If only the owner is saved, the launcher resumes at the unfinished Soul step.
- Changing Apps root is saved for the next launcher start; active service and Channels paths do not switch mid-run.
- Settings separates application setup gaps from runtime tools. Optional-client requirements appear only for clients whose checkout is present; Iris installation remains unavailable until its current `node`, `bun`, and `ip` release path can run.
- Stop Hermes Channels before selecting another Soul; restart it to load the new exact selection.
- Graceful Stop never force-kills. If a service is still stopping after 30 seconds, the separately confirmed Force Stop action becomes available as manual recovery.
- Packaged repair, update, and uninstall require every OpenAlma service to be stopped, even when the launcher window is already closed. The installer refuses rather than force-killing a service or deleting around locked data. If damaged launcher files prevent verification, only normal data-preserving uninstall remains available; Remove Everything stays disabled.
- If a core update cannot finish rolling back, the launcher exposes one Recover action. It restores the recorded Soul backup and previous core commits, validates them, and leaves Update for a separate retry; package restoration may require internet access.
- Iris connection settings belong to `mcp-memu-server/config.json`: `mentra.public_base_url` and `mentra.integration_bearer_token`. Settings checks host health and private ingress; static earcons are intentionally public. "Host ready" is not proof that the phone is connected.
- Install takes a soul and phone ID in Settings and discovers the shared owner from mcp. Install/Update generates Iris `.env.local` from these inputs before building; editing that artifact does not affect host readiness. An existing artifact gets a one-time `.orig` backup. Same-version Repair is shown only when OpenAlma Mentra has reported exact-acknowledgement support; stock Mentra cannot prove that a repair occurred.
- While an offer is live, Settings keeps the QR fallback visible, shows its exact Phone ID and connection values, and includes stock Mentra's developer-menu steps. A fresh exact-device Iris report stops first-install or version-changing-update offers automatically; same-version presence alone never closes Repair.
- Hermes uses one Iris-style editable soul field with attached existing-soul suggestions and an explicit arrow action. First Iris install retains its editable field and existing-soul dropdown. Both use the local MCP `/souls` API with user context. Lookup failure displays unavailable and preserves the current Channels configuration. Install config/target validation precedes soul creation; later build failures can still leave the created soul available for retry.
- Deploy the status endpoint, launcher, and Iris release wrapper together: status now requires the existing bearer. No phone bundle update is needed for this host-side change.
- Stop remains graceful and unbounded. If mcp reports no completed work for 30 seconds, the launcher reveals the separately confirmed Force Stop recovery action but never triggers it automatically.

- The launcher tracks PIDs in `~/.cache/openalma-launcher/`. Stopping the
  launcher does not stop the services it started — they keep running.
- The active soul lives in the channels config
  (`hermes-channels/data/config.json`: `soul_id`, `souls`,
  `reply_prefix_template`). The retired hermes-agent had its own "SOUL.md"
  persona file — unrelated to the memU soul concept; they shared a name only
  by accident.
