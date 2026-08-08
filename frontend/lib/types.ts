/**
 * Types mirroring the backend event stream.
 *
 * Kept in sync by hand with `backend/app/api/events.py` and
 * `backend/app/state/models.py`. Worth generating from the OpenAPI schema
 * eventually; for a project this size hand-maintained is cheaper than the
 * codegen step, and the shapes are small.
 */

export type Phase =
  | "interview"
  | "research"
  | "recommend"
  | "book"
  | "complete";

export type EventKind =
  | "phase"
  | "tool"
  | "progress"
  | "message"
  | "ui"
  | "state"
  | "done"
  | "error";

export interface PhaseEvent {
  phase: Phase;
  allowed: boolean;
  message: string;
  missing: string[];
}

export interface ToolEvent {
  name: string;
  status: "started" | "finished";
  arguments?: Record<string, unknown>;
  summary?: string;
  result?: Record<string, unknown>;
}

export interface ProgressEvent {
  text: string;
  remaining?: number;
}

export interface MessageEvent {
  role: "assistant";
  text: string;
}

export interface StateEvent {
  phase: Phase;
  known: Record<string, unknown>;
  missing: string[];
  conflicts: string[];
  shortlist_size: number;
}

export interface UiEvent {
  surface: "inline" | "panel" | "progress";
  component: Record<string, unknown>;
}

export interface ErrorEvent {
  text: string;
  recoverable: boolean;
}

export interface StreamEvent {
  kind: EventKind;
  at: string;
  data: Record<string, unknown>;
}

/* ------------------------------------------------------------------ */
/* Domain                                                              */
/* ------------------------------------------------------------------ */

export interface Listing {
  id: string;
  category: string;
  brand: string;
  model: string;
  variant: string | null;
  year: number;
  km: number;
  fuel: string;
  transmission: string;
  seats: number;
  condition: string;
  for_sale: boolean;
  for_rent: boolean;
  price_inr: number | null;
  price_eur: number | null;
  rent_per_day_inr: number | null;
  rent_per_day_eur: number | null;
  min_rental_days: number | null;
  weekly_discount_pct: number | null;
  city: string;
  country: string;
  seller_type: string;
  seller_name: string;
  available_from: string;
  available_to: string | null;
  image_key: string;
}

export interface ScoreComponent {
  criterion: string;
  raw_score: number;
  weight: number;
}

export interface ReasoningRecord {
  listing_id: string;
  rank: number;
  total_score: number;
  matched: string[];
  tradeoffs: string[];
  breakdown: ScoreComponent[];
  weight_source: "inferred" | "fallback";
}

export interface SessionSummary {
  session_id: string;
  phase: Phase;
  known: Record<string, unknown>;
  missing: string[];
  conflicts: string[];
  shortlist: string[];
  status: {
    phase: Phase;
    turns_in_phase: number;
    turn_cap: number;
    tools: string[];
    next_phase: Phase | null;
    can_advance: boolean;
    blocked_by: string | null;
  };
}

/* ------------------------------------------------------------------ */
/* Transcript                                                          */
/* ------------------------------------------------------------------ */

/**
 * What the transcript renders. Tool activity is a first-class entry rather
 * than hidden: showing the agent's working is the point of the product, not
 * debug output.
 */
export type TranscriptEntry =
  | { id: string; type: "user"; text: string }
  | { id: string; type: "assistant"; text: string }
  | {
      id: string;
      type: "tool";
      name: string;
      status: "running" | "done";
      summary?: string;
      result?: Record<string, unknown>;
    }
  | { id: string; type: "phase"; phase: Phase; message: string; allowed: boolean }
  | { id: string; type: "progress"; text: string; remaining?: number }
  | { id: string; type: "listings"; listings: Listing[]; total: number }
  | {
      id: string;
      type: "rankings";
      records: ReasoningRecord[];
      listings: Record<string, Listing>;
      weightSource: string;
    }
  | { id: string; type: "error"; text: string };
