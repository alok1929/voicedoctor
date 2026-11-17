from motor.motor_asyncio import AsyncIOMotorClient
from app.config import settings

_client: AsyncIOMotorClient | None = None


def get_client() -> AsyncIOMotorClient:
    global _client
    if _client is None:
        _client = AsyncIOMotorClient(settings.mongodb_uri)
    return _client


def get_db():
    return get_client()[settings.mongodb_db]


def reports_col():
    return get_db()["reports"]


def users_col():
    return get_db()["users"]


def pulses_col():
    return get_db()["pulses"]


def orgs_col():
    return get_db()["organizations"]


async def close_client():
    global _client
    if _client:
        _client.close()
        _client = None
