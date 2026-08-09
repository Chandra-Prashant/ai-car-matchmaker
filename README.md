# AI Car Matchmaker

A multistep agent that helps you find a car to buy or rent. It interviews you
conversationally, searches real inventory through MCP tools, ranks the results
against weights inferred from your own priorities, and shows exactly why each
car placed where it did — then books it through MCP Apps rendered inside the
conversation.

Built for the Amulate Summer Hackathon 2026.

---

## What it does

**Interviews rather than filters.** The agent asks one thing at a time,
records what you volunteer in any order, and detects when your requirements
cannot all be satisfied — telling you which constraint is binding and what
relaxing it would find, computed from the catalogue rather than guessed.

**Ranks with inferred weights.** Say your budget is tight and you don't care
about age, and the agent shifts the criterion weights accordingly. The same
shortlist reorders, and a stacked contribution bar shows each criterion's
weighted contribution to every score.

**Compares buying against renting.** For a fixed-duration need it computes
total cost both ways — depreciation, registration, resale friction, carrying
costs — and reports the crossover point at which buying overtakes renting.

**Books without leaving the chat.** The booking form and the mock checkout are
real MCP Apps: `ui://` resources served by MCP servers, rendered in a
sandboxed View on a separate origin, talking back over JSON-RPC.

---

## Architecture

```
Browser (host, :3000)                    Sandbox proxy (:3001)
  ├── A2UI renderer ──── surfaces          └── View iframe (host CSP)
  └── MCP Apps host ───────────────────────────┘  postMessage JSON-RPC
            │ SSE
  FastAPI (:8000)
            │
  Agent loop — interview → research → recommend → book
            │
  ┌─────────┼──────────────┬─────────────────┐
  marketplace       booking-form        checkout
  (MCP server)      (MCP App)           (MCP App)
            │
  SQLite — 183 listings, 12 categories, 10 brands each
```

### Multistep orchestration

Phase transitions are **authorised by the state machine, not the model**. The
agent may propose a move; `app/agent/phases.py` decides whether it is
permitted by inspecting session state. Research cannot begin before the five
required slots are filled — not because the prompt says so, but because the
search tools are not in the tool list until then.

When a transition is refused, the refusal is returned to the model as a tool
result naming what is missing, so it self-corrects by asking the user.

Every rule here is unit-tested without an API key: `backend/tests/test_phases.py`.

### A2UI

Catalogues, ranked results and the constraint panel are described by the agent
as A2UI v1.0 messages and rendered by the client's own components. A custom
catalog (`backend/app/a2ui/catalog.py`) declares the vocabulary — `CarCard`,
`RankedCarCard`, `ContributionBar` — so the agent names components and binds
data while the client owns how they look.

The constraint panel demonstrates the protocol's structure/data split: its
component tree is sent once per turn, and every subsequent change travels as a
single `updateDataModel`.

Ranked cards carry A2UI actions. "Book this one" dispatches an action whose
context bindings resolve against that card's item scope, and the agent
responds — the UI drives the conversation, not just the other way round.

### MCP Apps

Three MCP servers, two of which expose UI:

| Server | Tools | UI resource |
|---|---|---|
| `marketplace` | search, compare, availability | — |
| `booking-form` | `open_booking_form` (model), `submit_booking` and `validate_booking_field` (app-only) | `ui://booking/form` |
| `checkout` | `open_checkout` (model), `submit_payment` (app-only) | `ui://checkout/payment` |

Per SEP-1865, the browser renders each View through a **sandbox proxy on a
separate origin** — that origin separation, not the iframe sandbox attribute,
is the containment boundary. The host constructs the CSP; the View never
chooses its own.

A View may only call tools its server marks `visibility: ["app"]`. The
allowlist is read from the server's own metadata, so it cannot drift.

### Payments are simulated

There is no payment library anywhere in the dependency tree, and a test
asserts it. The checkout accepts only an allowlist of obviously-fake card
numbers — **deliberately without a Luhn check**, since passing Luhn would mean
accepting a real card.

---

## Running it

### Prerequisites

