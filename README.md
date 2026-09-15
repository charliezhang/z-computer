# Z-Computer MVP

A controlled ecosystem where parents and teachers "vibe create" educational mini-apps.

- **Z-Studio** (`/#/studio`): lovable-like authoring UI. Talks to **Z-Coder**, a headless Claude Code agent
  (Python Agent SDK) constrained to the Z-platform primitives.
- **Z-runtime**: each app's `server.js` runs in QuickJS inside the FastAPI process; its `client.js` runs in a
  sandboxed iframe. They talk only over one platform-managed WebSocket.
- **Z-Computer** (`/#/computer`): kid-facing thin client that lists and runs published apps.
- Apps are stored as `.zab` bundles (zip: `manifest.json`, `client.js`, `server.js`, `prompts.json`, `assets/`) in SQLite.
- Client primitives: `Z.send/onMessage/onReady/asset`, `Z.takePicture()`, `Z.recognizeSpeech()`, and
  `Z.reactToImage(image, promptId)`, which the host relays over the app's WebSocket so the backend runs a fast
  multimodal call (Claude Haiku) with the prompt persisted in the bundle's `prompts.json`. Images are never stored.
- Every successful Z-Coder turn snapshots the workspace as a new **revision**. **Publish** points the app's live
  pointer at the latest revision (what Z-Computer serves). **History** in Studio tags the live revision and can
  **revert** the draft to any earlier revision (recorded as a new revision; re-publish to make it live).

## Run

```
cp backend/.env.example backend/.env   # set ANTHROPIC_API_KEY
make install
make dev                                # backend :8000, frontend :5173
```

Open http://localhost:5173, passcode `ZC123`.

## Demo

1. Creator → New app → prompt: "Make a 10-question times-table quiz for a 3rd grader; the server checks answers and keeps a best score."
2. Watch Z-Coder's thinking / tool calls stream in; the draft preview reloads when it finishes.
3. Publish. Home → Child opens Z-Computer in a new tab; the app appears in the grid.
4. Agent trace is persisted: `sqlite3 backend/data/z.db 'select kind,count(*) from agent_events group by kind'`.
5. Bundle download: `GET /api/apps/<id>/bundle.zab` (header `X-Z-Token`).

## Deploy (AWS EC2)

Uses the `zc` AWS CLI profile (override with `AWS_PROFILE`). One t3.small Ubuntu box runs Caddy (auto HTTPS on
`<ip>.sslip.io`, serves the built frontend, proxies `/api` and `/ws`) and the backend as a systemd service.

```
make infra     # once: key pair from ~/.ssh/id_ed25519.pub, security group, instance, Elastic IP -> deploy/instance.env
make deploy    # every time: rsync repo + backend/.env, install/build on the box, restart services
make logs      # tail backend logs
make ssh
```
