/**
 * API client.
 *
 * Turns are POSTs whose response body is an SSE stream, so `EventSource`
 * cannot be used — it only issues GETs. Parsing the stream by hand is a
 * dozen lines and avoids restructuring the transport to suit a browser API.
 */

import type { SessionSummary, StreamEvent } from "./types";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<T>;
}

export function createSession(): Promise<SessionSummary> {
  return json<SessionSummary>("/api/sessions", { method: "POST" });
}

export function currentSession(): Promise<SessionSummary> {
  return json<SessionSummary>("/api/sessions/current");
}

export function getSession(id: string): Promise<SessionSummary> {
  return json<SessionSummary>(`/api/sessions/${id}`);
}

export function getHistory(id: string): Promise<Record<string, unknown>> {
  return json(`/api/sessions/${id}/history`);
}

/**
 * Send a message and yield events as they arrive.
 *
 * An async generator rather than a callback: the caller can `for await` over
 * a turn, and cancelling is a `break` instead of a subscription to unwind.
 */
export async function* takeTurn(
  sessionId: string,
  message: string,
  options: { script?: string; signal?: AbortSignal } = {},
): AsyncGenerator<StreamEvent> {
  const response = await fetch(`${BASE}/api/sessions/${sessionId}/turn`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, script: options.script ?? null }),
    signal: options.signal,
  });

  if (!response.ok || !response.body) {
    throw new Error(`Turn failed: ${response.status}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });

    // SSE frames are separated by a blank line. Anything after the last
    // separator is a partial frame and stays in the buffer.
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";

    for (const frame of frames) {
      const event = parseFrame(frame);
      if (event) yield event;
    }
  }
}

function parseFrame(frame: string): StreamEvent | null {
  let kind = "";
  const dataLines: string[] = [];

  for (const line of frame.split("\n")) {
    if (line.startsWith("event:")) {
      kind = line.slice(6).trim();
    } else if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).trim());
    }
  }

  if (!kind || dataLines.length === 0) return null;

  try {
    const parsed = JSON.parse(dataLines.join("\n")) as Record<string, unknown>;
    const at = (parsed.at as string) ?? new Date().toISOString();
    return { kind: kind as StreamEvent["kind"], at, data: parsed };
  } catch {
    // A malformed frame is not worth failing the turn over — the stream
    // carries many events and losing one is recoverable.
    return null;
  }
}

/* ------------------------------------------------------------------ */
/* Formatting                                                          */
/* ------------------------------------------------------------------ */

export function rupees(value: number | null | undefined): string {
  if (value == null) return "—";
  return `₹${value.toLocaleString("en-IN")}`;
}

export function km(value: number): string {
  return `${value.toLocaleString("en-IN")} km`;
}

/** 'compact_suv' -> 'Compact SUV'. Mirrors the backend's humanise_category. */
export function categoryLabel(value: string): string {
  const acronyms: Record<string, string> = { suv: "SUV", mpv: "MPV" };
  return value
    .split("_")
    .map((word) =>
      acronyms[word] ?? word.charAt(0).toUpperCase() + word.slice(1),
    )
    .join(" ");
}

export function slotLabel(key: string): string {
  const labels: Record<string, string> = {
    mode: "Buying or renting",
    use_case: "Use",
    category: "Type",
    budget_max: "Budget",
    budget_min: "Minimum",
    target_date: "From",
    duration_days: "Duration",
    seats_min: "Seats",
    fuel: "Fuel",
    transmission: "Gearbox",
    brand_affinity: "Brands",
    year_min: "Year from",
    km_max: "Max mileage",
    city: "City",
    country: "Country",
  };
  return labels[key] ?? key.replace(/_/g, " ");
}

export function slotValue(key: string, value: unknown): string {
  if (value == null) return "—";
  if (Array.isArray(value)) return value.join(", ");
  if (key === "budget_max" || key === "budget_min") {
    return rupees(Number(value));
  }
  if (key === "category") return categoryLabel(String(value));
  return String(value);
}
