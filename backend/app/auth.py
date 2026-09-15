"""Passcode gate. The passcode lives only on the backend; clients hold an opaque token."""
import os
import secrets

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

router = APIRouter()
_TOKENS: set[str] = set()


class AuthIn(BaseModel):
    passcode: str


@router.post("/api/auth")
def auth(body: AuthIn) -> dict:
    if body.passcode != os.environ.get("Z_PASSCODE", "ZC123"):
        raise HTTPException(401, "wrong passcode")
    token = secrets.token_hex(16)
    _TOKENS.add(token)
    return {"token": token}


def require_token(x_z_token: str = Header(default="")) -> None:
    if x_z_token not in _TOKENS:
        raise HTTPException(401, "missing or invalid token")


def ws_token_ok(token: str | None) -> bool:
    return bool(token) and token in _TOKENS
