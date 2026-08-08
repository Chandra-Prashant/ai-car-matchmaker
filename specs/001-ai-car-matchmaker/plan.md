# Implementation Plan — AI Car Matchmaker

**Feature:** `001-ai-car-matchmaker`
**Input:** `specs/001-ai-car-matchmaker/spec.md`
**Constitution:** `.specify/memory/constitution.md`
**Status:** Draft

---

## 1. Constitution Check

| Principle | How this plan satisfies it |
|---|---|
| I. Spec before code | Every section below traces to an FR. Tasks derive from this plan, not from ad-hoc coding. |
| II. Protocols used honestly | Section 7 defines real `ui://` resources and a genuine host-side JSON-RPC bridge. Section 8 defines A2UI as declarative JSON, never HTML from the agent. |
| III. Agent state explicit | Section 5 defines `SessionState` as a serialisable Pydantic model with deterministic phase guards. |
| IV. Every recommendation explained | Section 6.3 defines a mandatory `ReasoningRecord` attached to every ranked result. |
| V. Mock transaction safety | Section 7.3: no payment SDK is installed at all; card fields accept only a fixed set of obviously-fake test numbers. |
| VI. Reproducible from zero | Section 9: Docker Compose, seeded RNG, single `README.md` path. |
| VII. Graceful degradation | Every MCP tool returns a text `content` block in addition to any UI metadata. |
| VIII. Observable by default | Section 10: OpenTelemetry spans on every phase and tool call, exported to Langfuse. |

No violations. No complexity exceptions requested.

---

## 2. Resolved Open Questions

**Q1 — Interview ordering.** *Adaptive.* The agent asks for whichever required slot is missing, prioritised by information gain, and never re-asks a filled slot. Satisfies FR-002 and FR-004.

**Q2 — Ranking weights.** *Inferred with fixed fallback.* Hard constraints (budget ceiling, date window, minimum seats) are filters and are never traded off. Soft criteria (year, mileage, fuel, transmission, brand affinity) receive base weights that the agent may adjust within a bounded range based on emphasis in the user's own phrasing. If inference fails or produces out-of-range weights, the fixed base weights apply. Rationale: demonstrates genuine agent reasoning while keeping FR-013's score breakdown explainable and testable. *Reversible decision — reverting to purely fixed weights touches only `ranking.py`.*

**Q3 — Mixed result sets.** *Never mixed.* Rental and purchase results are always separate ranked sets. When mode is undecided, FR-015's cost comparison is presented first and the user chooses a mode before results render.

**Q4 — Side-by-side compare.** *Stretch goal, not a functional requirement.* Implemented only if Week 3 completes ahead of schedule. Tracked in `tasks.md` under a clearly marked optional section so that dropping it does not break acceptance criteria.

---

## 3. Technical Context

| Concern | Choice | Rationale |
|---|---|---|
| Language (backend) | Python 3.12 | Agent SDK and MCP SDK are Python-first; matches existing skill set. |
| Agent harness | Claude Agent SDK | Native MCP client support removes an entire integration layer. Permitted by challenge rules. |
| Web framework | FastAPI | Async, Pydantic-native, SSE-friendly. |
| Agent → client transport | SSE over HTTP | A2UI messages stream to the client; SSE is sufficient (unidirectional) and far simpler than WebSockets. Client → agent uses ordinary POST. |
| Frontend | Next.js (App Router) + TypeScript + Tailwind | A2UI renderer and MCP Apps host both live here. |
| Persistence | SQLite via SQLAlchemy | Zero-ops, file-backed, trivially reproducible in Docker. Postgres is unnecessary at 120 listings. |
| Session store | SQLite table, session id in a cookie | Satisfies FR-025 at single-browser scope. |
| MCP servers | Python MCP SDK, stdio transport locally | Three separate servers (Section 7). |
| Observability | OpenTelemetry SDK → Langfuse | Satisfies FR-029 and the challenge bonus. |
| Evals | pytest + recorded transcripts | Satisfies FR-030. |
| Packaging | Docker Compose (backend, frontend, mcp servers) | Satisfies submission requirement. |

**Dependency note:** no payment library of any kind is added to the project. This is deliberate and is asserted by a test.

---

## 4. Repository Structure

