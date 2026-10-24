"""Bearer tokens for the mobile app: HMAC-signed "user_id:expiry", no server-side session table."""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from db import repo

TOKEN_TTL_S = 30 * 24 * 3600
_bearer = HTTPBearer(auto_error=False)


def _secret() -> bytes:
    return (os.environ.get("APP_SECRET") or os.environ.get("DATABASE_URL") or "dev-secret-change-me").encode()


def sign(user_id: int, ttl_s: int = TOKEN_TTL_S, purpose: str = "api") -> str:
    msg = f"{purpose}:{user_id}:{int(time.time()) + ttl_s}".encode()
    sig = hmac.new(_secret(), msg, hashlib.sha256).hexdigest()[:40]
    return base64.urlsafe_b64encode(msg).decode().rstrip("=") + "." + sig


def verify(token: str, purpose: str = "api") -> int | None:
    try:
        body, sig = token.split(".")
        msg = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))
        good = hmac.new(_secret(), msg, hashlib.sha256).hexdigest()[:40]
        if not hmac.compare_digest(good, sig):
            return None
        p, uid, exp = msg.decode().split(":")
        return int(uid) if p == purpose and int(exp) >= time.time() else None
    except Exception:  # noqa: BLE001
        return None


def current_user(creds: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> dict:
    uid = verify(creds.credentials) if creds else None
    user = repo.get_user(uid) if uid else None
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Autentificați-vă din nou.")
    return user


def require_site(user: dict = Depends(current_user)) -> tuple[dict, dict]:
    site = repo.get_site_for_user(user["id"])
    if not site:
        raise HTTPException(status.HTTP_409_CONFLICT, "Completați mai întâi profilul instalației.")
    return user, site


def require_premium(user: dict) -> None:
    if user.get("plan") != "premium":
        raise HTTPException(status.HTTP_402_PAYMENT_REQUIRED,
                            "Funcție Premium. Abonați-vă din ecranul Cont (mod de test, fără bani reali).")
