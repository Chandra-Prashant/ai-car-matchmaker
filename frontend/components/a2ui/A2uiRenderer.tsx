"use client";

/**
 * A2UI React renderer.
 *
 * Walks a surface's adjacency list from `root` and dispatches each component
 * name to a React implementation. The agent names components and binds data;
 * everything about how they look lives here.
 *
 * LIST TEMPLATES
 * --------------
 * When a container binds `children` to a path with a template componentId,
 * the renderer instantiates the template once per item and gives each
 * instance its own scope. That is why a relative binding like `brand`
 * resolves to a different value in each card while `/weightSource` still
 * reaches the surface root.
 *
 * PROGRESSIVE RENDERING
 * ---------------------
 * A referenced component that has not arrived yet renders as nothing rather
 * than throwing. The spec asks for this: definitions may stream in any
 * order, and the tree should fill in as they land.
 */

import { useCallback, useMemo } from "react";

import {
  type A2uiComponent,
  type ActionSpec,
  type Scope,
  type Surface,
  isTemplate,
  resolveActionContext,
  resolveProps,
  resolvePointer,
} from "@/lib/a2ui/store";

/* ------------------------------------------------------------------ */
/* Presentation helpers                                                */
/* ------------------------------------------------------------------ */

const rupees = (value: unknown): string =>
  typeof value === "number" ? `₹${value.toLocaleString("en-IN")}` : "—";

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

/* ------------------------------------------------------------------ */
/* Catalog implementations                                             */
/* ------------------------------------------------------------------ */

type Props = Record<string, unknown>;

interface RenderContext {
  surface: Surface;
  scope: Scope;
  renderChild: (id: string, scope?: Scope) => React.ReactNode;
  dispatch: (action: ActionSpec | undefined, scope: Scope) => void;
}

function PriceLine({ perDay, purchase }: { perDay: unknown; purchase: unknown }) {
  return (
    <div style={{ display: "flex", gap: "1.25rem", alignItems: "baseline" }}>
      {typeof perDay === "number" && (
        <span>
          <span className="figure" style={{ fontSize: "1.125rem", fontWeight: 600 }}>
            {rupees(perDay)}
          </span>
          <span className="label"> / day</span>
        </span>
      )}
      {typeof purchase === "number" && (
        <span>
          <span className="figure" style={{ fontSize: "1.125rem", fontWeight: 600 }}>
            {rupees(purchase)}
          </span>
          <span className="label"> to buy</span>
        </span>
      )}
    </div>
  );
}

function CarCard({ props, ctx }: { props: Props; ctx: RenderContext }) {
  const action = props.action as ActionSpec | undefined;
  return (
    <article
      className="card"
      style={{
        padding: "0.875rem 1rem",
        cursor: action ? "pointer" : undefined,
      }}
      onClick={action ? () => ctx.dispatch(action, ctx.scope) : undefined}
    >
      <div className="display" style={{ fontSize: "1rem" }}>
        {String(props.brand ?? "")} {String(props.model ?? "")}
      </div>
      <div className="eyebrow" style={{ marginTop: 2 }}>
        {String(props.year ?? "")} · {String(props.seller ?? "")}
      </div>
      <div style={{ marginTop: "0.625rem" }}>
        <PriceLine perDay={props.pricePerDay} purchase={props.purchasePrice} />
      </div>
    </article>
  );
}

function ContributionBar({ props }: { props: Props }) {
  const breakdown = (props.breakdown ?? []) as {
    criterion: string;
    rawScore: number;
    weight: number;
  }[];

  const contributions = breakdown
    .map((c) => ({ ...c, value: c.rawScore * c.weight }))
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
            title={`${CRITERION_LABELS[c.criterion] ?? c.criterion}`}
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
                  background: CRITERION_COLOURS[c.criterion] ?? "var(--ink-3)",
                  flexShrink: 0,
                }}
              />
              {CRITERION_LABELS[c.criterion] ?? c.criterion}
            </dt>
            <dd>
              <span style={{ color: "var(--ink-3)" }}>
                {(c.rawScore * 100).toFixed(0)}%
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

