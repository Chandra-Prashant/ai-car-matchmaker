"use client";

/**
 * Session state and turn streaming.
 *
 * Owns one job: consume the event stream and turn it into a transcript the
 * UI can render. Components below it are presentational.
 *
 * Two events get intercepted rather than rendered as generic tool results —
 * `search_listings` becomes a catalogue and `rank_shortlist` becomes ranked
 * cards with reasoning. Everything else renders as an activity line, which
 * is deliberate: the agent's working is content, not debug output.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { createSession, currentSession, takeTurn } from "@/lib/api";
import type {
  Listing,
  Phase,
  ReasoningRecord,
  StateEvent,
  TranscriptEntry,
} from "@/lib/types";

let counter = 0;
const nextId = () => `e${++counter}`;

export interface AgentSession {
  sessionId: string | null;
  phase: Phase;
  known: Record<string, unknown>;
  missing: string[];
  conflicts: string[];
  shortlistSize: number;
  transcript: TranscriptEntry[];
  busy: boolean;
  connectionError: string | null;
  send: (message: string) => Promise<void>;
  reset: () => Promise<void>;
}

export function useAgentSession(): AgentSession {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [phase, setPhase] = useState<Phase>("interview");
  const [known, setKnown] = useState<Record<string, unknown>>({});
  const [missing, setMissing] = useState<string[]>([]);
  const [conflicts, setConflicts] = useState<string[]>([]);
  const [shortlistSize, setShortlistSize] = useState(0);
  const [transcript, setTranscript] = useState<TranscriptEntry[]>([]);
  const [busy, setBusy] = useState(false);
  const [connectionError, setConnectionError] = useState<string | null>(null);

  // Listings seen this session, so rankings can be rendered with full detail
  // without refetching what the search already returned.
  const listingCache = useRef<Record<string, Listing>>({});

  useEffect(() => {
    let cancelled = false;
    currentSession()
      .then((summary) => {
        if (cancelled) return;
        setSessionId(summary.session_id);
        setPhase(summary.phase);
        setKnown(summary.known);
        setMissing(summary.missing);
        setConflicts(summary.conflicts);
      })
      .catch(() =>
        setConnectionError(
          "Can't reach the agent. Start the backend on port 8000 and reload.",
        ),
      );
    return () => {
      cancelled = true;
    };
  }, []);

  const append = useCallback((entry: TranscriptEntry) => {
    setTranscript((prev) => {
      // A tool's "finished" entry replaces its "running" one rather than
      // appending, so each step occupies one line that resolves in place
      // instead of two that read as repetition.
      if (entry.type === "tool" && entry.status === "done") {
        const index = prev.findLastIndex(
          (e) => e.type === "tool" && e.status === "running" && e.name === entry.name,
        );
        if (index >= 0) {
          const next = [...prev];
          next[index] = entry;
          return next;
        }
      }
      return [...prev, entry];
    });
  }, []);

  const send = useCallback(
    async (message: string) => {
      if (!sessionId || busy) return;

      setBusy(true);
      setConnectionError(null);
      append({ id: nextId(), type: "user", text: message });

      try {
        for await (const event of takeTurn(sessionId, message)) {
          const data = event.data;

          switch (event.kind) {
            case "state": {
              const s = data as unknown as StateEvent;
              setPhase(s.phase);
              setKnown(s.known);
              setMissing(s.missing);
              setConflicts(s.conflicts);
              setShortlistSize(s.shortlist_size);
              break;
            }

            case "message":
              append({
                id: nextId(),
                type: "assistant",
                text: String(data.text ?? ""),
              });
              break;

            case "phase":
              append({
                id: nextId(),
                type: "phase",
                phase: data.phase as Phase,
                message: String(data.message ?? ""),
                allowed: Boolean(data.allowed),
              });
              break;

            case "progress":
              append({
                id: nextId(),
                type: "progress",
                text: String(data.text ?? ""),
                remaining: data.remaining as number | undefined,
              });
              break;

            case "tool":
              handleTool(data, append, listingCache);
              break;

            case "error":
              append({
                id: nextId(),
                type: "error",
                text: String(data.text ?? "Something went wrong."),
              });
              break;

            case "done":
              break;
          }
        }
      } catch (error) {
        setConnectionError(
          error instanceof Error ? error.message : "The turn failed.",
        );
      } finally {
        setBusy(false);
      }
    },
    [sessionId, busy, append],
  );

  const reset = useCallback(async () => {
    const summary = await createSession();
    setSessionId(summary.session_id);
    setPhase(summary.phase);
    setKnown({});
    setMissing(summary.missing);
    setConflicts([]);
    setShortlistSize(0);
    setTranscript([]);
    listingCache.current = {};
  }, []);

  return {
    sessionId,
    phase,
    known,
    missing,
    conflicts,
    shortlistSize,
    transcript,
    busy,
    connectionError,
    send,
    reset,
  };
}

/* ------------------------------------------------------------------ */

function handleTool(
  data: Record<string, unknown>,
  append: (entry: TranscriptEntry) => void,
  cache: React.MutableRefObject<Record<string, Listing>>,
) {
  const name = String(data.name ?? "");
  const status = String(data.status ?? "");

  if (status === "started") {
    append({ id: nextId(), type: "tool", name, status: "running" });
    return;
  }

  const result = (data.result ?? {}) as Record<string, unknown>;
  const summary = String(data.summary ?? "");

  // Search results become a catalogue rather than a line of text.
  if (name === "search_listings" && Array.isArray(result.listings)) {
    const listings = result.listings as Listing[];
    for (const listing of listings) cache.current[listing.id] = listing;

    append({ id: nextId(), type: "tool", name, status: "done", summary });
    if (listings.length > 0) {
      append({
        id: nextId(),
        type: "listings",
        listings,
        total: Number(result.total_matched ?? listings.length),
      });
    }
    return;
  }

  // Rankings become cards with the reasoning attached — the thing the whole
  // product is for.
  if (name === "rank_shortlist" && Array.isArray(result.rankings)) {
    const records = result.rankings as ReasoningRecord[];

    // Rankings carry their listings, so a resumed session can render cards
    // without having seen the search that produced them.
    if (Array.isArray(result.listings)) {
      for (const listing of result.listings as Listing[]) {
        cache.current[listing.id] = listing;
      }
    }
    append({ id: nextId(), type: "tool", name, status: "done", summary });
    if (records.length > 0) {
      append({
        id: nextId(),
        type: "rankings",
        records,
        listings: { ...cache.current },
        weightSource: String(result.weight_source ?? "fallback"),
      });
    }
    return;
  }

  append({ id: nextId(), type: "tool", name, status: "done", summary, result });
}