```
backend/
  app/
    main.py                 FastAPI entrypoint, SSE endpoint
    agent/
      orchestrator.py       phase machine, agent loop
      phases.py             phase definitions and guards
      prompts/              system + phase prompts (versioned files)
      ranking.py            scoring, weight inference, explanation
      tco.py                buy-vs-rent cost comparison (FR-015)
    api/
      session.py            create/resume/inspect session
      events.py             SSE stream of A2UI frames + agent events
      mcp_bridge.py         host-side JSON-RPC relay for MCP Apps
    state/
      models.py             SessionState, ConstraintSet, Shortlist
      store.py              persistence
    models/
      listing.py            Listing ORM + Pydantic schemas
      reasoning.py          ReasoningRecord
mcp-servers/
  marketplace/              search/filter/compare tools (plain MCP)
  booking-form/             MCP App — ui://booking/form
  checkout/                 MCP App — ui://checkout/payment
frontend/
  app/                      Next.js routes
  components/
    a2ui/                   A2UI renderer + component catalog (Section 8)
    mcp-host/               iframe host, postMessage bridge, sandbox policy
data/
  generator/seed.py         deterministic inventory generator
  seed/marketplace.db       generated, gitignored
evals/
  cases/                    scenario fixtures
  test_agent_behaviour.py
docs/
  architecture.md
  demo-script.md
```

---

## 5. State Model

```python
class ConstraintSet(BaseModel):
    mode: Literal["buy", "rent"] | None
    use_case: str | None
    category: str | None
    budget_min: int | None
    budget_max: int | None
    target_date: date | None
    duration_days: int | None
    seats_min: int | None
    fuel: str | None
    transmission: str | None
    brand_affinity: list[str]

class SessionState(BaseModel):
    session_id: str
    phase: Literal["interview", "research", "recommend", "book", "complete"]
    constraints: ConstraintSet
    inferred_weights: dict[str, float]
    shortlist: list[str]
    reasoning_log: list[ReasoningRecord]
    conflicts: list[Conflict]
    history: list[TurnRecord]
```

**Phase guards are deterministic, not model-decided.** `interview → research` requires the five FR-001 slots to be non-null and `conflicts` to be empty. The agent may *propose* a transition; the orchestrator enforces it. This is what makes FR-023 demonstrable rather than aspirational.

**Mid-flow mode change (Scenario C)** is handled by a `revise_constraints` tool that recomputes which slots survive: mode-independent slots (seats, fuel, use case) persist; mode-dependent slots (budget semantics, duration) reset and are re-elicited.

---

## 6. Agent Design

### 6.1 Phases

| Phase | Agent's job | Tools available |
|---|---|---|
| Interview | Elicit missing slots, detect conflicts | `update_slots`, `emit_input_control`, `flag_conflict` |
| Research | Query inventory, narrow to ≤10 | `search_listings`, `compare_listings`, `check_availability` |
| Recommend | Score, rank, explain | `rank_shortlist`, `compute_tco` |
| Book | Drive the two MCP Apps | `open_booking_form`, `open_checkout` |

Tool availability is scoped per phase. The agent cannot search during the interview — this enforces FR-001 structurally rather than by prompt instruction.

### 6.2 Ranking (Q2 resolution)

1. **Filter** on hard constraints. A listing violating budget ceiling, date window, or minimum seats is removed, never down-weighted.
2. **Infer weights.** Agent proposes adjustments to base weights from user phrasing, bounded to ±0.15 per criterion, renormalised to sum to 1.
3. **Score** each surviving listing per criterion, 0–1.
4. **Rank** by weighted sum.
5. **Explain** — emit a `ReasoningRecord` per listing.

### 6.3 Reasoning Record

```python
class ReasoningRecord(BaseModel):
    listing_id: str
    rank: int
    total_score: float
    matched: list[str]          # constraints satisfied
    tradeoffs: list[str]        # constraints compromised, with magnitude
    breakdown: dict[str, float] # criterion → weighted contribution
    weight_source: Literal["inferred", "fallback"]
```

`weight_source` is deliberately exposed in the UI. It is honest, and it makes the Q2 design visible to a judge.

---

## 7. MCP Layer

> **Verify before implementing:** field names below follow the MCP Apps extension (`io.modelcontextprotocol/ui`). Confirm the exact `_meta` keys against the current specification in `modelcontextprotocol/ext-apps` before writing server code — this extension is young and key names have moved.

### 7.1 `marketplace` server (plain MCP, optional per challenge)

| Tool | Input | Output |
|---|---|---|
| `search_listings` | mode, category, price range, year, km, fuel, transmission, seats, city, date window | listings + total match count |
| `compare_listings` | listing ids | aligned attribute matrix |
| `check_availability` | listing id, date window | boolean + alternative windows |

All return text content blocks. Structured payloads travel in `structuredContent`.

### 7.2 `booking-form` server (MCP App — mandatory)

