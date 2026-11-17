"""JWT verification for protected routes (tokens issued by routes/auth.py).

Every token carries both `sub` (email) and `org_id` — all data ownership in this
app (reports, pulses, library sounds) is scoped by org_id, not by individual user,
so every authenticated request resolves the caller's org up front.
"""

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from pydantic import BaseModel

from app.config import settings

_bearer = HTTPBearer(auto_error=False)


class CurrentUser(BaseModel):
    email: str
    org_id: str


def _decode(token: str) -> dict:
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])


async def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> CurrentUser:
    if not creds:
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        payload = _decode(creds.credentials)
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
    email = (payload.get("sub") or "").strip().lower()
    org_id = payload.get("org_id")
    if not email or not org_id:
        # org_id is missing on tokens minted before org support existed — the user
        # needs to log in again to get a token carrying it.
        raise HTTPException(status_code=401, detail="Please log in again")
    return CurrentUser(email=email, org_id=org_id)


async def get_current_user_email(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> str:
    return (await get_current_user(creds)).email
