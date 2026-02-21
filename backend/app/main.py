"""
F.I.R.E. — Freedom Intelligent Routing Engine
FastAPI Application
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.api import ingest, tickets, processing, dashboard

settings = get_settings()

# ── Logging setup ──
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)-18s %(levelname)-5s %(message)s",
    datefmt="%H:%M:%S",
)
# Make pipeline logs always visible
logging.getLogger("pipeline").setLevel(logging.DEBUG)


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("F.I.R.E. Engine starting up...")
    yield
    print("F.I.R.E. Engine shutting down...")


app = FastAPI(
    title="F.I.R.E. — Freedom Intelligent Routing Engine",
    description="AI-powered ticket routing: PII anonymization → spam filter → parallel LLM analysis → geocoding → priority scoring → smart routing",
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

app.include_router(ingest.router)
app.include_router(tickets.router)
app.include_router(processing.router)
app.include_router(dashboard.router)


@app.get("/health", tags=["System"])
async def health():
    return {"status": "healthy", "service": "F.I.R.E. Engine", "version": "0.1.0"}


@app.get("/", tags=["System"])
async def root():
    return {
        "message": "🔥 F.I.R.E. — Freedom Intelligent Routing Engine",
        "docs": "/docs",
        "health": "/health",
    }
