# OpenAlma Launcher

One place to open your companion's chats, explore her memories, and manage
OpenAlma. Start the apps you want to use and leave the rest stopped:

- OpenAlma's memory services
- Iris for voice and photos
- Atomic Mind Map
- Hermes Channels
- SillyTavern

Use **Setup** beside an app to configure it. Hermes lets you choose which
WhatsApp chats your companion can hear and answer; Iris connects her to your
phone or smartglasses. **Settings** holds general OpenAlma preferences.

For a guided installation, start with [Getting started](https://openalma.org/getting-started.html).

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

The launcher opens its own window when a Chromium-based browser is available,
or a page in your default browser otherwise. You can also visit
`http://127.0.0.1:8765`. Its own window remembers your zoom and, where supported,
its size and position. Opening the shortcut again brings that window forward.

Flags:

- `--port N` — listen on a different port (default `8765`)
- `--no-browser` — don't auto-open the UI

## Start menu shortcut (Linux)

```sh
cp memu-stack.desktop ~/.local/share/applications/
update-desktop-database ~/.local/share/applications/ 2>/dev/null || true
```

## Windows (unreleased)

The upcoming Windows installer will let you open OpenAlma from the Start menu
without a terminal window. It is not published yet.

## Notes

- On first use, confirm your name and choose or create your companion's Soul.
- Each Soul has its own memory progress and recovery controls.
- Stop Hermes before switching its Soul, then start it again.
- New WhatsApp chats are excluded until you choose to include them. Changing
  the default for new chats does not change the choices for existing chats.
- **Stop** gives an app time to finish safely. If it gets stuck, you can choose
  **Force Stop** after 30 seconds; OpenAlma will not do that automatically.
- Finish your Iris conversation before stopping the memory services.
- If memory processing fails, the launcher shows the problem and a **Retry**
  button. You decide when to try again; other Souls can continue independently.
- Closing the launcher does not stop the apps it started. Stop them first if
  you want to shut down OpenAlma completely.
- Stop all OpenAlma apps before updating, repairing or uninstalling. If an update
  needs recovery, follow the launcher's **Recover** action.

## Echo (In Development)

Echo brings chat exports into OpenAlma so your companion does not have to start
over. Choose her Soul and the app the chat came from, then **Preview** the dates
and messages before choosing **Import**. Messages already imported are skipped.

Messages in the current period join the unmemorized chat; older messages are
archived. Past conversations can currently become memories only before a Soul
has memorized conversations of her own. Echo's processing controls are still
being finished; it is not yet ready for everyday use.