function RankedCarCard({ props, ctx }: { props: Props; ctx: RenderContext }) {
  const rank = Number(props.rank ?? 0);
  const matched = (props.matched ?? []) as string[];
  const tradeoffs = (props.tradeoffs ?? []) as string[];
  const workingId = props.working as string | undefined;
  const action = props.action as ActionSpec | undefined;

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
          aria-label={`Rank ${rank}`}
          style={{
            fontSize: "1.5rem",
            fontWeight: 600,
            lineHeight: 1,
            color: rank === 1 ? "var(--signal)" : "var(--ink-3)",
            minWidth: "1.75rem",
          }}
        >
          {rank}
        </div>

        <div style={{ flex: 1, minWidth: 0 }}>
          <div className="display" style={{ fontSize: "1rem" }}>
            {String(props.brand ?? "")} {String(props.model ?? "")}
          </div>
          <div className="eyebrow" style={{ marginTop: 2 }}>
            {String(props.year ?? "")} · {String(props.city ?? "")} · score{" "}
            {Number(props.score ?? 0).toFixed(2)}
          </div>

          <div style={{ marginTop: "0.625rem" }}>
            <PriceLine perDay={props.pricePerDay} purchase={props.purchasePrice} />
          </div>

          <ul
            style={{
              margin: "0.75rem 0 0",
              padding: 0,
              listStyle: "none",
              fontSize: "0.8125rem",
              color: "var(--ink-2)",
            }}
          >
            {matched.slice(0, 3).map((m) => (
              <li key={m} style={{ display: "flex", gap: 8 }}>
                <span style={{ color: "var(--ok)" }} aria-hidden>
                  ✓
                </span>
                {m}
              </li>
            ))}
            {tradeoffs.slice(0, 2).map((t) => (
              <li key={t} style={{ display: "flex", gap: 8 }}>
                <span style={{ color: "var(--warn)" }} aria-hidden>
                  ·
                </span>
                {t}
              </li>
            ))}
          </ul>

          {action && (
            <button
              className="btn"
              style={{ marginTop: "0.75rem", fontSize: "0.8125rem" }}
              onClick={() => ctx.dispatch(action, ctx.scope)}
            >
              Book this one
            </button>
          )}
        </div>
      </div>

      {workingId && (
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
          {ctx.renderChild(workingId, ctx.scope)}
        </div>
      )}
    </article>
  );
}

function ConflictNotice({ props }: { props: Props }) {
  const relaxations = (props.relaxations ?? []) as string[];
  return (
    <div
      style={{
        padding: "0.75rem 0.875rem",
        background: "var(--signal-soft)",
        border: "1px solid var(--signal)",
        borderRadius: "var(--radius)",
        fontSize: "0.875rem",
      }}
    >
      <div className="eyebrow" style={{ color: "var(--warn)" }}>
        Can&apos;t satisfy everything
      </div>
      <p style={{ margin: "0.375rem 0 0" }}>{String(props.description ?? "")}</p>
      {relaxations.map((r) => (
        <p key={r} style={{ margin: "0.375rem 0 0", color: "var(--ink-2)" }}>
          {r}
        </p>
      ))}
    </div>
  );
}

