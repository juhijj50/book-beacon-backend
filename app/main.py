from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .database import engine
from .routers import auth, clerk, search, shelf, vault
from .services import embeddings


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Schema is managed by Alembic — run `alembic upgrade head` before serving.
    yield
    await engine.dispose()


app = FastAPI(title="Book Beacon", version="0.2.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(search.router)
app.include_router(shelf.router)
app.include_router(vault.router)
app.include_router(clerk.router)


@app.get("/", tags=["meta"])
async def root():
    return {
        "app": "Book Beacon",
        "ai_features": "on" if embeddings.ai_enabled() else "off (set GEMINI_API_KEY)",
        "docs": "/docs",
    }


@app.get("/health", tags=["meta"])
async def health():
    return {"status": "ok"}
