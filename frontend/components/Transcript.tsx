"use client";

/**
 * Transcript rendering.
 *
 * The signature element is `ContributionBar` — each criterion's weighted
 * contribution as a segment of one bar, so why a car ranked where it did is
 * legible at a glance rather than buried in a paragraph. Everything else on
 * the page stays quiet so that bar carries the weight.
 */

import { useState } from "react";

import { categoryLabel, km, rupees } from "@/lib/api";
import type {
  Listing,
  ReasoningRecord,
  ScoreComponent,
  TranscriptEntry,
} from "@/lib/types";

const CRITERION_COLOURS: Record<string, string> = {
  budget: "var(--c8)",
  recency: "var(--c2)",
  category: "var(--c3)",
  condition: "var(--c4)",
  seats: "var(--c5)",
  fuel: "var(--c6)",
  transmission: "var(--c7)",
  brand: "var(--c9)",
  availability: "var(--c1)",
  location: "var(--c10)",
};

const CRITERION_LABELS: Record<string, string> = {
  budget: "Price vs budget",
  recency: "Model year",
  category: "Vehicle type",
  condition: "Mileage",
  seats: "Seating",
  fuel: "Fuel",
  transmission: "Gearbox",
  brand: "Brand",
  availability: "Availability",
  location: "Location",
};

const TOOL_LABELS: Record<string, string> = {
  update_slots: "Noting requirements",
  revise_constraints: "Revising requirements",
  change_mode: "Switching between buying and renting",
  flag_conflict: "Checking for conflicts",
  resolve_conflict: "Resolving conflict",
  search_listings: "Searching listings",
  set_shortlist: "Narrowing candidates",
  rank_shortlist: "Ranking against priorities",
  compute_tco: "Comparing cost of buying and renting",
  advance_phase: "Moving on",
  session_status: "Checking progress",
  list_facet_values: "Checking what's available",
};

/* ------------------------------------------------------------------ */
/* Signature: contribution bar                                         */
/* ------------------------------------------------------------------ */

