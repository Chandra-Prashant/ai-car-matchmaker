"""FastAPI entrypoint.

Hosts the session and turn API. The MCP servers run as separate processes
over stdio and are not mounted here — see app/mcp_servers/.
"""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.sessions import router as session_router

app = FastAPI(
    title="AI Car Matchmaker",
    description="Multistep agent for finding a car to buy or rent",
    version="0.1.0",
)

# The frontend runs on 3000 and the MCP Apps sandbox proxy on 3001 — the
# spec requires the sandbox to sit on an origin distinct from the host, and
# differing ports satisfy that. Both need to reach this API.
_DEFAULT_ORIGINS = "http://localhost:3000,http://localhost:3001"
_origins = os.getenv("CORS_ORIGINS", _DEFAULT_ORIGINS).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _origins if o.strip()],
    # Session id travels in a cookie, so credentials must be allowed.
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(session_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
