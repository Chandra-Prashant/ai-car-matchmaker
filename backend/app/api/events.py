"""Agent event stream.

Serves T032 and FR-009 (visible research progress).

TRANSPORT SHAPE
---------------
A turn is a stream. The client POSTs a message and the response body streams
events until the turn finishes. There is no separate "open a stream" call and
no server-side queue: the events of a turn belong to that turn's request.

SSE rather than WebSockets because the flow is one-directional — the client
sends a message as an ordinary POST and receives events back. A duplex
transport would add reconnection and framing concerns for no benefit.

EVENT KINDS
-----------
Two families travel down the same stream:

- Agent events (`phase`, `tool`, `progress`, `message`) describe what the
  agent is doing. These drive the progress timeline.
- A2UI frames (`ui`) carry declarative component trees for the client to
  render with its own components. The agent never sends HTML here — see
  Constitution II.

Keeping both in one ordered stream matters: a car catalogue must appear
after the search that produced it, and interleaving them in one sequence is
what preserves that.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field
from pydantic_core import to_jsonable_python

from app.state.models import SessionState


class EventKind(str, Enum):
    #: Phase changed, or a transition was refused.
    PHASE = "phase"
    #: A tool is about to run, or has returned.
    TOOL = "tool"
    #: Human-readable progress during a long step.
    PROGRESS = "progress"
    #: Assistant text for the conversation.
    MESSAGE = "message"
    #: A sandboxed MCP App View to mount.
    UI = "ui"
    #: An A2UI protocol envelope — createSurface, updateComponents,
    #: updateDataModel or deleteSurface.
    A2UI = "a2ui"
    #: The session state panel, so the client never derives it locally.
    STATE = "state"
    #: Turn finished normally.
    DONE = "done"
    #: Turn failed.
    ERROR = "error"


class AgentEvent(BaseModel):
    kind: EventKind
    at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    data: dict[str, Any] = Field(default_factory=dict)

    def to_sse(self) -> str:
        """Serialise as a Server-Sent Event frame.

        `event:` carries the kind so the browser's EventSource can dispatch
        by listener rather than the client switching on a field.

        Encoded through Pydantic's `to_jsonable_python` before json.dumps:
        event data carries dates and enums straight out of tool results, and
        the stdlib encoder rejects both.
        """
        payload = json.dumps(
            to_jsonable_python({"at": self.at, **self.data}),
            separators=(",", ":"),
        )
        return f"event: {self.kind.value}\ndata: {payload}\n\n"


# --------------------------------------------------------------------------
# Constructors — keep event shapes in one place
# --------------------------------------------------------------------------


def phase_event(
    phase: str,
    allowed: bool = True,
    message: str = "",
    missing: list[str] | None = None,
) -> AgentEvent:
    return AgentEvent(
        kind=EventKind.PHASE,
        data={
            "phase": phase,
            "allowed": allowed,
            "message": message,
            "missing": missing or [],
        },
    )


def tool_started(name: str, arguments: dict[str, Any]) -> AgentEvent:
    return AgentEvent(
        kind=EventKind.TOOL,
        data={"name": name, "status": "started", "arguments": arguments},
    )


def tool_finished(
    name: str, summary: str, result: dict[str, Any] | None = None
) -> AgentEvent:
    return AgentEvent(
        kind=EventKind.TOOL,
        data={
            "name": name,
            "status": "finished",
            "summary": summary,
            "result": result or {},
        },
    )


def progress(text: str, remaining: int | None = None) -> AgentEvent:
    data: dict[str, Any] = {"text": text}
    if remaining is not None:
        data["remaining"] = remaining
    return AgentEvent(kind=EventKind.PROGRESS, data=data)


def message(text: str, role: Literal["assistant"] = "assistant") -> AgentEvent:
    return AgentEvent(kind=EventKind.MESSAGE, data={"role": role, "text": text})


def ui_frame(component: dict[str, Any], surface: str = "inline") -> AgentEvent:
    """An A2UI component tree.

    `surface` says where it belongs: `inline` in the transcript, `panel` in
    the persistent side panel (the constraint view), `progress` in the
    research timeline.
    """
    return AgentEvent(
        kind=EventKind.UI, data={"surface": surface, "component": component}
    )


def a2ui_message(message: dict[str, Any], surface: str = "inline") -> AgentEvent:
    """One A2UI envelope.

    `surface` is a placement hint for the client — `inline` in the
    transcript, `panel` in the persistent side column. It is not part of the
    A2UI protocol; the protocol's own surfaceId identifies *what* is being
    updated, while this says *where* it belongs in the page.
    """
    return AgentEvent(
        kind=EventKind.A2UI, data={"placement": surface, "message": message}
    )


def state_event(state: SessionState) -> AgentEvent:
    return AgentEvent(kind=EventKind.STATE, data=state.panel())


def done_event(state: SessionState) -> AgentEvent:
    return AgentEvent(
        kind=EventKind.DONE,
        data={"phase": state.phase.value, "session_id": state.session_id},
    )


def error_event(text: str, recoverable: bool = True) -> AgentEvent:
    return AgentEvent(
        kind=EventKind.ERROR, data={"text": text, "recoverable": recoverable}
    )


# --------------------------------------------------------------------------
# Runner protocol
# --------------------------------------------------------------------------


class AgentRunner(Protocol):
    """Anything that can take a user message and emit events.

    Defined as a protocol so the transport, the API layer and the client can
    all be built and tested before the model loop exists — and so the eval
    harness can substitute a deterministic runner for a real one.
    """

    async def run_turn(
        self, state: SessionState, user_message: str
    ) -> AsyncIterator[AgentEvent]:  # pragma: no cover - interface
        ...


async def stream_sse(events: AsyncIterator[AgentEvent]) -> AsyncIterator[str]:
    """Adapt an event stream into SSE frames, reporting failures in-band.

    An exception mid-turn must reach the client as an `error` event rather
    than a truncated body, or the UI will sit waiting for a turn that has
    already died.
    """
    try:
        async for event in events:
            yield event.to_sse()
    except Exception as exc:  # noqa: BLE001 - surfaced to the client
        yield error_event(f"The turn failed: {exc}", recoverable=True).to_sse()
