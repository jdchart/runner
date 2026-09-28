---
name: add-project
description: Register a local project with Runner — a dev server (Flask/Python, Node/Vite, …) or a terminal-only folder with preconfigured commands such as claude — by creating data/projects/<id>/ (project.json, start.sh, close.sh, logo), optionally in a group, and checking that servers actually start on their assigned port. Use when asked to add, track, register or group projects/repos in Runner.
---

# Add a project to Runner

Goal: `data/projects/<id>/` exists, the project starts from Runner on its own port
alongside every other project, and it shows up in the UI with a sensible name,
description, tags and logo. Read `.claude/CLAUDE.md` (and `CLAUDE.local.md`, if present) first if you haven't this session.

## 0. Decide the shape

- One repo can be **several projects**: e.g. a workspace with a runnable app in one
  subfolder and plain folders you only `cd` into. Make one Runner project per folder the
  user wants to act on, and put them in a **group** (`"group": "<Name>"`; it's created
  if missing, and you can set its description with `core.save_group(gid, {...})`).
- **kind "server"**: something with a dev server → steps 1–4 below.
- **kind "terminal"**: a folder to open a shell in, usually to run `claude`. No port and
  no scripts. Give it `"commands": [{"label": "Claude", "run": "claude"}]` (or whatever
  the user runs there), and skip to the logo and report steps.
- Servers can have commands too (e.g. Claude in the app folder).

## 1. Inspect the project

Given a path (for example `~/code/foo`), find out:

- **Kind and entry point**: `app.py`/`wsgi.py`/`manage.py`/`pyproject.toml` (Python),
  `package.json` scripts (Node), README "Running" section, CLAUDE.md.
- **How it picks its port**. This matters most. `grep -rn "app.run\|PORT\|port" --include=*.py`
  (skip `.venv`), or look at the `dev` script / framework in package.json.
  - Reads `os.environ["PORT"]` → run it directly.
  - Hard-coded `app.run(port=5000)` → use the flask CLI: `flask --app <module> run --port "$PORT"`.
    Find the module/factory it would need (`--app app`, `--app "pkg:create_app()"`).
  - Vite → `npm run dev -- --port "$PORT" --strictPort`; Next → `-p "$PORT"`;
    Express etc. usually read `PORT`.
  - Never edit the project itself to make it fit. Adapt start.sh instead. If there's
    truly no way to pass a port, say so and ask.
- **Environment**: `.venv/` present? `requirements*.txt`? `node_modules/`? Any env
  vars it needs (check README, `.env.example`)? Put those in start.sh.
- **Non-root URL** (e.g. the app lives at `/app`) → `url_path`.
- **Name, one-line description, tags**: from the README title and intro. Tags are
  lowercase; reuse existing ones where they fit (`grep -h '"tags"' -A5 data/projects/*/project.json`).
  Include the stack (`flask`, `node`, …) plus one or two topic tags.

## 2. Create it

Use core.create: it picks a free unique port, slugifies the id, copies the template
scripts and auto-copies a favicon/logo from the project:

```sh
.venv/bin/python - <<'EOF'
from runner import core
print(core.create({
    "name": "Foo", "path": "~/code/foo",
    "description": "One line from the README.", "tags": "flask, tools",
    "type": "python-flask",          # or "node", "blank" (see data/templates/)
    # "port": 5123, "url_path": "/", # only if there's a reason
    # "group": "Foo",                # joins/creates data/groups/foo/
    # "commands": [{"label": "Claude", "run": "claude"}],
    # "kind": "terminal",            # folder only: no port, no scripts
}))
EOF
```

(If Runner's app is open, `POST /api/projects` with header `X-Runner: 1` does the same.)

## 3. Adjust start.sh

Edit `data/projects/<id>/start.sh` to match what you found. Rules:

- It runs with cwd = the project folder, env has `PORT`, `PROJECT_DIR`, `PROJECT_ID`,
  `RUNNER_PROJECT_DATA`, and a login-shell `PATH`.
- It must **stay in the foreground**: end with `exec <server command>`. No `&`,
  `nohup`, `setsid`, or daemonising flags.
- Call the venv's binaries directly (`.venv/bin/python`, `.venv/bin/flask`) rather than
  `source activate`.
- Keep the "create .venv / npm install if missing" block from the template when it
  applies.
- Add a short comment for anything unusual (why the flask CLI, why an env var).

close.sh can usually stay as the template. Add real logic only when the project needs
a graceful shutdown step, such as `docker compose down`.

Logo: if none was found, or the one found is a framework default (the Svelte, Vite or
React logo), look for an image the app uses in its header. If there isn't one, draw a
simple SVG in the house style: 128×128, `rx="28"` rounded tile, flat shapes, two or
three colours. Leaving it empty is also fine; the UI falls back to a coloured initial. Put it at `assets/logo.<ext>` (svg, png, jpg,
webp, ico, gif). Only one `logo.*` file.

## 4. Verify it runs

Start it through core (never on the default port by hand), wait for "running", fetch
the URL, check the log, and stop it:

```sh
.venv/bin/python - <<'EOF'
import time, urllib.request
from runner import core
pid = "foo"
core.start(pid)
meta = core.load(pid)
for _ in range(60):
    s = core.status(meta)["state"]
    if s in ("running", "exited"): break
    time.sleep(0.5)
print("state:", s)
if s == "running":
    print(urllib.request.urlopen(core.url(meta)).status)
print(core.log_tail(pid)[-1500:])
core.stop(pid, wait=True)
print("port free:", not core.port_open(meta["port"]))
EOF
```

If Runner's app is open, it already sees the project, and the check above behaves the
same (the state file is shared). If it's `exited` or stuck on `starting`, read the log,
fix start.sh, and repeat. Common causes: wrong entry point, missing deps, and the app
ignoring `$PORT` (it's listening somewhere else: `lsof -nP -iTCP -sTCP:LISTEN | grep python`).
A **403 on a running app** usually means it only accepts `Host: localhost`/`127.0.0.1`
(Runner addresses projects as `<id>.localhost` to keep their cookies apart): set
`"host": "127.0.0.1"` via `core.update(pid, {"host": "127.0.0.1"})` rather than touching the app.

## 5. Report

Tell the user the id, port, URL, tags, and anything non-obvious you put in start.sh.
If the project had a quirk worth remembering (a hard-coded port, a required env var),
add a line under "Registered projects: quirks" in `CLAUDE.local.md` at the repo root (gitignored; create it if missing). Never put project-specific notes in `.claude/CLAUDE.md` or the README: those are shared.
