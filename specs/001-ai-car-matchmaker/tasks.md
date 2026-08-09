# Tasks — AI Car Matchmaker

**Feature:** `001-ai-car-matchmaker`
**Derived from:** `plan.md`
## Status

Phases 1-3 complete. T042-T045 (observability and evals) descoped against the
deadline — see `plan.md` section 13. A2UI work was added after the original
breakdown and appears as T060-T063 below.

**Convention:** `[P]` marks tasks with no dependency on the immediately preceding task. Each task is one commit. Every task cites the requirement it serves.

---

## Phase 1 — Foundation and Inventory

*Exit criterion: a CLI query returns deterministically filtered listings.*

- **T001** Scaffold Python backend with `uv`; add FastAPI, uvicorn, pydantic, sse-starlette, httpx, sqlalchemy, python-dotenv; add pytest and ruff as dev dependencies. Verify `/health` responds.
- **T002** Define the `Listing` ORM model and Pydantic schemas — id, mode availability, category, brand, model, year, price, rent_per_day, km, fuel, transmission, seats, city, availability windows, seller type, image reference. *(FR-010, FR-028)*
- **T003** Define the category and brand taxonomy: 12 categories, 10 brands each, as a versioned data file rather than inline constants. *(FR-026)*
- **T004** Write the deterministic inventory generator — seeded RNG, 120+ listings, plausible price/year/mileage correlations, both INR and EUR pricing. Assert that two runs produce content-identical rows. *(FR-026, FR-027)*
- **T005** `[P]` Write the repository layer: filter queries across every field in FR-010, with pagination and total match count. *(FR-010)*
- **T006** Write a CLI query script for manual verification of the repository layer. Not shipped in the final app; kept as a debugging tool.
- **T007** `[P]` Unit tests for the generator (determinism, distribution across categories and brands) and the repository (each filter dimension in isolation, then combined).

---

## Phase 2 — Protocol Layer

*Exit criterion: all three MCP servers working in the MCPJam inspector, both Apps rendering and round-tripping data. Do not begin Phase 3 until this passes.*

- **T008** **Read the current specs first.** Confirm `_meta` key names against `modelcontextprotocol/ext-apps` (specification 2026-01-26 or later) and record the confirmed shape in `docs/architecture.md`. Do not write server code from memory or from tutorials. *(Constitution II)*
- **T009** Scaffold the `marketplace` MCP server with stdio transport; implement `search_listings`. Verify in MCPJam. *(FR-008, FR-010)*
- **T010** Implement `compare_listings` and `check_availability` on the same server. *(FR-010)*
- **T011** `[P]` Assert text content blocks are returned by every tool alongside structured payloads. *(Constitution VII)*
- **T012** Scaffold the `booking-form` MCP server. Register `ui://booking/form` as a UI resource; implement `open_booking_form` with prefill parameters. *(FR-017, FR-018)*
- **T013** Build the booking form UI: prefilled but editable fields, inline validation, submit and cancel. *(FR-018, FR-019)*
- **T014** Implement the iframe→server round trip for booking: `submit_booking`, `validate_field`, `cancel`. Verify in MCPJam. *(FR-017)*
- **T015** Scaffold the `checkout` MCP server. Register `ui://checkout/payment`; implement `open_checkout`. *(FR-020)*
- **T016** Build the checkout UI: persistent simulation banner, allowlisted fake test values only, explicit rejection of anything else. *(FR-020, FR-021)*
- **T017** Implement confirmation record issuance — listing, terms, dates, reference id. *(FR-022)*
- **T018** `[P]` Write a test asserting that no payment-processing library appears anywhere in the dependency tree. *(Constitution V)*

---

## Phase 3 — Agent and Frontend

*Exit criterion: full flow in the browser, interview through confirmation.*

### 3a. Agent core

- **T019** Implement `SessionState`, `ConstraintSet`, `ReasoningRecord`, and the session store. *(FR-023, FR-025)*
- **T020** Implement the phase machine with deterministic guards. The orchestrator enforces transitions; the agent only proposes them. *(FR-001, FR-023)*
- **T021** Implement per-phase tool scoping so search tools are unavailable during the interview. *(FR-001)*
- **T022** Wire the Claude Agent SDK loop; connect the three MCP servers as clients.
- **T023** Implement `update_slots` and out-of-order slot capture. *(FR-004)*
- **T024** Implement conflict detection and `flag_conflict`. *(FR-006)*
- **T025** Implement `revise_constraints` — mode-independent slots survive a mode change, mode-dependent slots reset. *(FR-007, Scenario C)*
- **T026** Implement scoring: hard-constraint filtering, then per-criterion scoring 0–1. *(FR-012)*
- **T027** Implement bounded weight inference with fixed fallback and `weight_source` reporting. *(FR-012, Q2)*
- **T028** Implement `ReasoningRecord` emission for every ranked listing. *(FR-013)*
- **T029** Implement buy-vs-rent TCO computation. *(FR-015)*
- **T030** Implement empty-result handling — identify the binding constraint, propose a relaxation with its cost. *(FR-016)*

