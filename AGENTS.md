# OpenAlma Launcher and Public Docs

README.md and docs/ welcome prospective users; launcher/README.md explains
installation and everyday use. Keep implementation constraints here, not in
those introductions. Task progress belongs in its plan or audit.

## Where to Work

- `launcher/run.py`: bootstrap and launcher process entry.
- `launcher/app.py`, `services.py`, `soul.py`: web app, service lifecycle and Soul setup.
- `launcher/templates/`, `launcher/static/`: launcher and Echo UI.
- `release-components.json`: coordinated component versions and installation sources.
- `docs/`: the public website; describe released behavior in plain language.

OpenAlma owns when an app starts and stops; each app owns how it starts.
Echo's UI is here; import orchestration belongs to mcp-memu-server.

Routine notices and errors use the shared inline message, not browser alerts.
Clicking Force Stop is confirmation: do not ask again. Its request supplies
the existing `confirmed=true`; the direct-API confirmation guard remains.

## Runtime Dependencies

`requirements.txt` pins runtime dependencies, including transitive packages.
Maintainers edit the direct inputs in `requirements.in`, regenerate from the
OpenAlma repository root, and test before shipping:

```sh
uv pip compile --universal --python-version 3.12 launcher/requirements.in -o launcher/requirements.txt
```
