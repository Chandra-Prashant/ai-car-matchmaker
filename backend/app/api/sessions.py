"""Session and turn endpoints.

Serves T032 and FR-025 (a session survives reload).

The session id travels in a cookie. Scope is single-browser by decision
recorded in plan.md section 2 — cross-device resumption was judged to add
no value a demo can show.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, Cookie, Depends, HTTPException, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.agent.phases import phase_status
from app.agent.scripted import SCRIPTS, ScriptedRunner
from app.api.events import stream_sse
from app.db import get_session
from app.state.models import SessionState
from app.state.store import SessionStore

router = APIRouter(prefix="/api", tags=["session"])

SESSION_COOKIE = "matchmaker_session"
COOKIE_MAX_AGE = 60 * 60 * 24 * 7


class SessionSummary(BaseModel):
    session_id: str
    phase: str
    known: dict
    missing: list[str]
    conflicts: list[str]
    shortlist: list[str]
    status: dict


class TurnRequest(BaseModel):
    message: str
    #: Which scripted journey to run. Removed once the model-backed
    #: runner lands; until then it is how the demo scenarios are driven.
    script: str = "rental"


def _summarise(state: SessionState) -> SessionSummary:
    panel = state.panel()
    return SessionSummary(
        session_id=state.session_id,
        phase=state.phase.value,
        known=panel["known"],
        missing=panel["missing"],
        conflicts=panel["conflicts"],
        shortlist=state.shortlist,
        status=phase_status(state),
    )


@router.post("/sessions", response_model=SessionSummary)
def create_session(
    response: Response,
    db: Annotated[Session, Depends(get_session)],
) -> SessionSummary:
    store = SessionStore(db)
    state = store.create()
    db.commit()

    response.set_cookie(
        SESSION_COOKIE,
        state.session_id,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
    )
    return _summarise(state)


@router.get("/sessions/current", response_model=SessionSummary)
def current_session(
    response: Response,
    db: Annotated[Session, Depends(get_session)],
    matchmaker_session: Annotated[str | None, Cookie()] = None,
) -> SessionSummary:
    """Resume from the cookie, or start fresh.

    An unknown id yields a new session rather than an error — a stale cookie
    should not present the user with a failure page.
    """
    store = SessionStore(db)
    state = store.get_or_create(matchmaker_session)
    db.commit()

    if state.session_id != matchmaker_session:
        response.set_cookie(
            SESSION_COOKIE,
            state.session_id,
            max_age=COOKIE_MAX_AGE,
            httponly=True,
            samesite="lax",
        )
    return _summarise(state)


@router.get("/sessions/{session_id}", response_model=SessionSummary)
def get_session_by_id(
    session_id: str,
    db: Annotated[Session, Depends(get_session)],
) -> SessionSummary:
    state = SessionStore(db).get(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="No such session")
    return _summarise(state)


@router.get("/sessions/{session_id}/history")
def get_history(
    session_id: str,
    db: Annotated[Session, Depends(get_session)],
) -> dict:
    """Turns, transitions and reasoning — the replay view (FR-024)."""
    state = SessionStore(db).get(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="No such session")

    return {
        "session_id": state.session_id,
        "turns": [t.model_dump(mode="json") for t in state.history],
        "transitions": [t.model_dump(mode="json") for t in state.transitions],
        "reasoning": [r.model_dump(mode="json") for r in state.reasoning_log],
        "weights": state.inferred_weights,
        "weight_source": state.weight_source.value,
    }


@router.post("/sessions/{session_id}/turn")
def take_turn(
    session_id: str,
    body: Annotated[TurnRequest, Body()],
    db: Annotated[Session, Depends(get_session)],
) -> StreamingResponse:
    """Send a message and stream the agent's events back.

    The turn is the stream: the response body stays open until the agent
    finishes, then closes. No separate subscribe call, no server-side queue.

    Currently driven by the scripted runner. Swapping in the model-backed
    runner changes only the line below, because both satisfy `AgentRunner`.
    """
    store = SessionStore(db)
    state = store.get(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="No such session")

    steps = SCRIPTS.get(body.script)
    if steps is None:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown script. Available: {sorted(SCRIPTS)}",
        )

    runner = ScriptedRunner(db, steps)

    async def events():
        async for frame in stream_sse(runner.run_turn(state, body.message)):
            yield frame
        # Persist once the turn has finished rather than per event: a
        # half-finished turn should not leave partial state behind.
        store.save(state)
        db.commit()

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # Nginx and similar buffer SSE by default, which delays every
            # event until the turn ends and defeats the point.
            "X-Accel-Buffering": "no",
        },
    )


@router.delete("/sessions/{session_id}")
def delete_session(
    session_id: str,
    db: Annotated[Session, Depends(get_session)],
) -> dict:
    removed = SessionStore(db).delete(session_id)
    db.commit()
    if not removed:
        raise HTTPException(status_code=404, detail="No such session")
    return {"deleted": session_id}
