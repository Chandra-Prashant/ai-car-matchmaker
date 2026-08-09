/**
 * A2UI renderer core.
 *
 * Holds surfaces, applies the four agent-to-renderer messages, and resolves
 * data bindings. Framework-agnostic on purpose — the React layer sits on top
 * and this can be tested without it.
 *
 * THE ADJACENCY LIST
 * ------------------
 * Components arrive as a flat list referencing each other by id, with
 * exactly one `root`. The tree is reconstructed at render time. That is what
 * lets the agent stream definitions in any order and lets rendering start
 * before every component has arrived.
 *
 * SCOPE
 * -----
 * Paths beginning with `/` resolve from the surface's data model root.
 * Anything else is relative and resolves against the current item when
 * rendering inside a list template — so one `CarCard` definition binding
 * `brand` serves every listing in the array.
 */

export interface A2uiComponent {
  id: string;
  component: string;
  catalogId?: string;
  [key: string]: unknown;
}

export interface Binding {
  path: string;
}

export interface FunctionCall {
  call: string;
  args?: Record<string, unknown>;
}

export interface ChildTemplate {
  path: string;
  componentId: string;
}

export interface ActionSpec {
  event?: {
    name: string;
    context?: Record<string, unknown>;
    wantResponse?: boolean;
  };
  functionCall?: FunctionCall;
}

export interface Surface {
  surfaceId: string;
  catalogId?: string;
  components: Record<string, A2uiComponent>;
  dataModel: Record<string, unknown>;
}

export type A2uiMessage =
  | { version: string; createSurface: Record<string, unknown> }
  | { version: string; updateComponents: Record<string, unknown> }
  | { version: string; updateDataModel: Record<string, unknown> }
  | { version: string; deleteSurface: Record<string, unknown> };

/* ------------------------------------------------------------------ */
/* Guards                                                              */
/* ------------------------------------------------------------------ */

export function isBinding(value: unknown): value is Binding {
  return (
    typeof value === "object" &&
    value !== null &&
    typeof (value as Binding).path === "string" &&
    !("componentId" in value)
  );
}

export function isTemplate(value: unknown): value is ChildTemplate {
  return (
    typeof value === "object" &&
    value !== null &&
    typeof (value as ChildTemplate).path === "string" &&
    typeof (value as ChildTemplate).componentId === "string"
  );
}

export function isFunctionCall(value: unknown): value is FunctionCall {
  return (
    typeof value === "object" &&
    value !== null &&
    typeof (value as FunctionCall).call === "string"
  );
}

/* ------------------------------------------------------------------ */
/* JSON Pointer                                                        */
/* ------------------------------------------------------------------ */

/**
 * Resolve an RFC 6901 pointer against a value.
 *
 * Returns undefined for a missing path rather than throwing: during
 * streaming a component can reference data that has not arrived yet, and the
 * spec asks renderers to degrade gracefully rather than fail.
 */
export function resolvePointer(root: unknown, pointer: string): unknown {
  if (pointer === "" || pointer === "/") return root;

  const segments = pointer
    .replace(/^\//, "")
    .split("/")
    .map((s) => s.replace(/~1/g, "/").replace(/~0/g, "~"));

  let current: unknown = root;
  for (const segment of segments) {
    if (current == null) return undefined;
    if (Array.isArray(current)) {
      const index = Number(segment);
      if (!Number.isInteger(index)) return undefined;
      current = current[index];
    } else if (typeof current === "object") {
      current = (current as Record<string, unknown>)[segment];
    } else {
      return undefined;
    }
  }
  return current;
}

/* ------------------------------------------------------------------ */
/* Renderer-side functions                                             */
/* ------------------------------------------------------------------ */

const CATEGORY_WORDS: Record<string, string> = { suv: "SUV", mpv: "MPV" };

/**
 * The catalog's functions, implemented here rather than shipped as code
 * across the wire — the agent references them by name only.
 */
export const FUNCTIONS: Record<
  string,
  (args: Record<string, unknown>, resolve: (v: unknown) => unknown) => unknown
> = {
  formatRupees(args, resolve) {
    const value = Number(resolve(args.value));
    if (!Number.isFinite(value)) return "—";
    return `₹${value.toLocaleString("en-IN")}`;
  },

  categoryLabel(args, resolve) {
    const value = String(resolve(args.value) ?? "");
    return value
      .split("_")
      .map((w) => CATEGORY_WORDS[w] ?? w.charAt(0).toUpperCase() + w.slice(1))
      .join(" ");
  },

  formatString(args, resolve) {
    const template = String(resolve(args.value) ?? "");
    // ${...} interpolation. Nested calls are out of scope here; the
    // catalog's own components never emit them.
    return template.replace(/\$\{([^}]+)\}/g, (_match, expr: string) =>
      String(resolve({ path: expr.trim() }) ?? ""),
    );
  },
};

/* ------------------------------------------------------------------ */
/* Store                                                               */
/* ------------------------------------------------------------------ */

