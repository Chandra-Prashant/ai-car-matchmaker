"""Session persistence.

Serves FR-025: a session survives page reload without losing gathered
constraints.

Scope decision (spec Q, FR-025): single-browser persistence only. The session
id lives in a cookie; cross-device resumption is explicitly out of scope and
would add no judged value.

Storage shape: queryable fields are columns, the state itself is a JSON blob.
The state model will change repeatedly over the next few weeks and writing
migrations for a demo database is wasted effort. If the shape ever needs
querying — "all sessions that reached checkout" — promote that field to a
column then.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime

from sqlalchemy import DateTime, String, Text, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.models.listing import Base
from app.state.models import Phase, SessionState


class SessionRow(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    phase: Mapped[str] = mapped_column(String(16), index=True)
    state_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime, index=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<SessionRow {self.id} {self.phase}>"


def new_session_id() -> str:
    return f"ses-{secrets.token_hex(8)}"


class SessionStore:
    """Load and save agent sessions.

    The caller owns the SQLAlchemy session; this class owns the mapping
    between `SessionState` and its stored row.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, session_id: str | None = None) -> SessionState:
        state = SessionState(session_id=session_id or new_session_id())
        self._insert(state)
        return state

    def get(self, session_id: str) -> SessionState | None:
        row = self._session.get(SessionRow, session_id)
        if row is None:
            return None
        return SessionState.model_validate_json(row.state_json)

    def get_or_create(self, session_id: str | None) -> SessionState:
        """Resume if the id is known, start fresh otherwise.

        Tolerating an unknown id rather than raising means a stale cookie
        gives the user a new session instead of an error page.
        """
        if session_id:
            existing = self.get(session_id)
            if existing is not None:
                return existing
        return self.create(session_id)

    def save(self, state: SessionState) -> None:
        state.touch()
        row = self._session.get(SessionRow, state.session_id)
        if row is None:
            self._insert(state)
            return
        row.phase = state.phase.value
        row.state_json = state.model_dump_json()
        row.updated_at = state.updated_at
        self._session.flush()

    def delete(self, session_id: str) -> bool:
        row = self._session.get(SessionRow, session_id)
        if row is None:
            return False
        self._session.delete(row)
        self._session.flush()
        return True

    def recent(self, limit: int = 20) -> list[SessionState]:
        """Most recently updated sessions — for the trace view and debugging."""
        rows = self._session.scalars(
            select(SessionRow).order_by(SessionRow.updated_at.desc()).limit(limit)
        ).all()
        return [SessionState.model_validate_json(row.state_json) for row in rows]

    def count_by_phase(self) -> dict[str, int]:
        counts = dict.fromkeys((p.value for p in Phase), 0)
        for row in self._session.scalars(select(SessionRow)).all():
            counts[row.phase] = counts.get(row.phase, 0) + 1
        return counts

    # ----------------------------------------------------------------

    def _insert(self, state: SessionState) -> None:
        now = datetime.now(UTC)
        self._session.add(
            SessionRow(
                id=state.session_id,
                phase=state.phase.value,
                state_json=state.model_dump_json(),
                created_at=now,
                updated_at=now,
            )
        )
        self._session.flush()
