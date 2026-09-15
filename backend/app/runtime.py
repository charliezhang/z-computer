"""Z-runtime: hosts an app's server.js in QuickJS and bridges it to one client over one WebSocket."""
import asyncio
import json
import time

import quickjs
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from . import db
from .apps import load_files
from .auth import ws_token_ok
from .vision import react_to_image

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
            if frame.get("type") == "primitive":
                await ws.send_json(await run_primitive(app_id, mode, frame))
                continue
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


async def run_primitive(app_id: str, mode: str, frame: dict) -> dict:
    """Platform primitives that need the backend (today: reactToImage). Prompts come from the app's prompts.json."""
    rid, name, args = frame.get("id"), frame.get("name"), frame.get("args") or {}
    try:
        if name != "reactToImage":
            raise ValueError(f"unknown primitive: {name}")
        prompt_id = str(args.get("promptId", ""))
        spec = load_files(app_id, mode)["prompts"].get(prompt_id)
        if spec is None:
            raise ValueError(f"no prompt '{prompt_id}' in prompts.json")
        prompt = spec["prompt"] if isinstance(spec, dict) else str(spec)
        max_tokens = int(spec.get("max_tokens", 300)) if isinstance(spec, dict) else 300
        t0 = time.monotonic()
        text = await react_to_image(prompt, args.get("image", ""), max_tokens=max_tokens)
        print(f"[app {app_id}] reactToImage '{prompt_id}' {time.monotonic() - t0:.1f}s {len(text)} chars", flush=True)
        return {"type": "primitive_result", "id": rid, "ok": True, "value": text}
    except Exception as e:
        return {"type": "primitive_result", "id": rid, "ok": False, "error": f"{type(e).__name__}: {e}"}
