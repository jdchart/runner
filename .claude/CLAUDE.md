# Runner

A macOS app for starting, stopping and opening local projects (Python/Flask and Node
dev servers, all at the same time), and for opening preconfigured Terminal sessions
(e.g. `claude`) in project folders. Projects can be grouped (e.g. an app and its
library in one repo).

The user's own projects and groups (`data/projects/`, `data/groups/`) are gitignored,
so this repo can be shared. Notes about their specific projects and machine belong in
`CLAUDE.local.md` at the repo root (also gitignored, loaded automatically), not here or
in the README.

Nothing is compiled. `Runner.app/Contents/MacOS/Runner` is a bash script that runs
`.venv/bin/python -m runner` from this repo (creating `.venv` on first launch). The
Python code serves the UI on http://127.0.0.1:4747 and shows it in a native pywebview
window. Edits to `runner/` apply the next time the app is opened. Edits to `data/` apply
on the next UI poll (every 1.5 s): nothing is cached.

## Layout

```
Runner.app/                   launcher bundle (Info.plist + bash script; logs to state/runner.log)
runner/
  __main__.py                 server thread + pywebview window; --browser, --port
  server.py                   Flask JSON API + index page
  core.py                     project storage, process control, macOS helpers (all the logic)
  templates/index.html        single page
  static/app.js, style.css    vanilla JS, no build step
data/
  projects/<id>/              one folder per tracked project (id = slug of name) — gitignored
    project.json              {name, path, kind, group, description, tags[], commands[],
                               port, url_path, host, type}
    start.sh                  run by Runner (server kind only)
    close.sh                  optional
    assets/logo.<svg|png|…>   optional; auto-copied from the project's favicon/logo on add
  groups/<id>/                one folder per group — gitignored
    group.json                {name, description}
    assets/logo.*             optional
  templates/<type>/           start.sh/close.sh copied into new projects (python-flask, node, blank) — tracked
state/                        gitignored runtime state
  <id>.json                   {pid, pgid, port, started} of a running project
  logs/<id>.log               output of start.sh (+ <id>.previous.log)
```

## Project kinds, commands, groups

- `kind: "server"` (default): has a port, start.sh/close.sh, start/stop/open.
  `kind: "terminal"`: just a folder. No port or scripts; `core.start` refuses it, and
  its status is `terminal`. The card leads with its commands and a Terminal button.
- `commands: [{label, run}]` (any kind): each is a card button that opens Terminal.app
  in the folder (venv activated, PORT exported for servers) and runs `run`
  (`core.open_shell(meta, command)`). The UI edits them as text, one `Label = command`
  per line (`core._clean_commands` accepts either form).
