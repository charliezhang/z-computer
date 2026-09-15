"""App CRUD, draft workspace, revision history (.zab snapshots), publish pointer, revert."""
import base64
import difflib
import json
import mimetypes
import secrets
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from . import db
from .auth import require_token
from .zab import pack, read_bundle, read_workspace, unpack

router = APIRouter(prefix="/api/apps", dependencies=[Depends(require_token)])

BOOTSTRAP_CLIENT = """// client.js — runs in the kid's browser inside a sandboxed iframe.
const app = document.getElementById('app');
app.innerHTML = `
  <div style="font-family:sans-serif;text-align:center;padding:40px">
    <h1>👋 Hello, I'm a new Z app</h1>
    <button id="ping" style="font-size:24px;padding:12px 24px">Ping the server</button>
    <p id="out"></p>
  </div>`;
document.getElementById('ping').onclick = () => Z.send({ type: 'ping' });
Z.onMessage((msg) => {
  if (msg.type === 'pong') document.getElementById('out').textContent = 'Server says pong #' + msg.count;
});
"""

BOOTSTRAP_SERVER = """// server.js — runs inside Z-runtime (QuickJS) on the platform server.
Z.onMessage((msg) => {
  if (msg.type === 'ping') {
    const count = Z.state.get('pings', 0) + 1;
    Z.state.set('pings', count);
    Z.send({ type: 'pong', count });
  }
});
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def workspace(app_id: str) -> Path:
    return db.APPS_DIR / app_id


def get_app(app_id: str) -> dict:
    row = db.one("SELECT * FROM apps WHERE id=?", (app_id,))
    if not row:
        raise HTTPException(404, "no such app")
    return row


# ---- revisions -------------------------------------------------------------

def latest_revision(app_id: str) -> dict | None:
    return db.one("SELECT * FROM revisions WHERE app_id=? ORDER BY number DESC LIMIT 1", (app_id,))


def live_revision(app_id: str) -> dict | None:
    return db.one("SELECT r.* FROM apps a JOIN revisions r ON r.id = a.live_revision_id WHERE a.id=?", (app_id,))


def snapshot(app_id: str, source: str, summary: str) -> dict:
    """Freeze the current workspace as a new numbered revision (.zab in SQLite)."""
    d = workspace(app_id)
    prev = latest_revision(app_id)
    number = (prev["number"] if prev else 0) + 1
    manifest_path = d / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["id"] = app_id
    manifest["version"] = number
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    rid = db.execute(
        "INSERT INTO revisions (app_id, number, source, summary, manifest_json, zab, created_at) VALUES (?,?,?,?,?,?,?)",
        (app_id, number, source, summary[:300], json.dumps(manifest), pack(d), now()))
    sync_manifest(app_id)
    return db.one("SELECT * FROM revisions WHERE id=?", (rid,))


def workspace_changed_since(rev: dict | None) -> bool:
    if not rev:
        return True
    return read_workspace(workspace(rev["app_id"])) != read_bundle(rev["zab"])


def load_files(app_id: str, mode: str) -> dict:
    """Draft = workspace on disk (what Z-Coder edits). Published = the live revision's .zab."""
    if mode == "published":
        r = live_revision(app_id)
        if not r:
            raise HTTPException(404, "app not published")
        return read_bundle(r["zab"])
    d = workspace(app_id)
    if not d.is_dir():
        raise HTTPException(404, "no workspace")
    return read_workspace(d)


def sync_manifest(app_id: str) -> None:
    """Copy name/icon from the workspace manifest onto the apps row."""
    m = json.loads((workspace(app_id) / "manifest.json").read_text())
    db.execute("UPDATE apps SET name=?, icon=?, updated_at=? WHERE id=?",
               (m.get("name", "Untitled"), m.get("icon", "📦"), now(), app_id))


# ---- routes ----------------------------------------------------------------

class CreateIn(BaseModel):
    name: str


DRAFT_LIST_SQL = """SELECT a.*, r.number AS version FROM apps a
                    LEFT JOIN revisions r ON r.id = a.live_revision_id ORDER BY a.updated_at DESC"""
# Published list shows what the kid will actually run: name/icon from the live revision's manifest.
PUBLISHED_LIST_SQL = """SELECT a.id, a.status, a.updated_at, r.number AS version,
                          json_extract(r.manifest_json, '$.name') AS name,
                          json_extract(r.manifest_json, '$.icon') AS icon
                        FROM apps a JOIN revisions r ON r.id = a.live_revision_id ORDER BY a.updated_at DESC"""


@router.get("")
def list_apps(published: int = 0) -> list[dict]:
    return db.query(PUBLISHED_LIST_SQL if published else DRAFT_LIST_SQL)


