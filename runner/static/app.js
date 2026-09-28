// Runner UI: polls /api/projects and renders groups of cards. No build step.
const $ = (s, el = document) => el.querySelector(s);
const state = { projects: [], groups: [], templates: [], tags: new Set(), editing: null, editingGroup: null, logFor: null };
const saved = (() => { try { return JSON.parse(localStorage.getItem("runner-ui") || "{}"); } catch { return {}; } })();
state.tags = new Set(saved.tags || []);
state.collapsed = new Set(saved.collapsed || []);
$("#search").value = saved.search || "";
$("#only-running").checked = !!saved.onlyRunning;

function remember() {
  try {
    localStorage.setItem("runner-ui", JSON.stringify({
      tags: [...state.tags], collapsed: [...state.collapsed],
      search: $("#search").value, onlyRunning: $("#only-running").checked }));
  } catch {}
}

async function api(path, opts = {}) {
  const init = { method: opts.method || "GET", headers: { "X-Runner": "1" } };
  if (opts.body instanceof FormData) init.body = opts.body;
  else if (opts.body !== undefined) {
    init.body = JSON.stringify(opts.body);
    init.headers["Content-Type"] = "application/json";
  }
  const r = await fetch(path, init);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || `${r.status} ${r.statusText}`);
  return data;
}

const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function hue(s) { let h = 0; for (const c of s) h = (h * 31 + c.charCodeAt(0)) % 360; return h; }

