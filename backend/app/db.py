"""SQLite access. One short-lived connection per call; WAL mode handles concurrency."""
import os
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path


def _pick_data_dir() -> Path:
    """Z_DATA_DIR if set; else backend/data; else the temp dir when that is not writable."""
    if os.environ.get("Z_DATA_DIR"):
        return Path(os.environ["Z_DATA_DIR"])
    default = Path(__file__).resolve().parent.parent / "data"
    try:
        default.mkdir(parents=True, exist_ok=True)
        probe = default / ".write-test"
        probe.touch()
        probe.unlink()
        return default
    except OSError:
        return Path(tempfile.gettempdir()) / "z-data"


DATA_DIR = _pick_data_dir()
DB_PATH = DATA_DIR / "z.db"
APPS_DIR = DATA_DIR / "apps"

SCHEMA = """
CREATE TABLE IF NOT EXISTS apps (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  icon TEXT NOT NULL DEFAULT '📦',
  status TEXT NOT NULL DEFAULT 'draft',
  agent_session_id TEXT,
  live_revision_id INTEGER,      -- revision currently served to Z-Computer
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS revisions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  app_id TEXT NOT NULL REFERENCES apps(id),
  number INTEGER NOT NULL,
  source TEXT NOT NULL,          -- initial | agent | revert | publish
  summary TEXT NOT NULL,
  manifest_json TEXT NOT NULL,
  zab BLOB NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  app_id TEXT NOT NULL,
  run_id TEXT NOT NULL,
  seq INTEGER NOT NULL,
  ts TEXT NOT NULL,
  kind TEXT NOT NULL,
  payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS app_state (
  app_id TEXT NOT NULL,
  key TEXT NOT NULL,
  value_json TEXT NOT NULL,
  PRIMARY KEY (app_id, key)
);
"""


def connect() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def init() -> None:
    APPS_DIR.mkdir(parents=True, exist_ok=True)
    with closing(connect()) as c:
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript(SCHEMA)
        _migrate(c)


def _migrate(c: sqlite3.Connection) -> None:
    """Earlier MVP builds stored published snapshots in `bundles`; fold them into `revisions`."""
    cols = {r[1] for r in c.execute("PRAGMA table_info(apps)")}
    if "live_revision_id" not in cols:
        c.execute("ALTER TABLE apps ADD COLUMN live_revision_id INTEGER")
    if c.execute("SELECT 1 FROM sqlite_master WHERE name='bundles'").fetchone():
        for b in c.execute("SELECT * FROM bundles ORDER BY app_id, version").fetchall():
            rid = c.execute(
                "INSERT INTO revisions (app_id, number, source, summary, manifest_json, zab, created_at) VALUES (?,?,?,?,?,?,?)",
                (b["app_id"], b["version"], "publish", f"Published v{b['version']}", b["manifest_json"], b["zab"], b["created_at"])).lastrowid
            c.execute("UPDATE apps SET live_revision_id=? WHERE id=?", (rid, b["app_id"]))
        c.execute("DROP TABLE bundles")
        c.commit()


def query(sql: str, params: tuple = ()) -> list[dict]:
    with closing(connect()) as c:
        return [dict(r) for r in c.execute(sql, params).fetchall()]


def one(sql: str, params: tuple = ()) -> dict | None:
    rows = query(sql, params)
    return rows[0] if rows else None


def execute(sql: str, params: tuple = ()) -> int:
    with closing(connect()) as c, c:
        return c.execute(sql, params).lastrowid
