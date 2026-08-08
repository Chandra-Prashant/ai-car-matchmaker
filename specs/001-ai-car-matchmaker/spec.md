# Feature Specification — AI Car Matchmaker

**Feature branch:** `001-ai-car-matchmaker`
**Status:** Draft
**Scope:** A multistep conversational agent that interviews a user about their
car needs, researches available listings on their behalf, presents ranked and
explained recommendations, and completes a simulated booking or purchase.

This document describes *what* the system does and *why*. It deliberately names
no frameworks, libraries, or languages; those belong in `plan.md`.

---

## 1. Problem Statement

A person who needs a car — to rent for a trip or to buy outright — currently
compares listings across many marketplaces manually, each with its own filters
and none of which understand the actual use case. The comparison is mechanical
(price, mileage, seats) while the real decision is contextual: a four-day trip
with three passengers and a tight budget is a different problem from a daily
commute purchase held for five years.

The system replaces that manual search with an agent that elicits the real
constraint set through conversation, searches on the user's behalf, and returns
a small ranked set of options with the reasoning made visible.

---

## 2. User Scenarios

### Scenario A — Rental, clear intent
A user opens the app and says they need a car for a weekend trip. The agent asks
about passenger count, dates, budget per day, and preferred category, presenting
interactive controls where a control is faster than typing. Once the constraint
set is complete, the agent searches, returns five ranked rental options with
per-option reasoning, and the user books one through an in-conversation form and
a simulated payment step, receiving a confirmation.

### Scenario B — Purchase, vague intent
A user says only that they are "thinking about buying something practical". The
agent progressively narrows: intended use, family size, fuel preference, budget
ceiling, timeframe. It surfaces trade-offs the user did not state (for example,
that their budget and their seat requirement conflict) and asks them to resolve
the conflict rather than silently dropping a constraint.

### Scenario C — Mid-flow change of mind
Partway through a purchase interview the user says they now only need the car
for six weeks. The agent recognises the mode change, retains the constraints that
still apply, discards those that do not, re-runs research against rental
inventory, and explains the switch.

### Scenario D — Buy versus rent undecided
A user does not know whether to rent or buy for their stated duration. The agent
computes and presents a cost-of-ownership comparison over that duration and
recommends a mode with justification, then proceeds down the chosen path.

### Scenario E — Empty result set
The constraint set matches no inventory. The agent reports this plainly, names
which constraint is binding, and offers specific relaxations with the cost of
each, rather than returning poor matches without comment.

---

## 3. Functional Requirements

### 3.1 Interview

- **FR-001** The system MUST collect, before any research begins: mode (buy or
  rent), use case, vehicle category, budget range, and target date or date range.
- **FR-002** The system MUST conduct collection conversationally, asking about
  missing information rather than presenting a single upfront form.
- **FR-003** The system MUST present interactive input controls inside the
  conversation where such a control is faster or less error-prone than free text
  (ranges, dates, single-choice sets).
- **FR-004** The system MUST accept information volunteered out of order and not
  re-ask for anything already supplied.
- **FR-005** The system MUST display the current known constraint set to the user
  at all times during the interview.
- **FR-006** The system MUST detect mutually unsatisfiable constraints and
  surface the conflict rather than resolving it silently.
- **FR-007** The system MUST allow any previously captured constraint to be
  amended at any later point, including after recommendations are shown.

### 3.2 Research

- **FR-008** The system MUST search inventory through a tool interface rather
  than from model recall, and MUST NOT invent listings.
- **FR-009** The system MUST expose research progress to the user while it runs:
  which step is executing, what is being queried, and how many candidates remain.
- **FR-010** The system MUST support filtering across at minimum: mode, category,
  brand, price or daily rate, year, mileage, fuel type, transmission, seat count,
  location, and availability window.
- **FR-011** The system MUST reduce a candidate set to a shortlist of at most ten
  options before ranking.

