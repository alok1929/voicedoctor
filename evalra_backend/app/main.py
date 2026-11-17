from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import close_client
from app.routes import reports, metrics, auth, pulses


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await close_client()


app = FastAPI(
    title="Evalra Backend",
    description="Stores eval call reports in MongoDB and serves aggregated metrics.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(reports.router)
app.include_router(metrics.router)
app.include_router(auth.router)
app.include_router(pulses.router)


@app.get("/health")
async def health():
    return {"status": "healthy"}
