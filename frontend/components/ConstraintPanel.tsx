"use client";

/**
 * The constraint panel — FR-005.
 *
 * Shows what the agent has understood, at all times. This is the honesty
 * surface of the product: if the agent has misheard something, the user sees
 * it here rather than discovering it in the results.
 *
 * Modelled on a vehicle specification sheet: label left, value right,
 * hairline between, figures in mono. Slots not yet filled are listed as
 * outstanding rather than hidden, so the interview's progress is visible.
 */

import { slotLabel, slotValue } from "@/lib/api";
import type { Phase } from "@/lib/types";

// Short enough to sit in a quarter-width column without breaking. The
// progress rule above each label carries the state; the word only has to
// name the step.
const PHASES: { key: Phase; label: string }[] = [
  { key: "interview", label: "Needs" },
  { key: "research", label: "Search" },
  { key: "recommend", label: "Rank" },
  { key: "book", label: "Book" },
];

const ORDER = [
  "mode",
  "use_case",
  "category",
  "budget_max",
  "target_date",
  "seats_min",
  "duration_days",
  "fuel",
  "transmission",
  "brand_affinity",
  "year_min",
  "km_max",
  "city",
  "country",
];

export function ConstraintPanel({
  phase,
  known,
  missing,
  conflicts,
  shortlistSize,
}: {
  phase: Phase;
  known: Record<string, unknown>;
  missing: string[];
  conflicts: string[];
  shortlistSize: number;
}) {
  const filled = ORDER.filter((key) => key in known);
  const activeIndex = PHASES.findIndex((p) => p.key === phase);

  return (
    <aside
      className="card"
      style={{
        padding: "1rem",
        position: "sticky",
        top: "1.5rem",
        alignSelf: "start",
      }}
    >
      {/* Phase progression. Order carries real information here — the agent
          cannot search before requirements are complete — so a numbered
          sequence is honest rather than decorative. */}
      <ol
        style={{
          display: "flex",
          gap: "0.375rem",
          listStyle: "none",
          margin: "0 0 1rem",
          padding: 0,
        }}
      >
        {PHASES.map((p, index) => {
          const done = index < activeIndex;
          const active = index === activeIndex;
          return (
            <li key={p.key} style={{ flex: 1 }}>
              <div
                style={{
                  height: 2,
                  background: done
                    ? "var(--ink-3)"
                    : active
                      ? "var(--signal)"
                      : "var(--rule)",
                }}
              />
              <div
                className="eyebrow"
                style={{
                  marginTop: 6,
                  fontSize: "0.5625rem",
                  letterSpacing: "0.06em",
                  whiteSpace: "nowrap",
                  lineHeight: 1.2,
                  color: active ? "var(--signal)" : "var(--ink-3)",
                }}
              >
                {p.label}
              </div>
            </li>
          );
        })}
      </ol>

      {filled.length === 0 ? (
        <p className="label" style={{ margin: 0, color: "var(--ink-3)" }}>
          Nothing captured yet. Tell the agent what you need and it will
          appear here.
        </p>
      ) : (
        <dl style={{ margin: 0 }}>
          {filled.map((key) => (
            <div className="spec-row" key={key}>
              <dt>{slotLabel(key)}</dt>
              <dd>{slotValue(key, known[key])}</dd>
            </div>
          ))}
        </dl>
      )}

      {missing.length > 0 && (
        <div style={{ marginTop: "1rem" }}>
          <div className="eyebrow" style={{ marginBottom: "0.375rem" }}>
            Still needed
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: "0.25rem" }}>
            {missing.map((key) => (
              <span
                key={key}
                className="figure"
                style={{
                  fontSize: "0.6875rem",
                  padding: "0.125rem 0.375rem",
                  border: "1px dashed var(--rule-strong)",
                  borderRadius: "var(--radius)",
                  color: "var(--ink-3)",
                }}
              >
                {slotLabel(key)}
              </span>
            ))}
          </div>
        </div>
      )}

      {conflicts.length > 0 && (
        <div
          style={{
            marginTop: "1rem",
            padding: "0.625rem 0.75rem",
            background: "var(--signal-soft)",
            border: "1px solid var(--signal)",
            borderRadius: "var(--radius)",
            fontSize: "0.8125rem",
          }}
        >
          <div className="eyebrow" style={{ color: "var(--warn)" }}>
            Can&apos;t satisfy everything
          </div>
          {conflicts.map((c) => (
            <p key={c} style={{ margin: "0.375rem 0 0" }}>
              {c}
            </p>
          ))}
        </div>
      )}

      {shortlistSize > 0 && (
        <div className="spec-row" style={{ marginTop: "1rem" }}>
          <dt>Shortlisted</dt>
          <dd>{shortlistSize}</dd>
        </div>
      )}
    </aside>
  );
}
