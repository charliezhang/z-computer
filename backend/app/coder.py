"""Z-Coder: a headless Claude Code agent (Agent SDK) that edits one app workspace per session."""
import asyncio
import json
import os
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage, ClaudeAgentOptions, ResultMessage, StreamEvent, TextBlock, ThinkingBlock,
    ToolResultBlock, ToolUseBlock, UserMessage, query,
)
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from . import db
from .apps import get_app, snapshot, sync_manifest, workspace
from .auth import ws_token_ok

router = APIRouter()
PROMPT = (Path(__file__).parent / "zcoder_prompt.md").read_text()
_locks: dict[str, asyncio.Lock] = {}

MODELS = ["claude-opus-4-6", "claude-opus-4-7", "claude-opus-4-8", "claude-opus-5", "claude-sonnet-4-6", "claude-sonnet-5", "claude-haiku-4-5"]
EFFORTS = ["low", "medium", "high", "xhigh", "max"]
DEFAULT_MODEL, DEFAULT_EFFORT = "claude-opus-5", "high"

# The CLI refuses to start nested inside another Claude Code session; this server is not one.
os.environ.pop("CLAUDECODE", None)


def _options(app: dict, model: str, effort: str) -> ClaudeAgentOptions:
    return ClaudeAgentOptions(
        model=model,
        effort=effort,
        cwd=str(workspace(app["id"])),
        system_prompt=PROMPT,
        allowed_tools=["Read", "Write", "Edit", "Glob", "Grep"],
        disallowed_tools=["Bash", "WebFetch", "WebSearch", "Task", "NotebookEdit"],
        permission_mode="acceptEdits",
        setting_sources=[],
        resume=app.get("agent_session_id"),
        max_turns=100,
        thinking={"type": "adaptive", "display": "summarized"},
        include_partial_messages=True,  # stream thinking/text deltas so Studio shows live progress
        env={k: v for k in ("ANTHROPIC_API_KEY",) if (v := os.environ.get(k))},
    )


async def run_turn(app_id: str, prompt: str, model: str = DEFAULT_MODEL, effort: str = DEFAULT_EFFORT) -> AsyncIterator[dict]:
    """Run one Z-Coder turn; yield and persist every event (thinking included). `delta` events are live-only."""
    app = get_app(app_id)
    run_id = uuid.uuid4().hex
    seq = 0

    def emit(kind: str, payload: dict) -> dict:
        nonlocal seq
        seq += 1
        ev = {"run_id": run_id, "seq": seq, "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "kind": kind, "payload": payload}
        db.execute("INSERT INTO agent_events (app_id, run_id, seq, ts, kind, payload_json) VALUES (?,?,?,?,?,?)",
                   (app_id, run_id, seq, ev["ts"], kind, json.dumps(payload, default=str)))
        return ev

    yield emit("user_prompt", {"text": prompt, "model": model, "effort": effort})
    try:
        async for msg in query(prompt=prompt, options=_options(app, model, effort)):
            if isinstance(msg, StreamEvent):
                # Transient, not persisted: the complete block arrives later as a thinking/text event.
                ev = msg.event
                if ev.get("type") == "content_block_delta":
                    d = ev.get("delta", {})
                    chunk = d.get("thinking") if d.get("type") == "thinking_delta" else d.get("text") if d.get("type") == "text_delta" else None
                    if chunk:
                        yield {"kind": "delta", "payload": {"index": ev.get("index", 0),
                                                            "block": "thinking" if d["type"] == "thinking_delta" else "text",
                                                            "text": chunk}}
            elif isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, ThinkingBlock) and block.thinking:
                        yield emit("thinking", {"text": block.thinking})
                    elif isinstance(block, TextBlock):
                        yield emit("text", {"text": block.text})
                    elif isinstance(block, ToolUseBlock):
                        yield emit("tool_use", {"id": block.id, "name": block.name, "input": block.input})
            elif isinstance(msg, UserMessage) and isinstance(msg.content, list):
                for block in msg.content:
                    if isinstance(block, ToolResultBlock):
                        yield emit("tool_result", {"tool_use_id": block.tool_use_id, "is_error": bool(block.is_error),
                                                   "content": block.content})
            elif isinstance(msg, ResultMessage):
                db.execute("UPDATE apps SET agent_session_id=? WHERE id=?", (msg.session_id, app_id))
                sync_manifest(app_id)
                rev = None if msg.is_error else snapshot(app_id, "agent", msg.result or prompt)
                yield emit("result", {"session_id": msg.session_id, "num_turns": msg.num_turns,
                                      "duration_ms": msg.duration_ms, "total_cost_usd": msg.total_cost_usd,
                                      "is_error": msg.is_error, "text": msg.result,
                                      "revision": rev["number"] if rev else None,
                                      "models": sorted(msg.model_usage or {})})
                break  # the turn is complete; release the per-app lock without waiting for the CLI to exit
    except Exception as e:
        yield emit("error", {"message": f"{type(e).__name__}: {e}"})


@router.websocket("/ws/studio/{app_id}")
async def ws_studio(ws: WebSocket, app_id: str, token: str = ""):
    if not ws_token_ok(token):
        await ws.close(code=4401)
        return
    await ws.accept()
    lock = _locks.setdefault(app_id, asyncio.Lock())
    try:
        while True:
            frame = await ws.receive_json()
            prompt = (frame.get("prompt") or "").strip()
            if not prompt:
                continue
            if lock.locked():
                await ws.send_json({"kind": "error", "payload": {"message": "Z-Coder is still working on this app"}})
                continue
            model = frame.get("model") if frame.get("model") in MODELS else DEFAULT_MODEL
            effort = frame.get("effort") if frame.get("effort") in EFFORTS else DEFAULT_EFFORT
            async with lock:
                async for ev in run_turn(app_id, prompt, model, effort):
                    await ws.send_json(ev)
    except WebSocketDisconnect:
        pass
