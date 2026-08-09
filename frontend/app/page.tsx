"use client";

import { useEffect, useRef, useState } from "react";

import { A2uiRenderer } from "@/components/a2ui/A2uiRenderer";
import { McpAppFrame } from "@/components/mcp-host/McpAppFrame";
import { TranscriptItem } from "@/components/Transcript";
import { useAgentSession } from "@/hooks/useAgentSession";

/**
 * Openers offered on an empty transcript.
 *
 * Not feature advertisements — each one is a real journey the agent handles
 * differently, so whichever a person picks, the first response demonstrates
 * something. An empty screen is an invitation to act.
 */
const OPENERS = [
  "I need to rent a 7-seater for a family trip in September, up to ₹3,500 a day",
  "Looking to buy something practical for commuting, around ₹12 lakh",
  "I need a car for about six weeks — not sure whether to rent or buy",
];

export default function Home() {
  const session = useAgentSession();
  const [draft, setDraft] = useState("");
  // Demo mode drives a scripted multi-act flow with no model calls —
  // used for reproducible demonstrations and when quota is exhausted.
  const [demo, setDemo] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [session.transcript.length]);

  const constraintSurface = session.surfaces.get("constraints");

  /**
   * An A2UI action becomes the user's next turn.
   *
   * The protocol allows a renderer to send actions to the agent; over this
   * transport the natural channel is the turn endpoint the conversation
   * already uses. Clicking "Book this one" on a card therefore drives the
   * agent exactly as typing would, without the user having to type.
   */
  const handleAction = (name: string, context: Record<string, unknown>) => {
    const label = String(context.label ?? "");
    const id = String(context.listingId ?? "");
    if (name === "book_listing") {
      void submit(`Book the ${label} (${id}) for me.`);
    } else if (name === "select_listing") {
      void submit(`Tell me more about the ${label} (${id}).`);
    }
  };

  const submit = async (text: string) => {
    const message = text.trim();
    if (!message || session.busy) return;
    setDraft("");
    await session.send(message, demo ? "demo" : undefined);
  };

  return (
    <div style={{ minHeight: "100vh", display: "flex", flexDirection: "column" }}>
      <header
        style={{
          borderBottom: "1px solid var(--rule)",
          background: "var(--card)",
        }}
      >
        <div
          style={{
            maxWidth: 1120,
            margin: "0 auto",
            padding: "0.875rem 1.5rem",
            display: "flex",
            alignItems: "baseline",
            justifyContent: "space-between",
            gap: "1rem",
          }}
        >
          <div style={{ display: "flex", alignItems: "baseline", gap: "0.75rem" }}>
            <span className="display">Car Matchmaker</span>
            <span className="eyebrow">Buy or rent, reasoned</span>
          </div>
          <div style={{ display: "flex", gap: "0.5rem" }}>
            {process.env.NODE_ENV === "development" && (
              <button
                className="btn btn-quiet"
                title="Run a scripted journey — no model calls"
                onClick={() => setDemo((d) => !d)}
                disabled={session.busy}
              >
                {demo ? "Demo mode: on" : "Demo mode: off"}
              </button>
            )}
            <button
              className="btn btn-quiet"
              onClick={session.reset}
              disabled={session.busy}
            >
              Start over
            </button>
          </div>
        </div>
      </header>

      <main
        style={{
          flex: 1,
          maxWidth: 1120,
          width: "100%",
          margin: "0 auto",
          padding: "1.5rem",
          display: "grid",
          gridTemplateColumns: "minmax(0, 1fr) 300px",
          gap: "1.5rem",
          alignItems: "start",
        }}
      >
        <section style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
          {session.connectionError && (
            <div
              className="card"
              style={{
                padding: "0.75rem 1rem",
                borderColor: "var(--stop)",
                color: "var(--stop)",
                fontSize: "0.875rem",
              }}
            >
              {session.connectionError}
            </div>
          )}

          {session.transcript.length === 0 && !session.connectionError && (
            <div style={{ paddingTop: "1rem" }}>
              <h1
                className="display"
                style={{ fontSize: "2rem", maxWidth: "18ch", margin: 0 }}
              >
                Say what you need. It works out the rest.
              </h1>
              <p
                className="label"
                style={{ maxWidth: "48ch", marginTop: "0.75rem" }}
              >
                The agent asks what it needs to know, searches real listings,
                and shows exactly why it ranked each one where it did.
              </p>

              <div
                style={{
                  display: "grid",
                  gap: "0.5rem",
                  marginTop: "1.75rem",
                  maxWidth: 560,
                }}
              >
                {OPENERS.map((opener) => (
                  <button
                    key={opener}
                    onClick={() => submit(opener)}
                    className="card"
                    style={{
                      textAlign: "left",
                      padding: "0.75rem 0.875rem",
                      cursor: "pointer",
                      fontSize: "0.875rem",
                      color: "var(--ink-2)",
                    }}
                  >
                    {opener}
                  </button>
                ))}
              </div>
            </div>
          )}

          {session.transcript.map((entry) => (
            <TranscriptItem
              key={entry.id}
              entry={entry}
              surfaces={session.surfaces}
              onAction={handleAction}
              onAppMessage={(text) => void submit(text)}
            />
          ))}

          {session.activeApp && (
            <McpAppFrame
              key={session.activeApp.toolName}
              uri={session.activeApp.uri}
              server={session.activeApp.server}
              toolName={session.activeApp.toolName}
              toolInput={session.activeApp.toolInput}
              toolResult={session.activeApp.toolResult}
              onMessage={(text) => void submit(text)}
            />
          )}

          <div ref={endRef} />
        </section>

        <aside
          className="card"
          style={{ padding: "1rem", position: "sticky", top: "1.5rem" }}
        >
          {constraintSurface ? (
            <A2uiRenderer surface={constraintSurface} />
          ) : (
            <p className="label" style={{ margin: 0, color: "var(--ink-3)" }}>
              Tell the agent what you need and it will appear here.
            </p>
          )}
        </aside>
      </main>

      <footer
        style={{
          position: "sticky",
          bottom: 0,
          borderTop: "1px solid var(--rule)",
          background: "var(--card)",
        }}
      >
        <div
          style={{
            maxWidth: 1120,
            margin: "0 auto",
            padding: "0.875rem 1.5rem",
            display: "flex",
            gap: "0.625rem",
            alignItems: "flex-end",
          }}
        >
          <textarea
            className="field"
            rows={1}
            value={draft}
            placeholder={
              session.busy ? "Working…" : "Tell the agent what you need"
            }
            disabled={session.busy || !session.sessionId}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void submit(draft);
              }
            }}
            style={{ minHeight: "2.5rem", maxHeight: "8rem" }}
          />
          <button
            className="btn"
            onClick={() => void submit(draft)}
            disabled={session.busy || !draft.trim()}
          >
            Send
          </button>
        </div>
      </footer>
    </div>
  );
}
