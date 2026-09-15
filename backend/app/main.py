from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from . import apps, auth, coder, db, runtime  # noqa: E402

db.init()
app = FastAPI(title="Z-Studio backend")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"], allow_methods=["*"], allow_headers=["*"])
for r in (auth.router, apps.router, coder.router, runtime.router):
    app.include_router(r)


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}
