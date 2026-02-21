"""
F.I.R.E. — Freedom Intelligent Routing Engine
FastAPI Application Entrypoint
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.api import ingest, tickets, processing, dashboard

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup / shutdown lifecycle."""
    # ── Startup ──
    print("🔥 F.I.R.E. Engine starting up...")
    yield
    # ── Shutdown ──
    print("🔥 F.I.R.E. Engine shutting down...")


app = FastAPI(
    title="F.I.R.E. — Freedom Intelligent Routing Engine",
    description=(
        "AI-powered ticket routing system with real-time processing, "
        "PII anonymization, sentiment analysis, geocoding, and smart routing."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

# ── CORS (allow frontend) ──
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Lock down in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Register routers ──
app.include_router(ingest.router)
app.include_router(tickets.router)
app.include_router(processing.router)
app.include_router(dashboard.router)


# ── Health check ──
@app.get("/health", tags=["System"])
async def health_check():
    return {
        "status": "healthy",
        "service": "F.I.R.E. Engine",
        "version": "0.1.0",
    }


@app.get("/", tags=["System"])
async def root():
    return {
        "message": "🔥 F.I.R.E. — Freedom Intelligent Routing Engine",
        "docs": "/docs",
        "health": "/health",
    }