### 3.3 Recommendation

- **FR-012** The system MUST return options ranked against the elicited
  constraint set, not against a fixed default ordering.
- **FR-013** Each returned option MUST carry structured reasoning: which
  constraints it satisfies, which it violates or compromises, and a per-criterion
  score contribution.
- **FR-014** The system MUST render the catalogue of results as structured,
  agent-described interface content rather than as prose or static markup.
- **FR-015** Where mode is undecided, the system MUST produce a cost comparison
  between renting and buying across the user's stated duration.
- **FR-016** On an empty result set, the system MUST identify the binding
  constraint and propose at least one specific relaxation.

### 3.4 Booking and Checkout

- **FR-017** The booking or purchase-enquiry form MUST be completed inside the
  conversation without navigation away from it.
- **FR-018** The form MUST be pre-populated from information already gathered
  during the interview, and every pre-filled value MUST remain editable.
- **FR-019** The form MUST validate input and report validation failures inline.
- **FR-020** The checkout interface MUST be completed inside the conversation and
  MUST be an unambiguous simulation, labelled as such at every step.
- **FR-021** The system MUST NOT transmit, store, or request genuine payment
  credentials.
- **FR-022** On completion the system MUST issue a confirmation record containing
  the selected listing, agreed terms, dates, and a reference identifier.

### 3.5 State and Memory

- **FR-023** The system MUST maintain continuity of constraints, shortlist, and
  reasoning history across all phases of a session.
- **FR-024** The system MUST record and be able to replay the sequence of
  decisions taken during a session.
- **FR-025** A session MUST be resumable after page reload without loss of
  gathered constraints. [NEEDS CLARIFICATION: is cross-device resumption in
  scope, or is single-browser persistence sufficient for the demo?]

### 3.6 Inventory

- **FR-026** The inventory MUST contain at least 100 listings spanning at least
  10 categories, with at least 10 brands represented in each category.
- **FR-027** Inventory generation MUST be deterministic so that identical queries
  return identical results across runs.
- **FR-028** Listings MUST carry both purchase and rental representations where
  the category supports both.

### 3.7 Observability

- **FR-029** Every phase transition, tool invocation, and model call MUST emit a
  trace record.
- **FR-030** The system MUST ship an evaluation suite asserting agent behaviour,
  covering at minimum: completeness of interview before research, budget
  adherence in results, correct mode switching, and conflict detection.

---

## 4. Out of Scope

- Real payment processing of any kind.
- Integration with BMW Group systems or APIs.
- Live scraping of third-party marketplaces.
- User accounts, authentication, or multi-user separation.
- Financing, insurance, trade-in valuation, and delivery logistics.
- Localisation beyond a single interface language.

---

## 5. Acceptance Criteria

The feature is complete when a reviewer can, from a clean environment, follow the
repository README and:

1. Complete Scenario A end to end, from first message to confirmation record.
2. Complete Scenario C, observing constraints correctly retained and discarded.
3. Observe interview state and research progress rendered live during a session.
4. Complete the booking form and the simulated checkout without leaving the
   conversation.
5. Expand any recommendation and read its per-criterion reasoning.
6. Trigger Scenario E and receive a named binding constraint plus a relaxation.
7. Inspect traces for the session and run the evaluation suite to completion.

---

## 6. Open Questions

- **Q1** Should the interview enforce a fixed question order, or adapt ordering
  to the information the user volunteers first? *(Leaning adaptive; affects
  FR-002 and FR-004.)*
- **Q2** What is the ranking weight policy — fixed weights per criterion, or
  weights inferred from the emphasis in the user's own phrasing?
- **Q3** Should rental and purchase results ever appear in a single ranked list,
  or always as separate result sets? *(Interacts with FR-015.)*
- **Q4** Is a "compare these two" interaction in scope for the first iteration,
  or deferred?

Each open question is resolved in this document before the corresponding task is
started, per Constitution Principle I.
