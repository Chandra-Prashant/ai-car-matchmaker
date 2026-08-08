# Project Constitution — AI Car Matchmaker

Non-negotiable principles governing every plan, task, and implementation decision
in this project. If a proposed change violates a principle here, the change is
rejected or the constitution is amended first — never silently overridden.

## I. Spec Before Code

No implementation task begins without a corresponding entry in `tasks.md`, which
must trace to a requirement in `spec.md`. Ambiguity is resolved by amending the
spec, not by improvising in code. Git history must demonstrate this ordering.

## II. Protocols Are Used Honestly

Where the challenge mandates a protocol, that protocol is genuinely implemented,
not simulated.

- The booking form and payment/checkout interfaces are real MCP Apps: server-side
  `ui://` resources linked to tools via `_meta`, rendered by the host in a
  sandboxed iframe, communicating over JSON-RPC via `postMessage`.
- The car catalogue and agent-progress surfaces are driven by A2UI: the agent
  emits declarative component/data JSON; the client maps components to its own
  native widgets. The agent never emits HTML or executable code for these
  surfaces.
- A hand-rolled React modal styled to look like an MCP App is a constitutional
  violation, regardless of how convincing it appears in a demo.

## III. Agent State Is Explicit

Conversation memory across the interview, research, and recommendation phases
lives in an inspectable, serialisable state object — not implicitly in the LLM
context window. Phase transitions are governed by deterministic guards, not by
the model's discretion alone. The current state must be renderable to the user
at any moment.

## IV. Every Recommendation Is Explained

No ranked result is presented without machine-readable reasoning attached:
matched criteria, trade-offs accepted, and a score breakdown. A recommendation
the system cannot justify is a bug, not a result.

## V. Safety of the Mock Transaction

No real payment rail, no real payment credentials, no collection of genuine card
or bank data, and no live BMW Group APIs. The checkout flow is a clearly
labelled simulation end to end. Test data must be visibly synthetic.

## VI. Reproducible From Zero

A reviewer with only the repository and Docker installed must reach a working
application by following `README.md`, without contacting the author. Seeded data
is deterministic so that a demo run today matches a demo run next month.

## VII. Graceful Degradation

Tools return valid text results for hosts that do not support the MCP Apps
extension. Rich UI is an enhancement layer, never a hard dependency for
correctness.

## VIII. Observable By Default

Every agent phase, tool invocation, and model call is traced. Behavioural claims
about the agent are backed by an evaluation case, not by anecdote.

## Amendment Procedure

Amendments are committed as explicit changes to this file with a rationale in the
commit message. Downstream `plan.md` and `tasks.md` are re-checked for
consistency in the same commit.