function ago(t) {
  const s = Math.max(0, Date.now() / 1000 - t);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ${Math.floor(s % 3600 / 60)} min`;
  return `${Math.floor(s / 86400)} d`;
}

const LIVE = ["running", "starting", "stopping", "restarting"];
const tildify = p => (p || "").replace(/^\/Users\/[^/]+/, "~");

function logoHtml(src, name, key, cls = "logo") {
  return src
    ? `<img class="${cls}" src="${src}" alt="">`
    : `<div class="${cls}" style="background:hsl(${hue(key)} 55% 48%)">${esc((name || "?").slice(0, 1).toUpperCase())}</div>`;
}

function statusLine(p) {
  const st = p.status || {};
  const link = st.url ? `<a href="#" data-act="open">${esc(st.url.replace(/\/$/, ""))}</a>` : "";
  switch (st.state) {
    case "terminal": return `<span class="muted">Terminal · ${esc(tildify(p.path))}</span>`;
    case "running": return `Running ${link} <span class="muted">· ${ago(st.started)}</span>`;
    case "starting": return `Starting… <span class="muted">port ${p.port}</span>`;
    case "stopping": return "Stopping…";
    case "restarting": return "Restarting…";
    case "exited": return `Exited${st.exit_code != null ? ` (code ${st.exit_code})` : ""} — <a href="#" data-act="log">see log</a>`;
    case "external": return `Port ${p.port} in use outside Runner${st.owner ? ` by ${esc(st.owner)}` : ""} ${link}`;
    default: return `<span class="muted">Stopped · port ${p.port ?? "?"}</span>`;
  }
}

function commandButtons(p, primary) {
  return (p.commands || []).map((c, i) =>
    `<button data-act="command" data-index="${i}" class="${primary && i === 0 ? "primary" : ""}" title="Open Terminal here and run: ${esc(c.run)}">❯ ${esc(c.label)}</button>`).join("");
}

function card(p) {
  const s = p.status?.state || "stopped";
  const live = LIVE.includes(s);
  const terminal = p.kind === "terminal";
  const logo = logoHtml(p.logo ? `/logo/${encodeURIComponent(p.id)}?v=${p._v || 0}` : null, p.name, p.id);
  const actions = terminal
    ? `${commandButtons(p, true)}
       <button data-act="shell" class="${p.commands?.length ? "" : "primary"}" title="Open a Terminal in the folder">Terminal</button>
       <span class="more"><button data-act="finder" class="ghost" title="Show in Finder">Folder</button></span>`
    : `${live
        ? `<button data-act="stop" ${s === "stopping" || s === "restarting" ? "disabled" : ""}>■ Stop</button>
           <button data-act="restart" ${s !== "running" && s !== "starting" ? "disabled" : ""}>↻ Restart</button>`
        : `<button data-act="start" class="primary" ${p.broken ? "disabled" : ""}>▶ Start</button>`}
       <button data-act="open" ${s === "running" || s === "external" ? "" : "disabled"}>Open ↗</button>
       ${commandButtons(p, false)}
       <span class="more">
         <button data-act="log" class="ghost" title="Log">Log</button>
         <button data-act="shell" class="ghost" title="Open a Terminal in the project (venv activated)">Shell</button>
         <button data-act="finder" class="ghost" title="Show in Finder">Folder</button>
       </span>`;
  return `<article class="card s-${s}" data-id="${esc(p.id)}">
    <div class="top">${logo}
      <div class="title">
        <div class="name" data-act="edit" title="Edit">${esc(p.name)}</div>
        ${p.description ? `<div class="desc">${esc(p.description)}</div>` : ""}
        ${terminal ? "" : `<div class="path" title="${esc(p.path)}">${esc(tildify(p.path))}</div>`}
      </div>
      <button class="edit-btn ghost" data-act="edit" title="Edit ${esc(p.name)}">✎</button>
    </div>
    ${p.tags?.length ? `<div class="tags">${p.tags.map(t => `<span class="tag${state.tags.has(t) ? " on" : ""}" data-tag="${esc(t)}">${esc(t)}</span>`).join("")}</div>` : ""}
    <div class="status"><span class="dot"></span><span>${statusLine(p)}</span></div>
    <div class="actions">${actions}</div>
  </article>`;
}

function groupOf(p) { return state.groups.find(g => g.id === p.group); }

function matches(p) {
  const q = $("#search").value.trim().toLowerCase();
  if ($("#only-running").checked && !LIVE.includes(p.status?.state)) return false;
  for (const t of state.tags) if (!p.tags?.includes(t)) return false;
  if (!q) return true;
  const g = groupOf(p);
  const hay = [p.name, p.description, p.path, p.id, ...(p.tags || []), String(p.port ?? ""),
               g?.name, g?.id, ...(p.commands || []).map(c => c.label)].join(" ").toLowerCase();
  return q.split(/\s+/).every(w => hay.includes(w));
}

function groupSection(g, members) {
  const servers = members.filter(p => p.kind !== "terminal");
  const running = servers.filter(p => p.status?.state === "running").length;
  const anyLive = servers.some(p => LIVE.includes(p.status?.state));
  const anyStopped = servers.some(p => ["stopped", "exited"].includes(p.status?.state));
  const collapsed = state.collapsed.has(g.id) && !$("#search").value.trim();
  const logo = logoHtml(g.logo ? `/logo/group/${encodeURIComponent(g.id)}?v=${g._v || 0}` : null, g.name, g.id, "logo small");
  return `<section class="group${collapsed ? " collapsed" : ""}" data-group="${esc(g.id)}">
    <div class="group-head">
      <button class="chev ghost" data-gact="toggle" title="Collapse">▾</button>
      ${logo}
      <div class="group-title" data-gact="toggle">
        <span class="group-name">${esc(g.name)}</span>
        ${g.description ? `<span class="muted">${esc(g.description)}</span>` : ""}
      </div>
      <span class="muted small">${members.length} project${members.length === 1 ? "" : "s"}${servers.length ? ` · ${running}/${servers.length} running` : ""}</span>
      ${servers.length ? `<button data-gact="start" ${anyStopped ? "" : "disabled"}>▶ Start all</button>
                          <button data-gact="stop" ${anyLive ? "" : "disabled"}>■ Stop all</button>` : ""}
      <button data-gact="edit" class="ghost">Edit</button>
    </div>
    <div class="grid">${members.map(card).join("")}</div>
  </section>`;
}

function render() {
  const counts = {};
  for (const p of state.projects) for (const t of p.tags || []) counts[t] = (counts[t] || 0) + 1;
  for (const t of [...state.tags]) if (!counts[t]) state.tags.delete(t);
  $("#tags").innerHTML = Object.keys(counts).sort().map(t =>
    `<button class="tag${state.tags.has(t) ? " on" : ""}" data-tag="${esc(t)}">${esc(t)}<span class="n">${counts[t]}</span></button>`).join("");

  const shown = state.projects.filter(matches);
  const html = [];
  const loose = shown.filter(p => !groupOf(p));        // standalone projects first, unlabelled
  if (loose.length) html.push(`<section class="loose"><div class="grid">${loose.map(card).join("")}</div></section>`);
  for (const g of state.groups) {
    const members = shown.filter(p => p.group === g.id);
    if (members.length) html.push(groupSection(g, members));
  }
  $("#sections").innerHTML = html.join("");

  const servers = state.projects.filter(p => p.kind !== "terminal");
  const running = servers.filter(p => p.status?.state === "running").length;
  $("#summary").textContent = `${running} running · ${state.projects.length} projects`;
  $("#stop-all").disabled = !state.projects.some(p => LIVE.includes(p.status?.state));
  const empty = $("#empty");
  empty.hidden = shown.length > 0;
  empty.textContent = state.projects.length ? "Nothing matches." : "No projects yet — add one with “＋ Add project”.";
}

async function refresh() {
  try {
    const data = await api("/api/projects");
    const v = new Map(state.projects.map(p => [p.id, p._v]));
    const gv = new Map(state.groups.map(g => [g.id, g._v]));
    state.projects = data.projects.map(p => ({ ...p, _v: v.get(p.id) || 0 }));
    state.groups = data.groups.map(g => ({ ...g, _v: gv.get(g.id) || 0 }));
    state.templates = data.templates;
    render();
  } catch (e) { console.error(e); }
}

// ---------------------------------------------------------------- actions
$("#sections").addEventListener("click", async e => {
  const tag = e.target.closest("[data-tag]");
  if (tag) { toggleTag(tag.dataset.tag); return; }

  const gbtn = e.target.closest("[data-gact]");
  if (gbtn) {
    const gid = gbtn.closest(".group").dataset.group;
    const act = gbtn.dataset.gact;
    if (act === "toggle") {
      state.collapsed.has(gid) ? state.collapsed.delete(gid) : state.collapsed.add(gid);
      remember(); render(); return;
    }
    if (act === "edit") return openGroupEdit(gid);
    gbtn.disabled = true;
    try { await api(`/api/groups/${gid}/${act}`, { method: "POST" }); }
    catch (err) { alert(err.message); }
    refresh();
    return;
  }

  const btn = e.target.closest("[data-act]");
  if (!btn) return;
  e.preventDefault();
  const id = btn.closest(".card").dataset.id;
  const act = btn.dataset.act;
  if (act === "edit") return openEdit(id);
  if (act === "log") return openLog(id);
  if (act === "command") {
    return api(`/api/projects/${id}/command`, { method: "POST", body: { index: +btn.dataset.index } }).catch(err => alert(err.message));
  }
  if (act === "open" || act === "shell" || act === "finder") return api(`/api/projects/${id}/${act}`, { method: "POST" }).catch(err => alert(err.message));
  btn.disabled = true;
  try {
    await api(`/api/projects/${id}/${act}`, { method: "POST" });
  } catch (err) {
    alert(err.message);
  }
  refresh();
});

function toggleTag(t) {
  state.tags.has(t) ? state.tags.delete(t) : state.tags.add(t);
  remember(); render();
}
$("#tags").addEventListener("click", e => { const t = e.target.closest("[data-tag]"); if (t) toggleTag(t.dataset.tag); });
$("#search").addEventListener("input", () => { remember(); render(); });
$("#only-running").addEventListener("change", () => { remember(); render(); });
$("#stop-all").addEventListener("click", async () => {
  if (!confirm("Stop every running project?")) return;
  await api("/api/stop-all", { method: "POST" }).catch(err => alert(err.message));
  refresh();
});
document.addEventListener("keydown", e => {
  if ((e.metaKey || e.ctrlKey) && e.key === "f") { e.preventDefault(); $("#search").focus(); $("#search").select(); }
  if (e.key === "Escape" && document.activeElement === $("#search")) { $("#search").value = ""; remember(); render(); }
});

// ---------------------------------------------------------------- add / edit project
const dlg = $("#edit"), form = $("#edit-form");

function syncKind() { dlg.classList.toggle("terminal", form.kind.value === "terminal"); }
form.kind.addEventListener("change", syncKind);

function fillGroupList() {
  $("#group-list").innerHTML = state.groups.map(g => `<option value="${esc(g.name)}">`).join("");
}
const commandsText = cmds => (cmds || []).map(c => `${c.label} = ${c.run}`).join("\n");

$("#add").addEventListener("click", () => {
  state.editing = null;
  form.reset();
  dlg.classList.add("new");
  $("#edit-title").textContent = "Add project";
  form.type.innerHTML = state.templates.map(t => `<option ${t === "python-flask" ? "selected" : ""}>${esc(t)}</option>`).join("");
  fillGroupList();
  syncKind();
  $("#edit-error").textContent = "";
  dlg.showModal();
  form.name.focus();
});

async function openEdit(id) {
  const p = await api(`/api/projects/${id}`);
  state.editing = id;
  form.reset();
  dlg.classList.remove("new");
  $("#edit-title").textContent = `Edit ${p.name}`;
  for (const k of ["name", "port", "path", "description", "url_path", "start_sh", "close_sh"]) form[k].value = p[k] ?? "";
  form.kind.value = p.kind || "server";
  form.tags.value = (p.tags || []).join(", ");
  form.group.value = state.groups.find(g => g.id === p.group)?.name || p.group || "";
  form.commands.value = commandsText(p.commands);
  fillGroupList();
  syncKind();
  $("#edit-error").textContent = "";
  dlg.showModal();
}

form.addEventListener("submit", async e => {
  if (e.submitter?.value !== "save") return;
  e.preventDefault();
  const body = {
    name: form.name.value, path: form.path.value, description: form.description.value,
    tags: form.tags.value, kind: form.kind.value, group: form.group.value, commands: form.commands.value,
  };
  if (form.kind.value === "server") {
    body.url_path = form.url_path.value || "/";
    if (form.port.value) body.port = form.port.value;
  }
  try {
    if (state.editing) {
      if (form.kind.value === "server") {
        body.start_sh = form.start_sh.value;
        body.close_sh = form.close_sh.value;
      }
      await api(`/api/projects/${state.editing}`, { method: "PUT", body });
      const file = form.logo.files[0];
      if (file) {
        const fd = new FormData(); fd.append("file", file);
        await api(`/api/projects/${state.editing}/logo`, { method: "POST", body: fd });
        const p = state.projects.find(p => p.id === state.editing);
        if (p) p._v = Date.now();
      }
    } else {
      if (form.kind.value === "server") body.type = form.type.value;
      await api("/api/projects", { method: "POST", body });
    }
    dlg.close();
    refresh();
  } catch (err) {
    $("#edit-error").textContent = err.message;
  }
});

$("#delete").addEventListener("click", async () => {
  if (!confirm("Remove this project from Runner? (Stops it and deletes its Runner data folder — the project itself is untouched.)")) return;
  try { await api(`/api/projects/${state.editing}`, { method: "DELETE" }); dlg.close(); refresh(); }
  catch (err) { $("#edit-error").textContent = err.message; }
});
$("#data-folder").addEventListener("click", () => api(`/api/projects/${state.editing}/data`, { method: "POST" }));

// ---------------------------------------------------------------- edit group
const gdlg = $("#group-edit"), gform = $("#group-form");

function openGroupEdit(gid) {
  const g = state.groups.find(g => g.id === gid);
  state.editingGroup = gid;
  gform.reset();
  gform.name.value = g?.name || gid;
  gform.description.value = g?.description || "";
  $("#group-title").textContent = `Edit group ${g?.name || gid}`;
  $("#group-error").textContent = "";
  gdlg.showModal();
}

gform.addEventListener("submit", async e => {
  if (e.submitter?.value !== "save") return;
  e.preventDefault();
  const gid = state.editingGroup;
  try {
    await api(`/api/groups/${gid}`, { method: "PUT", body: { name: gform.name.value, description: gform.description.value } });
    const file = gform.logo.files[0];
    if (file) {
      const fd = new FormData(); fd.append("file", file);
      await api(`/api/groups/${gid}/logo`, { method: "POST", body: fd });
      const g = state.groups.find(g => g.id === gid);
      if (g) g._v = Date.now();
    }
    gdlg.close();
    refresh();
  } catch (err) {
    $("#group-error").textContent = err.message;
  }
});

$("#group-delete").addEventListener("click", async () => {
  if (!confirm("Remove this group? Its projects stay, ungrouped.")) return;
  try { await api(`/api/groups/${state.editingGroup}`, { method: "DELETE" }); gdlg.close(); refresh(); }
  catch (err) { $("#group-error").textContent = err.message; }
});

// ---------------------------------------------------------------- logs
async function openLog(id) {
  state.logFor = id;
  const p = state.projects.find(p => p.id === id);
  $("#logs-title").textContent = `Log — ${p?.name || id}`;
  $("#log-text").textContent = "";
  $("#logs").showModal();
  await loadLog();
}
async function loadLog() {
  if (!state.logFor || !$("#logs").open) return;
  const { log } = await api(`/api/projects/${state.logFor}/log`);
  const pre = $("#log-text");
  if (pre.textContent !== log) {
    pre.textContent = log || "(no output yet)";
    if ($("#log-follow").checked) pre.scrollTop = pre.scrollHeight;
  }
}
$("#logs-close").addEventListener("click", () => $("#logs").close());
$("#logs").addEventListener("close", () => { state.logFor = null; });

refresh();
setInterval(() => { if (!document.hidden) { refresh(); loadLog(); } }, 1500);
