"""Projects and groups on disk, and the processes that run projects.

A project folder (data/projects/<id>/) holds:
    project.json    metadata: name, path, kind, port, tags, group, commands, ...
    start.sh        run with cwd = the project's path; must stay in the foreground
    close.sh        optional; run to stop it (the process group is killed afterwards anyway)
    assets/logo.*   optional logo

kind "server" (default) has a port and start/close scripts; kind "terminal" is just
a folder to open Terminal in. Either can have `commands`, each a Terminal window
opened in the folder running one command (e.g. `claude`).

A group folder (data/groups/<id>/) holds group.json ({name, description}) and an
optional assets/logo.*. Projects join one with "group": "<id>".

Every start.sh runs in its own process group (so Flask's reloader and npm's
children die with it). Its pid is kept in state/<id>.json, which lets a freshly
opened Runner pick up projects started by a previous one.
"""

import json
import os
import re
import shutil
import signal
import socket
import subprocess
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROJECTS = ROOT / "data" / "projects"
GROUPS = ROOT / "data" / "groups"
TEMPLATES = ROOT / "data" / "templates"
STATE = ROOT / "state"
LOGS = STATE / "logs"

PORT_RANGE = range(5100, 6000)   # 5000 is AirPlay on macOS
LOGO_EXTS = (".svg", ".png", ".jpg", ".jpeg", ".webp", ".ico", ".gif")
META_FIELDS = ("name", "path", "kind", "group", "description", "tags", "port", "url_path",
               "host", "type", "commands")
KINDS = ("server", "terminal")


class ProjectError(Exception):
    pass


# --------------------------------------------------------------------------- metadata