@router.post("")
def create_app(body: CreateIn) -> dict:
    app_id = secrets.token_hex(3)
    d = workspace(app_id)
    (d / "assets").mkdir(parents=True)
    manifest = {"id": app_id, "name": body.name, "icon": "📦", "description": "A new Z app", "version": 0, "zab_version": 1}
    (d / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (d / "client.js").write_text(BOOTSTRAP_CLIENT)
    (d / "server.js").write_text(BOOTSTRAP_SERVER)
    db.execute("INSERT INTO apps (id, name, icon, status, created_at, updated_at) VALUES (?,?,?,?,?,?)",
               (app_id, body.name, "📦", "draft", now(), now()))
    snapshot(app_id, "initial", "New app from template")
    return get_app(app_id)


@router.get("/{app_id}")
def read_app(app_id: str) -> dict:
    return get_app(app_id)


@router.get("/{app_id}/files")
def files(app_id: str, mode: str = "draft") -> dict:
    get_app(app_id)
    f = load_files(app_id, mode)
    f["assets"] = {
        name: f"data:{mimetypes.guess_type(name)[0] or 'application/octet-stream'};base64,{base64.b64encode(data).decode()}"
        for name, data in f["assets"].items()
    }
    return f


@router.get("/{app_id}/revisions")
def revisions(app_id: str) -> list[dict]:
    """Revision history, newest first, tagging the one currently live."""
    app = get_app(app_id)
    rows = db.query("SELECT id, number, source, summary, created_at, manifest_json FROM revisions WHERE app_id=? ORDER BY number DESC", (app_id,))
    out = []
    for r in rows:
        m = json.loads(r.pop("manifest_json"))
        out.append({**r, "name": m.get("name", ""), "icon": m.get("icon", ""), "live": r["id"] == app["live_revision_id"]})
    return out


@router.post("/{app_id}/publish")
def publish(app_id: str) -> dict:
    """Make the current draft the production version served to Z-Computer."""
    get_app(app_id)
    rev = latest_revision(app_id)
    if workspace_changed_since(rev):
        rev = snapshot(app_id, "publish", "Published from draft")
    db.execute("UPDATE apps SET status='published', live_revision_id=?, updated_at=? WHERE id=?", (rev["id"], now(), app_id))
    return {"version": rev["number"]}


@router.post("/{app_id}/revisions/{number}/revert")
def revert(app_id: str, number: int) -> dict:
    """Restore the draft workspace to an earlier revision (recorded as a new revision; live pointer untouched)."""
    get_app(app_id)
    rev = db.one("SELECT * FROM revisions WHERE app_id=? AND number=?", (app_id, number))
    if not rev:
        raise HTTPException(404, "no such revision")
    unpack(rev["zab"], workspace(app_id))
    new = snapshot(app_id, "revert", f"Reverted to v{number}")
    return {"version": new["number"]}


@router.post("/{app_id}/revisions/{number}/promote")
def promote(app_id: str, number: int) -> dict:
    """Point production at an existing revision (no snapshot; the draft workspace is untouched)."""
    get_app(app_id)
    rev = db.one("SELECT id FROM revisions WHERE app_id=? AND number=?", (app_id, number))
    if not rev:
        raise HTTPException(404, "no such revision")
    db.execute("UPDATE apps SET status='published', live_revision_id=?, updated_at=? WHERE id=?", (rev["id"], now(), app_id))
    return {"version": number}


def revision_texts(app_id: str, number: int) -> dict[str, str]:
    rev = db.one("SELECT zab FROM revisions WHERE app_id=? AND number=?", (app_id, number))
    if not rev:
        raise HTTPException(404, f"no revision v{number}")
    b = read_bundle(rev["zab"])
    texts = {"manifest.json": json.dumps(b["manifest"], indent=2) + "\n", "client.js": b["client_js"], "server.js": b["server_js"]}
    for name, data in b["assets"].items():
        try:
            texts[f"assets/{name}"] = data.decode()
        except UnicodeDecodeError:
            texts[f"assets/{name}"] = f"<binary {len(data)} bytes>\n"
    return texts


@router.get("/{app_id}/revisions/{a}/diff/{b}")
def diff(app_id: str, a: int, b: int) -> dict:
    """Unified diff of every bundle file from revision a to revision b."""
    get_app(app_id)
    fa, fb = revision_texts(app_id, a), revision_texts(app_id, b)
    files = []
    for name in sorted(set(fa) | set(fb)):
        d = "".join(difflib.unified_diff(fa.get(name, "").splitlines(keepends=True), fb.get(name, "").splitlines(keepends=True),
                                         fromfile=f"v{a}/{name}", tofile=f"v{b}/{name}", n=3))
        files.append({"name": name, "diff": d})
    return {"from": a, "to": b, "files": files}


@router.get("/{app_id}/bundle.zab")
def bundle(app_id: str) -> Response:
    r = live_revision(app_id)
    if not r:
        raise HTTPException(404, "app not published")
    return Response(content=r["zab"], media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{app_id}-v{r["number"]}.zab"'})


@router.get("/{app_id}/events")
def events(app_id: str) -> list[dict]:
    rows = db.query("SELECT id, run_id, seq, ts, kind, payload_json FROM agent_events WHERE app_id=? ORDER BY id", (app_id,))
    return [{**r, "payload": json.loads(r.pop("payload_json"))} for r in rows]
