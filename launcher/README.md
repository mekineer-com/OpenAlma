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
Stop memU Server before installing/updating Atomic: its Claude session helper
is installed into the memory server's Python environment.

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
python3.12 run.py --install-shortcut
```

This creates your application-menu entry with this checkout's actual paths.
Run it again after moving the checkout. Startup failures open an error page;
running `python3.12 run.py` in a terminal also shows installation diagnostics.

## Windows

Download the [latest OpenAlma Beta installer](https://github.com/mekineer-com/OpenAlma/releases/latest)
to open OpenAlma from the Start menu without a terminal window. Beta is available
on the Stable channel. Launcher startup/tests are verified; full Windows component
installation remains separately qualified.

When a new OpenAlma release is available, stop all apps and choose **Update**.
The launcher downloads and opens the new installer; **Show installer** brings
that installer window forward if it is hidden.

The launcher downloads the matching Atomic Windows server during **Install**
and prepares its web dependencies without Rust or
Visual Studio. Working manual/debug binaries stay selected. Source-changing
updates of unproven manual builds are refused rather than overwriting them.
The component manifest selects the matching prebuilt server package.

## Notes

- OpenAlma prepares Iris's computer-side tools automatically after a
  phone connects. The main row has APK/QR/Setup links only; installing Iris on a
  phone still requires its Install action. Stock's explicit Install prepares
  tools as needed. Preparation failures offer Retry in Setup.
- On first use, confirm your name and choose or create your companion's Soul.
- Settings groups Apps root, Soul Workspace, launcher preferences and the log under **Host paths**. Source installs keep `paths.json` and `launcher.log` in the OpenAlma folder; Windows uses `%LOCALAPPDATA%\OpenAlma`. Existing preferences are moved once with their original kept as an `.orig` backup. Changing Soul Workspace does not move its files.
- Each Soul has its own memory progress and recovery controls.
- **Hide not installed** moves uninstalled services into the existing collapsed section. It disappears when all services are installed.
- Echo's **Install** enables the bundled importer once; only **Setup** remains afterward. Echo updates with the memory server.
- Stop Hermes before switching its Soul, then start it again.
- New WhatsApp chats are excluded until you choose to include them. Changing
  the default for new chats does not change the choices for existing chats.
- **Stop** gives an app time to finish safely. If it gets stuck, you can choose
  **Force Stop** after 15 seconds; OpenAlma will not do that automatically.
- Finish your Iris conversation before stopping the memory services.
- If memory processing fails, the launcher shows the problem and a **Retry**
  button. You decide when to try again; other Souls can continue independently.
- **Exit** shuts down the launcher and closes its own window. Neither Exit nor
  closing the window stops the apps it started; stop them first if you want to
  shut down OpenAlma completely.
- Stop all OpenAlma apps before updating, repairing or uninstalling. Updating
  the memory services first backs up their settings and Soul databases, and a
  failed update puts the previous version back. If the launcher still shows
  **Recover**, choose it to finish restoring.

## Echo (In Development)

Echo brings chat exports into OpenAlma so your companion does not have to start
over. Choose her Soul and the app the chat came from, then **Preview** the dates
and messages before choosing **Import**. Messages already imported are skipped.

Messages in the current period join the unmemorized chat; older messages are
archived. Past conversations can currently become memories only before a Soul
has memorized conversations of her own. Echo's processing controls are still
being finished; it is not yet ready for everyday use.
