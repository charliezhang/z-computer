"""Passcode gate. The passcode lives only on the backend; clients hold an opaque token.

The token is an HMAC of the passcode, so it is stateless: any backend instance (or a restarted one) can verify it
without shared storage. Fine for a single shared passcode; replace with real sessions when adding users.
"""
import hmac
import os

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

router = APIRouter()


def _token() -> str:
    secret = os.environ.get("Z_TOKEN_SECRET", "z-computer-dev-secret")
    return hmac.new(secret.encode(), os.environ.get("Z_PASSCODE", "ZC123").encode(), "sha256").hexdigest()


class AuthIn(BaseModel):
    passcode: str


@router.post("/api/auth")
def auth(body: AuthIn) -> dict:
    if not hmac.compare_digest(body.passcode, os.environ.get("Z_PASSCODE", "ZC123")):
        raise HTTPException(401, "wrong passcode")
    return {"token": _token()}


def require_token(x_z_token: str = Header(default="")) -> None:
    if not ws_token_ok(x_z_token):
        raise HTTPException(401, "missing or invalid token")


def ws_token_ok(token: str | None) -> bool:
    return bool(token) and hmac.compare_digest(token, _token())
