from datetime import datetime, timedelta
from uuid import uuid4

import bcrypt
from fastapi import APIRouter, HTTPException
from jose import jwt
from pydantic import BaseModel

from app.config import settings
from app.database import orgs_col, users_col

router = APIRouter(prefix="/auth", tags=["auth"])


class SignupRequest(BaseModel):
    name: str
    email: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


def _hash(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def _verify(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def _token(email: str, name: str, org_id: str) -> str:
    payload = {
        "sub": email,
        "name": name,
        "org_id": org_id,
        "exp": datetime.utcnow() + timedelta(days=settings.jwt_expire_days),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


async def _ensure_org_id(user: dict) -> str:
    """Every user belongs to exactly one org. New users get a fresh org at signup;
    this self-heals any pre-existing account that predates org support."""
    org_id = user.get("org_id")
    if org_id:
        return org_id
    org_id = uuid4().hex
    await orgs_col().insert_one({
        "_id": org_id,
        "name": f"{user['name']}'s org",
        "created_at": datetime.utcnow(),
    })
    await users_col().update_one({"email": user["email"]}, {"$set": {"org_id": org_id}})
    return org_id


@router.post("/signup")
async def signup(req: SignupRequest):
    email = req.email.lower().strip()
    name = req.name.strip()
    col = users_col()
    if await col.find_one({"email": email}):
        raise HTTPException(status_code=409, detail="Email already registered")

    org_id = uuid4().hex
    await orgs_col().insert_one({
        "_id": org_id,
        "name": f"{name}'s org",
        "created_at": datetime.utcnow(),
    })
    await col.insert_one({
        "email": email,
        "name": name,
        "password_hash": _hash(req.password),
        "org_id": org_id,
        "created_at": datetime.utcnow(),
    })
    token = _token(email, name, org_id)
    return {"token": token, "email": email, "name": name}


@router.post("/login")
async def login(req: LoginRequest):
    email = req.email.lower().strip()
    col = users_col()
    user = await col.find_one({"email": email})
    if not user or not _verify(req.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    org_id = await _ensure_org_id(user)
    token = _token(user["email"], user["name"], org_id)
    return {"token": token, "email": user["email"], "name": user["name"]}