- Registers resource `ui://booking/form` with mimetype `text/html;profile=mcp-app`.
- Tool `open_booking_form` references it via `_meta`, and passes prefill values drawn from `SessionState` (FR-018).
- Iframe → host calls: `submit_booking`, `validate_field`, `cancel`.
- Host → iframe: initial data payload, validation errors.
- Text fallback: a plain-text summary of the booking fields, so non-UI hosts still function (Constitution VII).

### 7.3 `checkout` server (MCP App — mandatory)

- Registers resource `ui://checkout/payment`.
- Tool `open_checkout` takes booking id and amount.
- The UI displays a persistent, non-dismissible simulation banner.
- Card field accepts only a hardcoded allowlist of obviously-fake test values; anything else is rejected with "simulation only". No Luhn validation, because passing Luhn would make real numbers acceptable.
- Returns a confirmation record satisfying FR-022.

### 7.4 Host bridge (frontend)

This is the highest-risk component. Requirements:

- Render each UI resource in an iframe with an explicit `sandbox` attribute; no `allow-same-origin` combined with `allow-scripts` against a trusted origin.
- Implement JSON-RPC over `postMessage`, validating message origin on every inbound message.
- Relay permitted method calls to the MCP server; reject anything not on an explicit allowlist.
- Enforce a per-app capability list; log every relayed call for the trace (FR-029).

Build and debug this against the MCPJam inspector **before** wiring it into the Next.js app.

---

## 8. A2UI Layer

The agent emits declarative component/data JSON. The frontend owns all styling and maps component types to React components. The agent never emits HTML for these surfaces (Constitution II).

**Component catalog** (client-side, agent-referenceable):

| Component | Purpose | FR |
|---|---|---|
| `ConstraintPanel` | Live view of gathered slots | FR-005 |
| `RangeInput` | Budget elicitation | FR-003 |
| `DateWindowInput` | Target date / duration | FR-003 |
| `ChoiceChips` | Category, fuel, transmission | FR-003 |
| `ProgressTimeline` | Research steps, query in flight, candidates remaining | FR-009 |
| `CarCard` | Single listing summary | FR-014 |
| `RankedList` | Ordered result set | FR-012, FR-014 |
| `ReasoningTrace` | Expandable breakdown per listing | FR-013 |
| `TcoComparison` | Buy vs rent over duration | FR-015 |
| `ConflictNotice` | Unsatisfiable constraint + relaxations | FR-006, FR-016 |
| `ComparisonTable` | *(stretch, Q4)* | — |

> **Verify before implementing:** confirm the current A2UI component schema and data-binding model at a2ui.org. The specification is young; secondary tutorials may describe an older shape.

---

## 9. Deployment

- Compose services: `backend`, `frontend`, `mcp-marketplace`, `mcp-booking`, `mcp-checkout`.
- Seed step runs on first boot and is idempotent.
- `.env.example` committed; `.env` gitignored.
- A public deployment in addition to Docker, if time allows. Docker is the primary submission artifact.

---

## 10. Observability and Evaluation

**Traces.** One root span per session; child spans per phase; leaf spans per tool call and per model call. Attributes include phase, tool name, latency, token counts, and `weight_source`.

**Eval suite** (minimum 20 cases):

- Interview completeness — research never begins with a null required slot.
- Budget adherence — no returned listing exceeds the stated ceiling.
- Mode switch — Scenario C retains mode-independent slots and discards the rest.
- Conflict detection — mutually unsatisfiable inputs produce a `ConflictNotice`, not a silent drop.
- Empty results — binding constraint is named and a relaxation is offered.
- Weight bounds — inferred weights stay within ±0.15 and renormalise correctly.
- Explanation completeness — every ranked listing carries a full `ReasoningRecord`.

---

## 11. Risks

| Risk | Mitigation |
|---|---|
| Host bridge takes longer than budgeted | Built and proven in MCPJam before frontend integration; it is the Week 2 exit criterion, not a Week 3 task. |
| A2UI or MCP Apps spec drift | Both flagged above; verify against primary sources at implementation time, not from memory or tutorials. |
| Agent loops or stalls mid-interview | Deterministic phase guards plus a hard turn cap per phase. |
| Demo fragility | Seeded data, recorded fallback video, and a scripted happy path in `docs/demo-script.md`. |
| Scope creep via Q4 | Explicitly optional; dropping it breaks no acceptance criterion. |

---

## 12. Phase Sequencing

| Week | Exit criterion (must be demoable) |
|---|---|
| 1 | Inventory generated; CLI query returns filtered listings deterministically. |
| 2 | All three MCP servers working in MCPJam, including both Apps rendering and round-tripping data. |
| 3 | Full flow in the browser: interview → research → ranked results → booking → mock checkout → confirmation. |
| 4 | Traces in Langfuse, eval suite green, Compose up from clean clone, README, deck, video. |