def slugify(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "project"


def project_dir(pid):
    d = (PROJECTS / pid).resolve()
    if d.parent != PROJECTS.resolve() or not (d / "project.json").is_file():
        raise ProjectError(f"no such project: {pid}")
    return d


def load(pid):
    d = project_dir(pid)
    meta = json.loads((d / "project.json").read_text())
    meta.setdefault("name", pid)
    meta.setdefault("path", "")
    meta.setdefault("description", "")
    meta.setdefault("tags", [])
    meta.setdefault("url_path", "/")
    meta.setdefault("type", "")
    meta.setdefault("kind", "server")
    meta.setdefault("group", "")
    meta.setdefault("commands", [])
    meta["id"] = pid
    meta["logo"] = logo_path(pid) is not None
    return meta


def list_ids():
    if not PROJECTS.is_dir():
        return []
    return sorted(p.name for p in PROJECTS.iterdir() if (p / "project.json").is_file())


def list_all():
    out = []
    for pid in list_ids():
        try:
            out.append(load(pid))
        except (ValueError, OSError) as e:          # broken json: show it rather than hide it
            out.append({"id": pid, "name": pid, "path": "", "tags": [], "port": None,
                        "description": f"project.json unreadable: {e}", "broken": True})
    return out


def _clean(fields):
    meta = {k: fields[k] for k in META_FIELDS if k in fields}
    if "name" in meta:
        meta["name"] = str(meta["name"]).strip()
        if not meta["name"]:
            raise ProjectError("name is required")
    if "path" in meta:
        meta["path"] = os.path.expanduser(str(meta["path"]).strip())
        if not os.path.isdir(meta["path"]):
            raise ProjectError(f"folder does not exist: {meta['path']}")
    if "tags" in meta:
        tags = meta["tags"]
        if isinstance(tags, str):
            tags = tags.split(",")
        meta["tags"] = sorted({t.strip().lower() for t in tags if t.strip()})
    if "port" in meta:
        try:
            meta["port"] = int(meta["port"])
        except (TypeError, ValueError):
            raise ProjectError("port must be a number")
        if not 1024 <= meta["port"] <= 65535:
            raise ProjectError("port must be between 1024 and 65535")
    if "url_path" in meta:
        meta["url_path"] = "/" + str(meta["url_path"] or "").lstrip("/")
    if "kind" in meta and meta["kind"] not in KINDS:
        raise ProjectError(f"kind must be one of {', '.join(KINDS)}")
    if "group" in meta:
        meta["group"] = ensure_group(meta["group"]) if str(meta["group"] or "").strip() else ""
    if "commands" in meta:
        meta["commands"] = _clean_commands(meta["commands"])
    return meta


def _clean_commands(commands):
    """[{label, run}], also accepted as text: one "Label = command" per line."""
    if isinstance(commands, str):
        items = []
        for line in commands.splitlines():
            if not line.strip():
                continue
            label, sep, run = line.partition("=")
            if not sep:
                label, run = line, line
            items.append({"label": label.strip(), "run": run.strip()})
        commands = items
    out = []
    for c in commands or []:
        run = str(c.get("run", "")).strip()
        if run:
            out.append({"label": str(c.get("label") or run).strip(), "run": run})
    return out


def _check_port_unique(port, pid=None):
    for other in list_all():
        if other["id"] != pid and other.get("port") == port:
            raise ProjectError(f"port {port} is already used by {other['name']}")


def next_free_port():
    taken = {p.get("port") for p in list_all()}
    for port in PORT_RANGE:
        if port not in taken and not port_open(port):
            return port
    raise ProjectError("no free port left in range")


def templates():
    if not TEMPLATES.is_dir():
        return []
    return sorted(p.name for p in TEMPLATES.iterdir() if p.is_dir())


def create(fields):
    meta = _clean(fields)
    if "name" not in meta or "path" not in meta:
        raise ProjectError("name and path are required")
    meta.setdefault("kind", "server")
    if meta["kind"] == "terminal":
        for k in ("port", "url_path", "host", "type"):
            meta.pop(k, None)
    else:
        meta.setdefault("port", next_free_port())
        _check_port_unique(meta["port"])
        meta.setdefault("url_path", "/")
    meta.setdefault("tags", [])
    meta.setdefault("description", "")

    pid = base = slugify(meta["name"])
    n = 2
    while (PROJECTS / pid).exists():
        pid, n = f"{base}-{n}", n + 1
    d = PROJECTS / pid
    (d / "assets").mkdir(parents=True)

    template = TEMPLATES / (meta.get("type") or "python-flask")
    for script in ("start.sh", "close.sh"):
        if meta["kind"] == "server" and (template / script).is_file():
            shutil.copy(template / script, d / script)
            (d / script).chmod(0o755)
    _write_meta(pid, meta)

    found = _find_logo_in(meta["path"])
    if found:
        shutil.copy(found, d / "assets" / ("logo" + found.suffix.lower()))
    return load(pid)


def update(pid, fields):
    meta = json.loads((project_dir(pid) / "project.json").read_text())
    new = _clean(fields)
    if new.get("kind", meta.get("kind", "server")) == "server":
        if "port" not in new and not meta.get("port"):
            new["port"] = next_free_port()
        if "port" in new:
            _check_port_unique(new["port"], pid)
    meta.update(new)
    _write_meta(pid, meta)
    return load(pid)


def _write_meta(pid, meta):
    meta = {k: meta[k] for k in META_FIELDS if k in meta} | {
        k: v for k, v in meta.items() if k not in META_FIELDS and k not in ("id", "logo")}
    (PROJECTS / pid / "project.json").write_text(json.dumps(meta, indent=2) + "\n")


def delete(pid):
    d = project_dir(pid)
    stop(pid, wait=True)
    shutil.rmtree(d)
    _state_path(pid).unlink(missing_ok=True)


# --------------------------------------------------------------------------- groups

def group_ids():
    if not GROUPS.is_dir():
        return []
    return sorted(p.name for p in GROUPS.iterdir() if (p / "group.json").is_file())


def load_group(gid):
    d = GROUPS / gid
    try:
        meta = json.loads((d / "group.json").read_text())
    except (OSError, ValueError):
        meta = {}
    meta.setdefault("name", gid)
    meta.setdefault("description", "")
    meta["id"] = gid
    meta["logo"] = _logo_in(d / "assets") is not None
    return meta


def list_groups():
    """Every group with a folder, plus any a project names without one."""
    ids = set(group_ids()) | {p.get("group") for p in list_all() if p.get("group")}
    return [load_group(g) for g in sorted(ids)]


def _group_dir(gid):
    d = (GROUPS / gid).resolve()
    if d.parent != GROUPS.resolve() or not gid:
        raise ProjectError(f"bad group id: {gid}")
    return d


def ensure_group(name_or_id):
    """The id of the group with this id or name, creating it if there's none."""
    value = str(name_or_id).strip()
    for g in list_groups():
        if value in (g["id"], g["name"]) or value.lower() == g["name"].lower():
            if not (GROUPS / g["id"] / "group.json").is_file():
                save_group(g["id"], {"name": g["name"]})
            return g["id"]
    gid = slugify(value)
    if not (GROUPS / gid / "group.json").is_file():
        save_group(gid, {"name": value})
    return gid


def save_group(gid, fields):
    d = _group_dir(gid)
    (d / "assets").mkdir(parents=True, exist_ok=True)
    try:
        meta = json.loads((d / "group.json").read_text())
    except (OSError, ValueError):
        meta = {}
    for k in ("name", "description"):
        if k in fields:
            meta[k] = str(fields[k]).strip()
    if not meta.get("name"):
        raise ProjectError("group name is required")
    (d / "group.json").write_text(json.dumps(meta, indent=2) + "\n")
    return load_group(gid)


def delete_group(gid):
    """Remove the group; its projects stay, ungrouped."""
    for p in list_all():
        if p.get("group") == gid:
            meta = json.loads((PROJECTS / p["id"] / "project.json").read_text())
            meta.pop("group", None)
            _write_meta(p["id"], meta)
    d = _group_dir(gid)
    if d.is_dir():
        shutil.rmtree(d)


def group_members(gid):
    return [p for p in list_all() if p.get("group") == gid]


def group_logo_path(gid):
    return _logo_in(_group_dir(gid) / "assets")


def set_group_logo(gid, filename, data):
    save_group(gid, {})
    _save_logo(_group_dir(gid) / "assets", filename, data)


def read_script(pid, name):
    p = project_dir(pid) / name
    return p.read_text() if p.is_file() else ""


def write_script(pid, name, text):
    p = project_dir(pid) / name
    if not text.strip():
        if name == "close.sh":
            p.unlink(missing_ok=True)
            return
        raise ProjectError("start.sh cannot be empty")
    p.write_text(text.replace("\r\n", "\n"))
    p.chmod(0o755)


def _logo_in(assets):
    for ext in LOGO_EXTS:
        if (assets / ("logo" + ext)).is_file():
            return assets / ("logo" + ext)
    return None


def logo_path(pid):
    return _logo_in(PROJECTS / pid / "assets")


def set_logo(pid, filename, data):
    _save_logo(project_dir(pid) / "assets", filename, data)


def _save_logo(assets, filename, data):
    ext = Path(filename).suffix.lower()
    if ext not in LOGO_EXTS:
        raise ProjectError(f"logo must be one of {', '.join(LOGO_EXTS)}")
    assets.mkdir(parents=True, exist_ok=True)
    for old in assets.glob("logo.*"):
        old.unlink()
    (assets / ("logo" + ext)).write_bytes(data)


def _find_logo_in(path):
    """A favicon or logo inside the project, if there's an obvious one."""
    skip = {".venv", "venv", "node_modules", ".git", "__pycache__", "dist", "build"}
    best = None
    for dirpath, dirnames, filenames in os.walk(path):
        dirnames[:] = [d for d in dirnames if d not in skip]
        if dirpath[len(path):].count(os.sep) >= 3:
            dirnames[:] = []
        for f in filenames:
            stem, ext = os.path.splitext(f.lower())
            if ext in LOGO_EXTS and stem in ("logo", "favicon", "icon", "apple-touch-icon"):
                cand = Path(dirpath) / f
                # prefer svg, then logo over favicon
                rank = (ext != ".svg", stem != "logo")
                if best is None or rank < best[0]:
                    best = (rank, cand)
    return best[1] if best else None


# --------------------------------------------------------------------------- processes

_children = {}     # pid -> Popen, for processes this Runner started
_busy = {}         # pid -> "stopping" / "restarting"
_lock = threading.Lock()
_login_env = None


def login_env():
    """PATH etc. from a login shell: an app opened from Finder gets a bare PATH,
    which would hide Homebrew, pyenv, nvm, ..."""
    global _login_env
    if _login_env is None:
        env = dict(os.environ)
        shell = os.environ.get("SHELL", "/bin/zsh")
        try:
            out = subprocess.run([shell, "-ilc", "printf '\\n__RUNNER__%s__RUNNER__' \"$PATH\""],
                                 capture_output=True, text=True, timeout=8,
                                 stdin=subprocess.DEVNULL).stdout
            m = re.search(r"__RUNNER__(.*?)__RUNNER__", out)
            if m and m.group(1):
                env["PATH"] = m.group(1)
        except (OSError, subprocess.SubprocessError):
            pass
        _login_env = env
    return dict(_login_env)


def _state_path(pid):
    return STATE / f"{pid}.json"


def _read_state(pid):
    try:
        return json.loads(_state_path(pid).read_text())
    except (OSError, ValueError):
        return None


def _group_alive(pgid):
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _alive(pid, st):
    child = _children.get(pid)
    if child is not None:
        child.poll()        # reap it, or its zombie keeps the group "alive"
    # the leader may have exited while its group still holds children (a reloader's server)
    return _group_alive(st["pgid"])


def port_open(port):
    for family, host in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
        with socket.socket(family, socket.SOCK_STREAM) as s:
            s.settimeout(0.15)
            try:
                if s.connect_ex((host, port)) == 0:
                    return True
            except OSError:
                pass
    return False


def port_owner(port):
    try:
        out = subprocess.run(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-Fpc"],
                             capture_output=True, text=True, timeout=3).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    pid = cmd = None
    for line in out.splitlines():
        if line.startswith("p") and pid is None:
            pid = line[1:]
        elif line.startswith("c") and cmd is None:
            cmd = line[1:]
    return f"{cmd} (pid {pid})" if pid else None


def url(meta):
    # <id>.localhost rather than localhost: cookies ignore the port, so every Flask app
    # on plain localhost would share (and keep clobbering) one "session" cookie.
    host = meta.get("host") or f"{meta['id']}.localhost"
    return f"http://{host}:{meta['port']}{meta.get('url_path', '/')}"


def status(meta):
    """stopped | starting | running | exited | external | stopping | restarting | terminal"""
    pid = meta["id"]
    if meta.get("kind") == "terminal":
        return {"state": "terminal", "url": None}
    port = meta.get("port")
    out = {"state": "stopped", "url": url(meta) if port else None}
    if not port:
        return out
    open_ = port_open(port)
    st = _read_state(pid)
    busy = _busy.get(pid)
    if st and _alive(pid, st):
        out.update(state=busy or ("running" if open_ else "starting"),
                   pid=st["pid"], started=st["started"])
    elif st:
        child = _children.get(pid)
        code = child.poll() if child else None
        out.update(state=busy or "exited", exit_code=code, started=st["started"])
    elif busy:
        out["state"] = busy
    elif open_:
        out.update(state="external", owner=port_owner(port))
    return out


def start(pid):
    meta = load(pid)
    with _lock:
        st = _read_state(pid)
        if st and _alive(pid, st):
            raise ProjectError(f"{meta['name']} is already running")
        if meta.get("kind") == "terminal":
            raise ProjectError(f"{meta['name']} is a terminal project: nothing to start")
        if not os.path.isdir(meta["path"]):
            raise ProjectError(f"folder does not exist: {meta['path']}")
        script = PROJECTS / pid / "start.sh"
        if not script.is_file():
            raise ProjectError("start.sh is missing")
        port = meta["port"]
        if port_open(port):
            owner = port_owner(port)
            raise ProjectError(f"port {port} is already in use" + (f" by {owner}" if owner else ""))

        LOGS.mkdir(parents=True, exist_ok=True)
        log = LOGS / f"{pid}.log"
        if log.exists():
            log.replace(LOGS / f"{pid}.previous.log")
        env = login_env() | {
            "PORT": str(port),
            "FLASK_RUN_PORT": str(port),
            "PROJECT_ID": pid,
            "PROJECT_DIR": meta["path"],
            "RUNNER_PROJECT_DATA": str(PROJECTS / pid),
            "PYTHONUNBUFFERED": "1",
        }
        env.pop("VIRTUAL_ENV", None)
        with open(log, "ab") as fh:
            fh.write(f"--- {time.strftime('%Y-%m-%d %H:%M:%S')} starting on port {port}\n".encode())
            fh.flush()
            proc = subprocess.Popen(["/bin/bash", str(script)], cwd=meta["path"], env=env,
                                    stdin=subprocess.DEVNULL, stdout=fh, stderr=subprocess.STDOUT,
                                    start_new_session=True)
        _children[pid] = proc
        STATE.mkdir(exist_ok=True)
        _state_path(pid).write_text(json.dumps(
            {"pid": proc.pid, "pgid": proc.pid, "port": port, "started": time.time()}))


def stop(pid, wait=False):
    """Run close.sh (if any), then make sure the whole process group is gone."""
    def work():
        try:
            _stop_now(pid)
        finally:
            _busy.pop(pid, None)
    st = _read_state(pid)
    if not st:
        return
    _busy[pid] = "stopping"
    if wait:
        work()
    else:
        threading.Thread(target=work, daemon=True).start()


def _stop_now(pid):
    st = _read_state(pid)
    if not st:
        return
    pgid = st["pgid"]
    close = PROJECTS / pid / "close.sh"
    if close.is_file() and _alive(pid, st):
        meta = load(pid)
        env = login_env() | {"PORT": str(st["port"]), "RUNNER_PID": str(st["pid"]),
                             "RUNNER_PGID": str(pgid), "PROJECT_ID": pid,
                             "PROJECT_DIR": meta["path"], "RUNNER_PROJECT_DATA": str(PROJECTS / pid)}
        with open(LOGS / f"{pid}.log", "ab") as fh:
            fh.write(b"--- running close.sh\n")
            fh.flush()
            try:
                subprocess.run(["/bin/bash", str(close)], cwd=meta["path"] or None, env=env,
                               stdin=subprocess.DEVNULL, stdout=fh, stderr=subprocess.STDOUT,
                               timeout=20)
            except subprocess.TimeoutExpired:
                fh.write(b"--- close.sh timed out\n")
    for sig, grace in ((None, 5), (signal.SIGTERM, 3), (signal.SIGKILL, 2)):
        if sig is not None:
            try:
                os.killpg(pgid, sig)
            except ProcessLookupError:
                pass
        deadline = time.time() + grace
        while time.time() < deadline and _alive(pid, st):
            time.sleep(0.1)
        if not _alive(pid, st):
            break
    child = _children.pop(pid, None)
    if child:
        child.poll()
    _state_path(pid).unlink(missing_ok=True)
    try:
        with open(LOGS / f"{pid}.log", "ab") as fh:
            fh.write(f"--- stopped {time.strftime('%H:%M:%S')}\n".encode())
    except OSError:
        pass


def restart(pid):
    def work():
        try:
            _stop_now(pid)
            deadline = time.time() + 5          # let the port be released
            while time.time() < deadline and port_open(load(pid)["port"]):
                time.sleep(0.1)
        finally:
            _busy.pop(pid, None)
        try:
            start(pid)
        except ProjectError as e:
            with open(LOGS / f"{pid}.log", "a") as fh:
                fh.write(f"--- restart failed: {e}\n")
    _busy[pid] = "restarting"
    threading.Thread(target=work, daemon=True).start()


def dismiss(pid):
    """Forget an exited process (clears the 'exited' state)."""
    st = _read_state(pid)
    if st and not _alive(pid, st):
        _state_path(pid).unlink(missing_ok=True)
        _children.pop(pid, None)


_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def log_tail(pid, max_bytes=60_000):
    p = LOGS / f"{pid}.log"
    if not p.is_file():
        return ""
    with open(p, "rb") as fh:
        fh.seek(0, 2)
        size = fh.tell()
        fh.seek(max(0, size - max_bytes))
        return _ANSI.sub("", fh.read().decode("utf-8", "replace"))


# --------------------------------------------------------------------------- macOS helpers

def _applescript_str(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def open_url(u):
    subprocess.Popen(["open", u])


def open_finder(path):
    subprocess.Popen(["open", path])


def open_shell(meta, command=None):
    """A Terminal window in the project folder, with its venv activated if it has one,
    then optionally running `command` (one of the project's preconfigured commands)."""
    path = meta["path"]
    q = "'" + path.replace("'", "'\\''") + "'"
    cmd = f"cd {q}"
    if os.path.isfile(os.path.join(path, ".venv", "bin", "activate")):
        cmd += " && source .venv/bin/activate"
    if meta.get("port"):
        cmd += f" && export PORT={meta['port']}"
    if command:
        cmd += f" && {command}"
    script = (f'tell application "Terminal"\n  do script {_applescript_str(cmd)}\n'
              f'  activate\nend tell')
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if r.returncode != 0:                       # no automation permission: plain window
        subprocess.Popen(["open", "-a", "Terminal", path])
