"""The Runner's own Flask app: a JSON API over core.py plus the single-page UI."""

from flask import Flask, abort, jsonify, render_template, request, send_file

from . import core

app = Flask(__name__)


@app.before_request
def require_header():
    # Browsers can't send a custom header cross-origin without a CORS preflight
    # (which we never allow), so random web pages can't drive the API.
    if request.method not in ("GET", "HEAD") and request.headers.get("X-Runner") != "1":
        abort(403)


@app.errorhandler(core.ProjectError)
def project_error(e):
    return jsonify(error=str(e)), 400


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/ping")
def ping():
    return jsonify(ok=True, app="runner")


@app.get("/api/projects")
def projects():
    out = []
    for meta in core.list_all():
        meta["status"] = core.status(meta) if not meta.get("broken") else {"state": "stopped"}
        out.append(meta)
    return jsonify(projects=out, groups=core.list_groups(), templates=core.templates())


@app.post("/api/projects")
def create():
    return jsonify(core.create(request.get_json(force=True)))


@app.get("/api/projects/<pid>")
def detail(pid):
    meta = core.load(pid)
    meta["start_sh"] = core.read_script(pid, "start.sh")
    meta["close_sh"] = core.read_script(pid, "close.sh")
    meta["folder"] = str(core.PROJECTS / pid)
    return jsonify(meta)


@app.put("/api/projects/<pid>")
def update(pid):
    body = request.get_json(force=True)
    meta = core.update(pid, body)
    if "start_sh" in body:
        core.write_script(pid, "start.sh", body["start_sh"])
    if "close_sh" in body:
        core.write_script(pid, "close.sh", body["close_sh"])
    return jsonify(meta)


@app.delete("/api/projects/<pid>")
def delete(pid):
    core.delete(pid)
    return jsonify(ok=True)


@app.post("/api/projects/<pid>/<action>")
def action(pid, action):
    meta = core.load(pid)
    if action == "start":
        core.start(pid)
    elif action == "stop":
        core.stop(pid)
    elif action == "restart":
        core.restart(pid)
    elif action == "dismiss":
        core.dismiss(pid)
    elif action == "open":
        core.open_url(core.url(meta))
    elif action == "shell":
        core.open_shell(meta)
    elif action == "command":
        i = int((request.get_json(silent=True) or {}).get("index", -1))
        if not 0 <= i < len(meta["commands"]):
            raise core.ProjectError("no such command")
        core.open_shell(meta, meta["commands"][i]["run"])
    elif action == "finder":
        core.open_finder(meta["path"])
    elif action == "data":
        core.open_finder(str(core.PROJECTS / pid))
    elif action == "logo":
        f = request.files.get("file")
        if not f:
            raise core.ProjectError("no file")
        core.set_logo(pid, f.filename, f.read())
    else:
        abort(404)
    return jsonify(ok=True)


@app.put("/api/groups/<gid>")
def update_group(gid):
    return jsonify(core.save_group(gid, request.get_json(force=True)))


@app.delete("/api/groups/<gid>")
def delete_group(gid):
    core.delete_group(gid)
    return jsonify(ok=True)


@app.post("/api/groups/<gid>/<action>")
def group_action(gid, action):
    members = [p for p in core.group_members(gid) if p.get("kind") == "server"]
    errors = []
    if action == "start":
        for p in members:
            if core.status(p)["state"] in ("stopped", "exited"):
                try:
                    core.start(p["id"])
                except core.ProjectError as e:
                    errors.append(f"{p['name']}: {e}")
    elif action == "stop":
        for p in members:
            core.stop(p["id"])
    elif action == "logo":
        f = request.files.get("file")
        if not f:
            raise core.ProjectError("no file")
        core.set_group_logo(gid, f.filename, f.read())
    else:
        abort(404)
    if errors:
        raise core.ProjectError("\n".join(errors))
    return jsonify(ok=True)


@app.post("/api/stop-all")
def stop_all():
    for pid in core.list_ids():
        core.stop(pid)
    return jsonify(ok=True)


@app.get("/api/projects/<pid>/log")
def log(pid):
    core.project_dir(pid)
    return jsonify(log=core.log_tail(pid))


@app.get("/logo/group/<gid>")
def group_logo(gid):
    p = core.group_logo_path(gid)
    if not p:
        abort(404)
    resp = send_file(p, max_age=0)
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@app.get("/logo/<pid>")
def logo(pid):
    p = core.logo_path(pid)
    if not p:
        abort(404)
    resp = send_file(p, max_age=0)
    resp.headers["Cache-Control"] = "no-cache"
    return resp
