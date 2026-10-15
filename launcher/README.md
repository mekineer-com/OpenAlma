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

On Linux, Python 3.12 creates the launcher's private environment on first run:

```sh
cd openalma/launcher
python3.12 run.py
```

On Debian/Ubuntu, install `python3.12-venv` alongside Python 3.12 so environment
creation includes pip.

Later launches reuse that environment. When an update changes `requirements.txt`,
the launcher installs the updated dependencies before starting. If setup fails,
fix the reported problem and run the same command again.

`requirements.txt` pins runtime dependencies, including transitive packages.
Maintainers edit the direct inputs in `requirements.in`, regenerate from the
OpenAlma repository root, and test before shipping:

```sh
uv pip compile --universal --python-version 3.12 launcher/requirements.in -o launcher/requirements.txt
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

## Windows

Download the [OpenAlma v0.1.15 Beta installer](https://github.com/mekineer-com/OpenAlma/releases/tag/v0.1.15)
to open OpenAlma from the Start menu without a terminal window. Beta is available
on the Stable channel. Launcher startup/tests are verified; full Windows component
installation remains separately qualified.

The launcher follows Edge's replacement process when it hands off startup, so
that handoff no longer stops the server while the app window remains open.

The launcher downloads the matching Atomic Windows server during **Install**
and prepares its web dependencies without Rust or
Visual Studio. Working manual/debug binaries stay selected. Source-changing
updates of unproven manual builds are refused rather than overwriting them.
The compatible server package remains on Atomic's v0.1.12 release; the component
manifest is unchanged.

## Notes

- Development sources prepare Iris's computer-side tools automatically after a
  phone connects. The main row has APK/QR/Setup links only; installing Iris on a
  phone still requires its Install action. Stock's explicit Install prepares
  tools as needed. Preparation failures offer Retry in Setup.
- On first use, confirm your name and choose or create your companion's Soul.
- Each Soul has its own memory progress and recovery controls.
- **Hide not installed** moves uninstalled services into the existing collapsed section. It disappears when all services are installed.
- Echo's **Install** enables the bundled importer once; only **Setup** remains afterward. Echo updates with the memory server.
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