- Docker, or: Python 3.12 + [uv](https://docs.astral.sh/uv/) + Node 20
- A model provider API key (see below)

### With Docker

```bash
git clone https://github.com/Chandra-Prashant/ai-car-matchmaker
cd ai-car-matchmaker
cp .env.example .env      # add your key
docker compose up --build
```

Open http://localhost:3000

### Without Docker

```bash
cp .env.example .env      # add your key

cd backend
uv sync
uv run python -m app.inventory.generator    # seed the catalogue
cd ..

cd frontend && npm install && cd ..

./dev.sh                  # starts all three services
```

### API key

The agent is provider-agnostic — it speaks the OpenAI chat-completions shape,
so any compatible endpoint works. Set two variables in `.env`:

```
LLM_PROVIDER=gemini
LLM_MODEL=gemini-3.5-flash
GEMINI_API_KEY=your-key-here
```

**Google AI Studio** (https://aistudio.google.com) has a free tier with no
card required, which is what this was developed against. `LLM_PROVIDER` also
accepts `anthropic`, `openai`, `groq` and `ollama`.

> Free-tier quotas are small — a full conversation costs 6–8 requests. If you
> hit a rate limit, either switch `LLM_MODEL` or use the scripted runner
> described below.

### Trying it without a model

A deterministic runner drives the same tools, phases and surfaces with no
model involved — used by the eval harness and useful for reproducible demos:

```bash
curl -N -X POST "http://localhost:8000/api/sessions/$SID/turn" \
  -H 'Content-Type: application/json' \
  -d '{"message":"book it","script":"booking"}'
```

Available scripts: `rental`, `mode_change`, `empty`, `booking`.

---

## Try these

| Prompt | What it demonstrates |
|---|---|
| `I need to rent a 7-seater MPV for a family trip in September, up to ₹3,500 a day` | Full interview → search → ranked results |
| then `Actually my budget is tight — nothing over ₹2,200 a day, and I don't care how old the car is` | Weight inference: the same shortlist reorders, and the contribution bar shifts |
| `A luxury SUV under ₹7 lakh` | Conflict detection: names the binding constraint and quantifies the relaxation |
| `I need a car for six weeks — not sure whether to rent or buy` | Buy-vs-rent cost comparison with a crossover point |
| then `Book the top one for me` | MCP Apps: booking form and mock checkout inside the conversation |

Checkout test cards: `0000000000000001` approves, `4000000000000002` declines.
Anything else is rejected as not-a-test-card.

---

## Development

Built with [spec-kit](https://github.com/github/spec-kit). The specification,
implementation plan and task breakdown are in `specs/001-ai-car-matchmaker/`,
and the project constitution — the non-negotiable principles, including that
protocols are implemented rather than simulated — is in
`.specify/memory/constitution.md`.

Git history follows the task breakdown: commits are tagged with the task they
implement, so `git log --oneline` reads back as the plan.

```bash
cd backend
uv run pytest -q          # 104 tests, no API key required
uv run ruff check app tests
```

`docs/architecture.md` records the confirmed MCP Apps protocol shape as
verified against the specification, plus known limitations.

### Layout

```
backend/app/
  a2ui/          A2UI catalog and surface builders
  agent/         phase machine, interview tools, ranking, TCO, model runner
  api/           session API, SSE stream, MCP host bridge
  inventory/     deterministic catalogue generator
  mcp_servers/   marketplace, booking-form, checkout
  models/        Listing, Booking
  repositories/  query layer
  state/         session state and store
frontend/
  components/a2ui/       A2UI renderer and catalog implementations
  components/mcp-host/   MCP Apps host
  lib/a2ui/              surface store, binding resolution
sandbox/         MCP Apps sandbox proxy (separate origin)
specs/           spec, plan, tasks
```

---

## Known limitations

- Model launch years are not modelled, so a listing may carry a model year
  predating that model's real introduction. Recorded in
  `docs/architecture.md`.
- EUR prices derive from INR at a fixed declared rate; real prices diverge
  between markets for reasons this does not model.
- Session persistence is single-browser by design; cross-device resumption is
  out of scope.
