# Demo script

Toggle **Demo mode** in the header first — the flow then runs against the
deterministic runner, so it is reproducible and costs no model quota. Without
it the same four messages drive the real agent.

Reloading the page starts a fresh session, so there is no stale state to clear
between takes.

## The journey

1. `I need to rent a 7-seater for a family trip in September, up to ₹3,500 a day`

   Requirements are captured as they are spoken and appear in the panel on the
   right. The agent asks the one thing still missing.

2. `MPV`

   Search, shortlist and ranking run in sequence, tracked by the progress
   timeline. Matching listings appear as A2UI cards, then ranked
   recommendations with their reasoning.

   **Expand *how this score was reached* on the top card.** Each criterion's
   weighted contribution is a segment of one bar — the claim the whole project
   rests on.

3. `Book the top one for me`

   The booking form opens inside the conversation. It is an MCP App: a `ui://`
   resource served by an MCP server, rendered in a sandboxed view on a
   separate origin.

4. Fill the form and submit.

   The view messages the host, which drives the agent to open the simulated
   checkout — a second MCP App.

5. Pay with `0000000000000001`.

   A confirmation reference is issued. `4000000000000002` declines; anything
   outside the test set is rejected outright.

## If there is time

- `A luxury SUV under ₹7 lakh` — the agent names the binding constraint and
  quantifies what relaxing it would find, from the catalogue rather than
  guessed.
- `Actually my budget is tight — nothing over ₹2,200 a day, and I don't care
  how old the car is` — the same shortlist reorders and the contribution bar
  shifts, because the weights were inferred from that phrasing.