- `group: "<id>"`: setting it to a name or id that doesn't exist creates
  `data/groups/<slug>/` (`core.ensure_group`). Standalone projects render first, with no heading; groups follow as collapsible sections
  (collapsed state lives in the UI's localStorage) with Start all / Stop all for their
  server members. Search matches group names, so searching a group's name shows the
  whole group. Deleting a group ungroups its projects.

## How running works

- The URL is `http://<id>.localhost:<port>` (`core.url`), not plain localhost: cookies
  ignore ports, so Flask apps on one hostname would overwrite each other's `session`
  cookie. macOS and browsers resolve `*.localhost` to loopback. A project whose app
  checks the Host header sets `"host"` in project.json (e.g. `127.0.0.1`).

- Each project has a **fixed, unique port** (auto-assigned from 5100 up; 5000 belongs to
  macOS AirPlay). The port is fixed rather than random so browser storage, which is per
  origin, survives restarts. `core.create/update` refuse duplicate ports, and `core.start`
  refuses if something is already listening on the port.
- `start.sh` runs as `/bin/bash start.sh` with **cwd = the project's path**, in a new
  session/process group (`start_new_session=True`), stdout+stderr to the log. Env:
  `PORT`, `FLASK_RUN_PORT`, `PROJECT_ID`, `PROJECT_DIR`, `RUNNER_PROJECT_DATA` (the
  data/projects/<id> folder), `PYTHONUNBUFFERED=1`, and `PATH` from a login shell
  (`core.login_env`), because apps opened from Finder get a bare PATH.
- start.sh must stay in the foreground (`exec …`). If it forks and exits, Runner still
  tracks the process group, but anything that calls setsid escapes.
- Stop: run `close.sh` (env adds `RUNNER_PID`, `RUNNER_PGID`), then wait 5 s, SIGTERM the
  group, wait 3 s, SIGKILL. This takes Flask's debug reloader child down too.
- Status (`core.status`): `stopped | starting | running | exited | external | stopping | restarting`.
  running = the group is alive and the port accepts connections; external = the port is
  open but Runner didn't start the process (the owner is shown via lsof).
- Projects **keep running when Runner quits**. On relaunch, `state/<id>.json` lets Runner
  reattach, since the group is checked with `killpg(pgid, 0)`.

## API (server.py)

Every non-GET request must carry `X-Runner: 1` (this blocks cross-site form posts), or
you get a 403.
`GET /api/projects` · `POST /api/projects` · `GET|PUT|DELETE /api/projects/<id>` (PUT
also accepts `start_sh`/`close_sh`) · `POST /api/projects/<id>/{start,stop,restart,dismiss,open,shell,finder,data,logo}` ·
`POST /api/projects/<id>/command` `{index}` · `PUT|DELETE /api/groups/<gid>` ·
`POST /api/groups/<gid>/{start,stop,logo}` · `POST /api/stop-all` ·
`GET /api/projects/<id>/log` · `GET /logo/<id>` · `GET /logo/group/<gid>`.
`GET /api/projects` returns `{projects, groups, templates}`.

## Working on it

- Dev loop without the app: `.venv/bin/python -m runner --browser --port 4748`. Use a
  different port if the app is open, otherwise it just opens a window onto the running one.
- Quick backend test: `from runner.server import app; app.test_client()` with the
  `X-Runner` header, as in the smoke test used during development (start two projects,
  poll until running, fetch their ports, stop, check the ports are free).
- Seeing the UI: serve the app on a spare port (`make_server('127.0.0.1', 4748, app)` in
  a background python) and drive it with Playwright from a scratch `.mjs` script
  (`CLAUDE.local.md` says where a copy is installed). The real window is WebKit
  (pywebview), so keep CSS to what Safari supports.
- Pressing a command button opens a real Terminal on the user's screen (e.g. running
  `claude`), so don't trigger `/command` or `/shell` in tests.
- Keep it dependency-light: Flask + pywebview only, and vanilla JS/CSS.
- UI conventions: a card's ✎ (and its name) opens Edit. Secondary buttons sit in a
  right-aligned `.more` block. An open dialog locks page scroll (`body:has(dialog[open])`).
- Adding a project: use the `add-project` skill (`.claude/skills/add-project`).
- Logos are hand-drawn SVGs: a 128×128 tile with `rx="28"`. To preview one, render it
  with AppKit `NSImage` from the venv (pyobjc comes with pywebview).

## Ideas not built yet

An embedded terminal or iTerm support (currently Terminal.app via osascript), starting
groups when Runner launches, ordering projects inside a group (currently by id).

## App icon

Source: `assets/runner-icon.svg`. The built files live in the repo:
`Runner.app/Contents/Resources/icon.icns` (Finder/Dock before launch),
`Runner.app/Contents/Resources/icon.png` (set as the Dock icon at runtime by
`__main__._name_the_app`) and `runner/static/icon.svg` (favicon + header). To rebuild,
render the SVG to PNGs with AppKit's NSImage (qlmanage can't render it), put them in
an `.iconset` (16…512 plus @2x), run `iconutil -c icns`, then `touch Runner.app` so
Finder refreshes.
