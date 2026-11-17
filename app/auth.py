"""JWT auth helpers for per-org library + call routes (same secret as evalra_backend).

Every token carries `sub` (email) and `org_id` — library sounds and eval calls are
scoped by org_id so a team shares one library and one report/pulse namespace.
"""

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from pydantic import BaseModel

from app import config

_bearer = HTTPBearer(auto_error=False)


class CurrentUser(BaseModel):
    email: str
    org_id: str


def _decode_token(token: str) -> dict:
    return jwt.decode(token, config.JWT_SECRET, algorithms=[config.JWT_ALGORITHM])


async def get_current_user_email(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> str:
    if not creds:
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        payload = _decode_token(creds.credentials)
        email = (payload.get("sub") or "").strip().lower()
        if not email:
            raise HTTPException(status_code=401, detail="Invalid token")
        return email
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")


async def get_optional_user_email(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> str | None:
    if not creds:
        return None
    try:
        payload = _decode_token(creds.credentials)
        email = (payload.get("sub") or "").strip().lower()
        return email or None
    except JWTError:
        return None


async def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> CurrentUser:
    if not creds:
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        payload = _decode_token(creds.credentials)
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
    email = (payload.get("sub") or "").strip().lower()
    org_id = payload.get("org_id")
    if not email or not org_id:
        raise HTTPException(status_code=401, detail="Please log in again")
    return CurrentUser(email=email, org_id=org_id)


async def get_optional_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> CurrentUser | None:
    if not creds:
        return None
    try:
        payload = _decode_token(creds.credentials)
    except JWTError:
        return None
    email = (payload.get("sub") or "").strip().lower()
    org_id = payload.get("org_id")
    if not email or not org_id:
        return None
    return CurrentUser(email=email, org_id=org_id)
