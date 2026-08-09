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
import { SurfaceStore, type Surface } from "@/lib/a2ui/store";
import type {
  Listing,
  Phase,
  ReasoningRecord,
  StateEvent,
  TranscriptEntry,
} from "@/lib/types";

type ToolResult = Record<string, unknown> | null;

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
  /** The MCP App currently open, if any. Held outside the transcript so
   *  streaming events cannot remount its iframe mid-handshake. */
  activeApp: {
    uri: string;
    server: string;
    toolName: string;
    toolInput: Record<string, unknown>;
    toolResult: Record<string, unknown> | null;
  } | null;
  /** Every live A2UI surface, keyed by surfaceId. */
  surfaces: Map<string, Surface>;
  busy: boolean;
  connectionError: string | null;
  send: (message: string, script?: string) => Promise<void>;
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
  const [surfaces, setSurfaces] = useState<Map<string, Surface>>(new Map());
  const store = useRef(new SurfaceStore());
  const [activeApp, setActiveApp] = useState<AgentSession["activeApp"]>(null);
  const [busy, setBusy] = useState(false);
  const [connectionError, setConnectionError] = useState<string | null>(null);


  useEffect(() => {
    let cancelled = false;
    // A fresh session on every page load. The backend would happily resume
    // the previous one, but a reloaded page has an empty transcript while the
    // agent remembers everything — which reads as the agent skipping ahead.
    createSession()
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
    async (message: string, script?: string) => {
      if (!sessionId || busy) return;

      setBusy(true);
      setConnectionError(null);
      append({ id: nextId(), type: "user", text: message });

      try {
        for await (const event of takeTurn(sessionId, message, { script })) {
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
              handleTool(data, append);
              break;

            case "a2ui": {
              // Apply the envelope, then publish a snapshot so React sees a
              // new Map and re-renders the affected surface.
              const message = data.message as Parameters<
                SurfaceStore["apply"]
              >[0];
              const surfaceId = store.current.apply(message);
              setSurfaces(store.current.snapshot());

              // Only inline surfaces enter the transcript; panel surfaces
              // are rendered in place beside it.
              const isCreate = message && "createSurface" in message;
              if (surfaceId && isCreate && data.placement === "inline") {
                append({ id: nextId(), type: "surface", surfaceId });
              }
              break;
            }

            case "ui": {
              const frame = data.component as Record<string, unknown>;
              setActiveApp({
                uri: String(frame.uri),
                server: String(frame.server),
                toolName: String(frame.toolName),
                toolInput: (frame.toolInput ?? {}) as Record<string, unknown>,
                toolResult: (frame.toolResult ?? null) as ToolResult,
              });
              break;
            }

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
    setActiveApp(null);
    store.current = new SurfaceStore();
    setSurfaces(new Map());
  }, []);

  return {
    sessionId,
    phase,
    known,
    missing,
    conflicts,
    shortlistSize,
    transcript,
    activeApp,
    surfaces,
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
) {
  const name = String(data.name ?? "");
  const status = String(data.status ?? "");

  if (status === "started") {
    append({ id: nextId(), type: "tool", name, status: "running" });
    return;
  }

  // Results are rendered from A2UI surfaces, not reshaped here. This is left
  // with one job: showing that a step ran and what it concluded.
  append({
    id: nextId(),
    type: "tool",
    name,
    status: "done",
    summary: String(data.summary ?? ""),
  });
}