function ContributionBar({ breakdown }: { breakdown: ScoreComponent[] }) {
  const contributions = breakdown
    .map((c) => ({ ...c, value: c.raw_score * c.weight }))
    .filter((c) => c.value > 0.001)
    .sort((a, b) => b.value - a.value);

  const total = contributions.reduce((sum, c) => sum + c.value, 0);
  if (total <= 0) return null;

  return (
    <div>
      <div
        style={{
          display: "flex",
          height: 8,
          borderRadius: 2,
          overflow: "hidden",
          background: "var(--sunken)",
        }}
      >
        {contributions.map((c) => (
          <div
            key={c.criterion}
            title={`${CRITERION_LABELS[c.criterion] ?? c.criterion}: ${(
              c.value * 100
            ).toFixed(1)} of ${(total * 100).toFixed(0)}`}
            style={{
              width: `${(c.value / total) * 100}%`,
              background: CRITERION_COLOURS[c.criterion] ?? "var(--ink-3)",
            }}
          />
        ))}
      </div>

      <dl style={{ margin: "0.75rem 0 0" }}>
        {contributions.slice(0, 5).map((c) => (
          <div className="spec-row" key={c.criterion}>
            <dt style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span
                aria-hidden
                style={{
                  width: 8,
                  height: 8,
                  borderRadius: 1,
                  background:
                    CRITERION_COLOURS[c.criterion] ?? "var(--ink-3)",
                  flexShrink: 0,
                }}
              />
              {CRITERION_LABELS[c.criterion] ?? c.criterion}
            </dt>
            <dd>
              <span style={{ color: "var(--ink-3)" }}>
                {(c.raw_score * 100).toFixed(0)}%
              </span>
              <span style={{ color: "var(--rule-strong)" }}> × </span>
              {(c.weight * 100).toFixed(0)}%
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Cards                                                               */
/* ------------------------------------------------------------------ */

function CarSpecs({ listing }: { listing: Listing }) {
  return (
    <dl style={{ margin: 0 }}>
      <div className="spec-row">
        <dt>Type</dt>
        <dd>{categoryLabel(listing.category)}</dd>
      </div>
      <div className="spec-row">
        <dt>Year</dt>
        <dd>{listing.year}</dd>
      </div>
      <div className="spec-row">
        <dt>Mileage</dt>
        <dd>{listing.condition === "new" ? "New" : km(listing.km)}</dd>
      </div>
      <div className="spec-row">
        <dt>Seats · Fuel · Gearbox</dt>
        <dd>
          {listing.seats} · {listing.fuel} · {listing.transmission}
        </dd>
      </div>
      <div className="spec-row">
        <dt>Location</dt>
        <dd>{listing.city}</dd>
      </div>
      <div className="spec-row">
        <dt>Available</dt>
        <dd>
          {listing.available_from}
          {listing.available_to ? ` – ${listing.available_to}` : " onwards"}
        </dd>
      </div>
    </dl>
  );
}

function PriceLine({ listing }: { listing: Listing }) {
  return (
    <div style={{ display: "flex", gap: "1.25rem", alignItems: "baseline" }}>
      {listing.rent_per_day_inr != null && (
        <span>
          <span className="figure" style={{ fontSize: "1.125rem", fontWeight: 600 }}>
            {rupees(listing.rent_per_day_inr)}
          </span>
          <span className="label"> / day</span>
        </span>
      )}
      {listing.price_inr != null && (
        <span>
          <span className="figure" style={{ fontSize: "1.125rem", fontWeight: 600 }}>
            {rupees(listing.price_inr)}
          </span>
          <span className="label"> to buy</span>
        </span>
      )}
    </div>
  );
}

function ListingCard({ listing }: { listing: Listing }) {
  return (
    <article className="card" style={{ padding: "0.875rem 1rem" }}>
      <div className="display" style={{ fontSize: "1rem" }}>
        {listing.brand} {listing.model}
      </div>
      <div className="eyebrow" style={{ marginTop: 2 }}>
        {listing.year} · {listing.seller_name}
      </div>
      <div style={{ marginTop: "0.625rem" }}>
        <PriceLine listing={listing} />
      </div>
    </article>
  );
}

function RankedCard({
  record,
  listing,
}: {
  record: ReasoningRecord;
  listing: Listing | undefined;
}) {
  const [open, setOpen] = useState(record.rank === 1);
  if (!listing) return null;

  return (
    <article className="card" style={{ overflow: "hidden" }}>
      <div
        style={{
          display: "flex",
          gap: "1rem",
          padding: "0.875rem 1rem",
          alignItems: "flex-start",
        }}
      >
        <div
          className="figure"
          aria-label={`Rank ${record.rank}`}
          style={{
            fontSize: "1.5rem",
            fontWeight: 600,
            lineHeight: 1,
            color: record.rank === 1 ? "var(--signal)" : "var(--ink-3)",
            minWidth: "1.75rem",
          }}
        >
          {record.rank}
        </div>

        <div style={{ flex: 1, minWidth: 0 }}>
          <div className="display" style={{ fontSize: "1rem" }}>
            {listing.brand} {listing.model}
          </div>
          <div className="eyebrow" style={{ marginTop: 2 }}>
            {listing.year} · {listing.city} · score{" "}
            {record.total_score.toFixed(2)}
          </div>

          <div style={{ marginTop: "0.625rem" }}>
            <PriceLine listing={listing} />
          </div>

          {record.matched.length > 0 && (
            <ul
              style={{
                margin: "0.75rem 0 0",
                padding: 0,
                listStyle: "none",
                fontSize: "0.8125rem",
                color: "var(--ink-2)",
              }}
            >
              {record.matched.slice(0, 3).map((m) => (
                <li key={m} style={{ display: "flex", gap: 8 }}>
                  <span style={{ color: "var(--ok)" }} aria-hidden>
                    ✓
                  </span>
                  {m}
                </li>
              ))}
              {record.tradeoffs.slice(0, 2).map((t) => (
                <li key={t} style={{ display: "flex", gap: 8 }}>
                  <span style={{ color: "var(--warn)" }} aria-hidden>
                    ·
                  </span>
                  {t}
                </li>
              ))}
            </ul>
          )}

          <button
            className="btn btn-quiet"
            onClick={() => setOpen(!open)}
            style={{ marginTop: "0.75rem", fontSize: "0.75rem" }}
            aria-expanded={open}
          >
            {open ? "Hide the working" : "Show the working"}
          </button>
        </div>
      </div>

      {open && (
        <div
          style={{
            borderTop: "1px solid var(--rule)",
            background: "var(--paper)",
            padding: "1rem",
          }}
        >
          <div className="eyebrow" style={{ marginBottom: "0.625rem" }}>
            How this score was reached
          </div>
          <ContributionBar breakdown={record.breakdown} />

          <details style={{ marginTop: "1rem" }}>
            <summary
              className="label"
              style={{ cursor: "pointer", color: "var(--ink-3)" }}
            >
              Full specification
            </summary>
            <div style={{ marginTop: "0.5rem" }}>
              <CarSpecs listing={listing} />
            </div>
          </details>
        </div>
      )}
    </article>
  );
}

/* ------------------------------------------------------------------ */
/* Activity lines                                                      */
/* ------------------------------------------------------------------ */

function ActivityLine({
  children,
  running = false,
  tone = "quiet",
}: {
  children: React.ReactNode;
  running?: boolean;
  tone?: "quiet" | "signal" | "stop";
}) {
  const colour =
    tone === "signal"
      ? "var(--signal)"
      : tone === "stop"
        ? "var(--stop)"
        : "var(--ink-3)";

  return (
    <div
      style={{
        display: "flex",
        gap: "0.625rem",
        alignItems: "baseline",
        fontSize: "0.8125rem",
        color: colour,
        padding: "0.1875rem 0",
      }}
    >
      <span
        aria-hidden
        style={{
          width: 5,
          height: 5,
          borderRadius: "50%",
          background: colour,
          flexShrink: 0,
          opacity: running ? 1 : 0.45,
          transform: "translateY(-2px)",
        }}
      />
      <span>{children}</span>
    </div>
  );
}

/* ------------------------------------------------------------------ */

export function TranscriptItem({ entry }: { entry: TranscriptEntry }) {
  switch (entry.type) {
    case "user":
      return (
        <div style={{ display: "flex", justifyContent: "flex-end" }}>
          <div
            style={{
              background: "var(--ink)",
              color: "var(--paper)",
              padding: "0.5rem 0.875rem",
              borderRadius: "var(--radius-lg)",
              maxWidth: "80%",
            }}
          >
            {entry.text}
          </div>
        </div>
      );

    case "assistant":
      return (
        <div style={{ whiteSpace: "pre-wrap", maxWidth: "58ch" }}>
          {entry.text}
        </div>
      );

    case "tool":
      return (
        <ActivityLine running={entry.status === "running"}>
          {TOOL_LABELS[entry.name] ?? entry.name}
          {entry.status === "running" ? "…" : ""}
          {entry.summary && entry.name !== "search_listings" && (
            <span style={{ color: "var(--ink-3)" }}> — {entry.summary}</span>
          )}
        </ActivityLine>
      );

    case "phase":
      return (
        <ActivityLine tone={entry.allowed ? "signal" : "stop"}>
          {entry.message}
        </ActivityLine>
      );

    case "progress":
      return (
        <ActivityLine>
          {entry.text}
          {entry.remaining != null && (
            <span className="figure"> — {entry.remaining} remaining</span>
          )}
        </ActivityLine>
      );

    case "listings":
      return (
        <section>
          <div className="eyebrow" style={{ marginBottom: "0.5rem" }}>
            {entry.total} matching {entry.total === 1 ? "listing" : "listings"}
          </div>
          <div style={{ display: "grid", gap: "0.5rem" }}>
            {entry.listings.map((listing) => (
              <ListingCard key={listing.id} listing={listing} />
            ))}
          </div>
        </section>
      );

    case "rankings":
      return (
        <section>
          <div className="eyebrow" style={{ marginBottom: "0.5rem" }}>
            Ranked
            {entry.weightSource === "inferred"
              ? " using weights inferred from your priorities"
              : " using default weights"}
          </div>
          <div style={{ display: "grid", gap: "0.5rem" }}>
            {entry.records.map((record) => (
              <RankedCard
                key={record.listing_id}
                record={record}
                listing={entry.listings[record.listing_id]}
              />
            ))}
          </div>
        </section>
      );

    case "error":
      return <ActivityLine tone="stop">{entry.text}</ActivityLine>;
  }
}