function TcoComparison({ props }: { props: Props }) {
  const assumptions = (props.assumptions ?? []) as string[];
  return (
    <div className="card" style={{ padding: "1rem" }}>
      <div className="eyebrow">
        Buying vs renting over {String(props.durationDays ?? "")} days
      </div>
      <dl style={{ margin: "0.75rem 0 0" }}>
        <div className="spec-row">
          <dt>Rent</dt>
          <dd>{rupees(props.rentTotal)}</dd>
        </div>
        <div className="spec-row">
          <dt>Buy and resell</dt>
          <dd>{rupees(props.buyTotal)}</dd>
        </div>
        <div className="spec-row">
          <dt>Buying overtakes at</dt>
          <dd>{String(props.crossoverDays ?? "—")} days</dd>
        </div>
      </dl>
      {typeof props.recommendation === "string" && (
        <p style={{ margin: "0.75rem 0 0", fontSize: "0.875rem" }}>
          {props.recommendation}
        </p>
      )}
      {assumptions.length > 0 && (
        <details style={{ marginTop: "0.75rem" }}>
          <summary className="label" style={{ cursor: "pointer", color: "var(--ink-3)" }}>
            Assumptions
          </summary>
          <ul style={{ margin: "0.5rem 0 0", paddingLeft: "1.25rem", fontSize: "0.8125rem", color: "var(--ink-2)" }}>
            {assumptions.map((a) => (
              <li key={a}>{a}</li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

function ProgressTimeline({ props }: { props: Props }) {
  const steps = (props.steps ?? []) as { label: string; status: string }[];
  if (steps.length === 0) return null;

  return (
    <div>
      {steps.map((step) => (
        <div
          key={step.label}
          style={{
            display: "flex",
            gap: "0.625rem",
            alignItems: "baseline",
            fontSize: "0.8125rem",
            color: step.status === "active" ? "var(--signal)" : "var(--ink-3)",
            padding: "0.1875rem 0",
          }}
        >
          <span
            aria-hidden
            style={{
              width: 5,
              height: 5,
              borderRadius: "50%",
              background: "currentColor",
              opacity: step.status === "done" ? 0.45 : 1,
              transform: "translateY(-2px)",
            }}
          />
          {step.label}
        </div>
      ))}
      {typeof props.remaining === "number" && (
        <div className="figure" style={{ fontSize: "0.75rem", color: "var(--ink-3)" }}>
          {props.remaining} candidates remaining
        </div>
      )}
    </div>
  );
}

function Section({ props, ctx }: { props: Props; ctx: RenderContext }) {
  return (
    <section>
      {typeof props.title === "string" && (
        <div className="eyebrow" style={{ marginBottom: "0.5rem" }}>
          {props.title}
        </div>
      )}
      {ctx.renderChild(String(props.child ?? ""), ctx.scope)}
    </section>
  );
}

function Text({ props }: { props: Props }) {
  const variant = String(props.variant ?? "body");
  const className =
    variant === "eyebrow" ? "eyebrow" : variant === "display" ? "display" : "label";
  return <div className={className}>{String(props.text ?? "")}</div>;
}

/* ------------------------------------------------------------------ */
/* Dispatch                                                            */
/* ------------------------------------------------------------------ */

const CONTAINERS = new Set(["Column", "List"]);

const IMPLEMENTATIONS: Record<
  string,
  (args: { props: Props; ctx: RenderContext }) => React.ReactNode
> = {
  CarCard,
  RankedCarCard,
  ContributionBar,
  ConflictNotice,
  TcoComparison,
  ProgressTimeline,
  Section,
  Text,
};

export function A2uiRenderer({
  surface,
  onAction,
}: {
  surface: Surface;
  onAction?: (name: string, context: Record<string, unknown>) => void;
}) {
  const dispatch = useCallback(
    (action: ActionSpec | undefined, scope: Scope) => {
      const resolved = resolveActionContext(action, scope);
      if (resolved) onAction?.(resolved.name, resolved.context);
    },
    [onAction],
  );

  const renderChild = useCallback(
    (id: string, scope: Scope): React.ReactNode => {
      const component = surface.components[id];
      // Progressive rendering: a definition that has not arrived yet simply
      // contributes nothing, rather than failing the whole tree.
      if (!component) return null;

      const props = resolveProps(component, scope);
      const ctx: RenderContext = {
        surface,
        scope,
        renderChild: (childId, childScope) =>
          renderChild(childId, childScope ?? scope),
        dispatch,
      };

      if (CONTAINERS.has(component.component)) {
        return (
          <div
            key={id}
            style={{ display: "grid", gap: "0.5rem" }}
          >
            {renderChildren(component, scope, ctx)}
          </div>
        );
      }

      const Impl = IMPLEMENTATIONS[component.component];
      if (!Impl) return null;
      return <Impl key={id} props={props} ctx={ctx} />;
    },
    [surface, dispatch],
  );

  const renderChildren = useCallback(
    (component: A2uiComponent, scope: Scope, ctx: RenderContext) => {
      const children = component.children;

      if (Array.isArray(children)) {
        return children.map((childId) => renderChild(String(childId), scope));
      }

      if (isTemplate(children)) {
        // A template creates a child scope per item, which is what makes
        // relative bindings resolve differently in each instance.
        const items = resolvePointer(scope.root, children.path);
        if (!Array.isArray(items)) return null;
        return items.map((item, index) => (
          <div key={index}>
            {ctx.renderChild(children.componentId, { root: scope.root, item })}
          </div>
        ));
      }

      return null;
    },
    [renderChild],
  );

  const tree = useMemo(
    () => renderChild("root", { root: surface.dataModel }),
    [renderChild, surface.dataModel],
  );

  return <>{tree}</>;
}