### 3b. Transport and A2UI

- **T031** **Confirm the current A2UI component schema and data-binding model at a2ui.org.** Record the confirmed shape in `docs/architecture.md`. *(Constitution II)*
- **T032** Implement the SSE event endpoint streaming A2UI frames and agent events. *(FR-009)*
- **T033** Scaffold the Next.js frontend; implement the A2UI renderer core and component resolution.
- **T034** `[P]` Build interview components: `ConstraintPanel`, `RangeInput`, `DateWindowInput`, `ChoiceChips`. *(FR-003, FR-005)*
- **T035** `[P]` Build `ProgressTimeline` for live research state. *(FR-009)*
- **T036** `[P]` Build result components: `CarCard`, `RankedList`, `ReasoningTrace`. *(FR-013, FR-014)*
- **T037** `[P]` Build `TcoComparison` and `ConflictNotice`. *(FR-006, FR-015, FR-016)*

### 3c. Host bridge

- **T038** Implement the iframe host: explicit sandbox policy, origin validation on every inbound message. *(Constitution II)*
- **T039** Implement JSON-RPC over `postMessage` with a method allowlist; reject anything not explicitly permitted.
- **T040** Relay permitted calls to the correct MCP server; log every relayed call for tracing. *(FR-029)*
- **T041** Integrate both Apps into the conversation flow so booking and checkout never navigate away. *(FR-017, FR-020)*

---

## Phase 4 — Observability, Hardening, Submission

- **T042** Instrument the backend with OpenTelemetry: root span per session, child per phase, leaf per tool and model call. *(FR-029)*
- **T043** Export to Langfuse; verify a full session appears as a coherent trace tree.
- **T044** Build the eval fixture harness — scenario definitions plus assertion helpers.
- **T045** Write eval cases: interview completeness, budget adherence, mode switch, conflict detection, empty results, weight bounds, explanation completeness. Minimum 20 total. *(FR-030)*
- **T046** `[P]` Write Dockerfiles for backend, frontend, and MCP servers.
- **T047** Write `docker-compose.yml` including an idempotent seed step. *(Constitution VI)*
- **T048** Verify from a clean clone: `git clone` → follow README → working app. Do this on a fresh directory, not your working tree. *(Constitution VI)*
- **T049** `[P]` Write `README.md`: what it does, architecture summary, run instructions, protocol notes, environment variables.
- **T050** `[P]` Write `docs/demo-script.md` — the scripted happy path plus Scenario C and Scenario E.
- **T051** Record the video demo. Include the mid-flow mind-change and one empty-result case; do not demo only the happy path.
- **T052** Build the slide deck from the provided template.
- **T053** `[P]` Optional public deployment in addition to the Docker submission.

---

## Optional — Stretch (Q4)

*Attempt only if Phase 3 completes ahead of schedule. Dropping this section breaks no acceptance criterion.*

- **T054** Implement `compare_listings` invocation from the recommendation UI.
- **T055** Build the `ComparisonTable` A2UI component.
- **T056** Add eval cases for comparison correctness.

---

## Dependency Notes

- T008 blocks T009–T017. T031 blocks T033–T037.
- Phase 2 must fully pass in MCPJam before Phase 3 begins. This is the single most important sequencing constraint in the project.
- T038–T041 depend on Phase 2 being complete but are independent of 3a.
- T048 must run before T051; do not record a demo of an app that has not been verified from a clean clone.


---

## Phase 5 — A2UI (added after the original breakdown)

- **T060** Define the A2UI v1.0 component catalog — CarCard, RankedCarCard,
  ContributionBar, ConstraintPanel, ProgressTimeline, TcoComparison,
  ConflictNotice — with `instructions` telling the agent to use them rather
  than composing from primitives. *(Done)*
- **T061** Build surface constructors emitting createSurface,
  updateComponents, updateDataModel and deleteSurface. The constraint panel
  sends structure once and data thereafter. *(Done)*
- **T062** Client-side surface store: adjacency list, JSON Pointer
  resolution, list templates with per-item scope, renderer-side functions.
  *(Done)*
- **T063** React renderer dispatching component names to the catalog's
  implementations, with actions resolving context bindings at dispatch.
  *(Done)*
