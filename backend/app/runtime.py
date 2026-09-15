"""Z-runtime: hosts an app's server.js in QuickJS and bridges it to one client over one WebSocket."""
import asyncio
import json

import quickjs
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from . import db
from .apps import load_files
from .auth import ws_token_ok

router = APIRouter()

# The only surface server.js can see. Everything crosses the boundary as JSON strings.
PRELUDE = """
var Z = (function () {
  var handler = null;
  function enc(v) { return JSON.stringify(v === undefined ? null : v); }
  return {
    onMessage: function (f) { handler = f; },
    send: function (d) { __send(enc(d)); },
    state: {
      get: function (k, dflt) { var v = __state_get(String(k)); return v === '' ? dflt : JSON.parse(v); },
      set: function (k, v) { __state_set(String(k), enc(v)); }
    },
    log: function () {
      __log(Array.prototype.map.call(arguments, function (a) { return typeof a === 'string' ? a : JSON.stringify(a); }).join(' '));
    },
    __dispatch: function (s) { if (handler) handler(JSON.parse(s)); }
  };
})();
"""


class ServerScript:
    """One QuickJS context per connection. Outbound messages are queued and drained by the caller."""

    def __init__(self, app_id: str, code: str):
        self.app_id = app_id
        self.outbox: list = []
        ctx = self.ctx = quickjs.Context()
        ctx.set_memory_limit(32 * 1024 * 1024)
        ctx.set_max_stack_size(1024 * 1024)
        ctx.add_callable("__send", lambda s: self.outbox.append(json.loads(s)))
        ctx.add_callable("__state_get", self._state_get)
        ctx.add_callable("__state_set", self._state_set)
        ctx.add_callable("__log", lambda s: print(f"[app {app_id}] {s}", flush=True))
        ctx.eval(PRELUDE)
        ctx.eval(code)

    def _state_get(self, key: str) -> str:
        row = db.one("SELECT value_json FROM app_state WHERE app_id=? AND key=?", (self.app_id, key))
        return row["value_json"] if row else ""

    def _state_set(self, key: str, value_json: str) -> None:
        db.execute("INSERT OR REPLACE INTO app_state (app_id, key, value_json) VALUES (?,?,?)",
                   (self.app_id, key, value_json))

    def dispatch(self, data) -> list:
        self.ctx.eval(f"Z.__dispatch({json.dumps(json.dumps(data))})")
        out, self.outbox = self.outbox, []
        return out


@router.websocket("/ws/app/{app_id}")
async def ws_app(ws: WebSocket, app_id: str, token: str = "", mode: str = "draft"):
    if not ws_token_ok(token):
        await ws.close(code=4401)
        return
    await ws.accept()
    try:
        code = load_files(app_id, mode)["server_js"]
        script = await asyncio.to_thread(ServerScript, app_id, code)
    except Exception as e:  # missing app, JS syntax error, ...
        await ws.send_json({"type": "error", "message": f"server.js failed to load: {e}"})
        await ws.close()
        return
    try:
        while True:
            frame = await ws.receive_json()
            if frame.get("type") != "msg":
                continue
            try:
                out = await asyncio.to_thread(script.dispatch, frame.get("data"))
            except quickjs.JSException as e:
                await ws.send_json({"type": "error", "message": f"server.js error: {e}"})
                continue
            for data in out:
                await ws.send_json({"type": "msg", "data": data})
    except WebSocketDisconnect:
        pass
