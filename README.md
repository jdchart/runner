# Runner

A small macOS app to start, stop and open your local projects, all at once, each on its
own port. It also opens preconfigured Terminal sessions (e.g. Claude) in project folders.

**Open it:** double-click `Runner.app`, or drag it to the Dock (keep the bundle in this
repo, since it runs the code next to it). The first launch creates `.venv` and installs
Flask and pywebview. Nothing is compiled: change the code and reopen the app, or change
anything in `data/` and it shows up within a second or two.

Without the window: `.venv/bin/python -m runner --browser` (UI at http://127.0.0.1:4747).

## Projects

Each tracked project is a folder in `data/projects/<id>/`. Your projects and groups are
gitignored: they're yours, not part of the app.

| file | |
|---|---|
| `project.json` | name, path, kind, group, description, tags, commands, port, url_path, host |
| `start.sh` | run with the project folder as cwd; gets `$PORT`; must stay in the foreground (`exec …`) |
| `close.sh` | optional graceful shutdown; the whole process group is killed afterwards anyway |
| `assets/logo.*` | svg/png/jpg/…; picked up from the project's favicon when added |

- **Servers** (the default kind) get a fixed port and open at `http://<id>.localhost:<port>`.
  A separate hostname per project keeps each app's cookies apart. Set `"host"` for an app
  that only answers to `localhost`/`127.0.0.1`.
- **`"kind": "terminal"`**: a folder you only open a shell in. No port, no scripts.
- **`"commands"`**: one-click Terminal sessions in the folder, e.g. `Claude = claude`.
- **`"group"`**: puts the project in a group (`data/groups/<id>/group.json` + `assets/logo.*`).
  Groups show after the standalone projects, as collapsible sections with Start all / Stop all.

Add projects with **＋ Add project** (templates in `data/templates/`: `python-flask`,
`node`, `blank`), or ask Claude Code to use the `add-project` skill, which also checks
that the project actually starts.

Projects keep running when Runner is closed; reopening it picks them up again.
Logs are in `state/logs/`.

The app icon's source is `assets/runner-icon.svg`. `.claude/CLAUDE.md` explains how to
rebuild `Runner.app/Contents/Resources/icon.icns` from it.