export class SurfaceStore {
  private surfaces = new Map<string, Surface>();

  list(): string[] {
    return [...this.surfaces.keys()];
  }

  get(surfaceId: string): Surface | undefined {
    return this.surfaces.get(surfaceId);
  }

  /** Apply one envelope message. Returns the affected surface id. */
  apply(message: A2uiMessage): string | null {
    if ("createSurface" in message) {
      const payload = message.createSurface as {
        surfaceId: string;
        catalogId?: string;
        components?: A2uiComponent[];
        dataModel?: Record<string, unknown>;
      };
      this.surfaces.set(payload.surfaceId, {
        surfaceId: payload.surfaceId,
        catalogId: payload.catalogId,
        components: indexById(payload.components ?? []),
        dataModel: payload.dataModel ?? {},
      });
      return payload.surfaceId;
    }

    if ("updateComponents" in message) {
      const payload = message.updateComponents as {
        surfaceId: string;
        components: A2uiComponent[];
      };
      const surface = this.surfaces.get(payload.surfaceId);
      if (!surface) return null;
      surface.components = {
        ...surface.components,
        ...indexById(payload.components),
      };
      return payload.surfaceId;
    }

    if ("updateDataModel" in message) {
      const payload = message.updateDataModel as {
        surfaceId: string;
        path?: string;
        value: unknown;
      };
      const surface = this.surfaces.get(payload.surfaceId);
      if (!surface) return null;
      surface.dataModel = writePointer(
        surface.dataModel,
        payload.path ?? "/",
        payload.value,
      );
      return payload.surfaceId;
    }

    if ("deleteSurface" in message) {
      const payload = message.deleteSurface as { surfaceId: string };
      this.surfaces.delete(payload.surfaceId);
      return payload.surfaceId;
    }

    return null;
  }

  /** A shallow copy, so React sees a new object and re-renders. */
  snapshot(): Map<string, Surface> {
    return new Map(this.surfaces);
  }
}

function indexById(components: A2uiComponent[]): Record<string, A2uiComponent> {
  return Object.fromEntries(components.map((c) => [c.id, c]));
}

/**
 * Upsert semantics, per the spec: an existing path is replaced, a missing
 * one is created, and an explicit null removes the key.
 */
function writePointer(
  root: Record<string, unknown>,
  pointer: string,
  value: unknown,
): Record<string, unknown> {
  if (pointer === "" || pointer === "/") {
    return (value ?? {}) as Record<string, unknown>;
  }

  const segments = pointer.replace(/^\//, "").split("/");
  const next = { ...root };
  let cursor: Record<string, unknown> = next;

  for (let i = 0; i < segments.length - 1; i += 1) {
    const key = segments[i];
    const existing = cursor[key];
    cursor[key] =
      typeof existing === "object" && existing !== null ? { ...existing } : {};
    cursor = cursor[key] as Record<string, unknown>;
  }

  const last = segments[segments.length - 1];
  if (value === null) delete cursor[last];
  else cursor[last] = value;

  return next;
}

/* ------------------------------------------------------------------ */
/* Binding resolution                                                  */
/* ------------------------------------------------------------------ */

export interface Scope {
  /** The surface's data model. */
  root: Record<string, unknown>;
  /** The current item, when rendering inside a list template. */
  item?: unknown;
}

/**
 * Turn a component property into a concrete value.
 *
 * Handles the three forms a Dynamic* property can take: a literal, a
 * `{path}` binding, or a `{call, args}` function invocation.
 */
export function resolveValue(value: unknown, scope: Scope): unknown {
  if (isFunctionCall(value)) {
    const impl = FUNCTIONS[value.call];
    if (!impl) return undefined;
    return impl(value.args ?? {}, (v) => resolveValue(v, scope));
  }

  if (isBinding(value)) {
    const pointer = value.path;
    if (pointer.startsWith("/")) return resolvePointer(scope.root, pointer);
    // Relative: resolve against the current template item.
    return resolvePointer(scope.item ?? scope.root, `/${pointer}`);
  }

  return value;
}

/** Resolve every property of a component against the current scope. */
export function resolveProps(
  component: A2uiComponent,
  scope: Scope,
): Record<string, unknown> {
  const resolved: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(component)) {
    if (key === "id" || key === "component" || key === "catalogId") continue;
    // children and action keep their raw shape — the renderer interprets
    // them structurally rather than as values.
    if (key === "children" || key === "child" || key === "action") {
      resolved[key] = value;
      continue;
    }
    resolved[key] = resolveValue(value, scope);
  }
  return resolved;
}

/** Resolve an action's context bindings at dispatch time. */
export function resolveActionContext(
  action: ActionSpec | undefined,
  scope: Scope,
): { name: string; context: Record<string, unknown> } | null {
  if (!action?.event) return null;
  const context: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(action.event.context ?? {})) {
    context[key] = resolveValue(value, scope);
  }
  return { name: action.event.name, context };
}
