"use client";

/**
 * MCP App host.
 *
 * Renders a View according to SEP-1865: this component creates the sandbox
 * proxy iframe on a separate origin, drives the lifecycle handshake, and
 * relays permitted tool calls to the backend.
 *
 * LIFECYCLE
 *   sandbox → host   ui/notifications/sandbox-proxy-ready
 *   host → sandbox   ui/notifications/sandbox-resource-ready   (HTML + CSP)
 *   view → host      ui/initialize                             → result
 *   view → host      ui/notifications/initialized
 *   host → view      ui/notifications/tool-input
 *   host → view      ui/notifications/tool-result
 *
 * Nothing is sent to the View before `initialized`, as the spec requires.
 *
 * The host is the only party that talks to the MCP server. A View's
 * `tools/call` goes to /api/mcp/call, which refuses anything the server has
 * not marked app-callable — so this component never has to decide what is
 * safe to invoke.
 */

import { useCallback, useEffect, useRef, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const SANDBOX = process.env.NEXT_PUBLIC_SANDBOX_URL ?? "http://localhost:3001";

interface UiResource {
  uri: string;
  server: string;
  html: string;
  csp: Record<string, string[]>;
  prefers_border: boolean;
}

interface Rpc {
  jsonrpc: "2.0";
  id?: number | string;
  method?: string;
  params?: Record<string, unknown>;
  result?: unknown;
  error?: { code: number; message: string };
}

export function McpAppFrame({
  uri,
  server,
  toolName,
  toolInput,
  toolResult,
  onMessage,
  onClose,
}: {
  uri: string;
  server: string;
  toolName: string;
  toolInput: Record<string, unknown>;
  toolResult: Record<string, unknown> | null;
  onMessage?: (text: string) => void;
  onClose?: () => void;
}) {
  const frameRef = useRef<HTMLIFrameElement>(null);
  const [resource, setResource] = useState<UiResource | null>(null);
  const [height, setHeight] = useState(320);
  const [error, setError] = useState<string | null>(null);
  const initialised = useRef(false);

  // The message listener must stay attached for the whole life of the View.
  // toolInput, toolResult and the callbacks are fresh identities on every
  // parent render — and the transcript re-renders continuously while events
  // stream — so depending on them directly would detach and reattach the
  // listener repeatedly, dropping whatever handshake message arrived in the
  // gap. Holding them in a ref lets the effect depend only on `resource`.
  const latest = useRef({ toolName, toolInput, toolResult, onMessage, onClose });
  latest.current = { toolName, toolInput, toolResult, onMessage, onClose };

  useEffect(() => {
    let cancelled = false;
    const params = new URLSearchParams({ uri, server });

    // no-store: the View HTML is read from disk on every request, so a
    // cached response would silently serve a stale UI after an edit.
    fetch(`${API}/api/mcp/resource?${params}`, { cache: "no-store" })
      .then((r) => {
        if (!r.ok) throw new Error(`${r.status}`);
        return r.json() as Promise<UiResource>;
      })
      .then((data) => {
        if (!cancelled) setResource(data);
      })
      .catch(() => {
        if (!cancelled) setError("Couldn't load this step. Try again.");
      });

    return () => {
      cancelled = true;
    };
  }, [uri, server]);

  const send = useCallback((message: Rpc) => {
    frameRef.current?.contentWindow?.postMessage(message, SANDBOX);
  }, []);

  const respond = useCallback(
    (id: number | string | undefined, result: unknown) => {
      if (id === undefined) return;
      send({ jsonrpc: "2.0", id, result });
    },
    [send],
  );

  const fail = useCallback(
    (id: number | string | undefined, message: string) => {
      if (id === undefined) return;
      send({ jsonrpc: "2.0", id, error: { code: -32000, message } });
    },
    [send],
  );

  useEffect(() => {
    if (!resource) return;

    async function handle(event: MessageEvent) {
      // Origin check on every inbound message: only the sandbox may speak
      // to the host.
      if (event.origin !== SANDBOX) return;

      // Source check too. Several Views can be mounted at once — a booking
      // form and a checkout, say — and every frame receives every message
      // from the sandbox origin. Without this, one frame answers another's
      // handshake and posts the reply into the wrong iframe, leaving both
      // Views waiting on responses that went elsewhere.
      if (event.source !== frameRef.current?.contentWindow) return;
      const msg = event.data as Rpc;
      if (!msg || msg.jsonrpc !== "2.0") return;

      switch (msg.method) {
        case "ui/notifications/sandbox-proxy-ready":
          send({
            jsonrpc: "2.0",
            method: "ui/notifications/sandbox-resource-ready",
            params: { html: resource!.html, csp: resource!.csp },
          });
          return;

        case "ui/initialize":
          respond(msg.id, {
            protocolVersion: "2026-01-26",
            hostInfo: { name: "car-matchmaker", version: "0.1.0" },
            hostCapabilities: { availableDisplayModes: ["inline"] },
            hostContext: {
              theme: "light",
              displayMode: "inline",
              // Pass the page's own tokens through so the View belongs to
              // the interface rather than looking bolted on.
              styles: {
                variables: {
                  "--color-background-primary": "#ffffff",
                  "--color-background-secondary": "#eef0f2",
                  "--color-text-primary": "#14181c",
                  "--color-text-secondary": "#4a545e",
                  "--color-border-primary": "#dfe3e7",
                  "--border-radius-md": "3px",
                  // A literal stack, not var(--font-inter): CSS custom
                  // properties do not cross the iframe document boundary,
                  // so a variable reference resolves to nothing inside the
                  // View and it falls back to a serif default.
                  "--font-sans":
                    "Inter, system-ui, -apple-system, sans-serif",
                },
              },
            },
          });
          return;

        case "ui/notifications/initialized":
          initialised.current = true;
          send({
            jsonrpc: "2.0",
            method: "ui/notifications/tool-input",
            params: {
              toolName: latest.current.toolName,
              arguments: latest.current.toolInput,
            },
          });
          if (latest.current.toolResult) {
            send({
              jsonrpc: "2.0",
              method: "ui/notifications/tool-result",
              params: latest.current.toolResult,
            });
          }
          return;

        case "ui/notifications/size-changed": {
          const h = Number((msg.params as { height?: number })?.height ?? 0);
          if (h > 0) setHeight(Math.min(900, Math.max(160, h + 8)));
          return;
        }

        case "ui/message": {
          const content = (msg.params as { content?: { text?: string } })
            ?.content;
          if (content?.text) latest.current.onMessage?.(content.text);
          respond(msg.id, {});
          latest.current.onClose?.();
          return;
        }

        case "ui/open-link": {
          const url = String((msg.params as { url?: string })?.url ?? "");
          if (url.startsWith("https://")) window.open(url, "_blank", "noopener");
          respond(msg.id, {});
          return;
        }

        case "ui/request-display-mode":
          // Only inline is offered, so acknowledge without changing.
          respond(msg.id, { displayMode: "inline" });
          return;

        case "tools/call": {
          const params = msg.params as {
            name?: string;
            arguments?: Record<string, unknown>;
          };
          try {
            const response = await fetch(`${API}/api/mcp/call`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                server: resource!.server,
                tool: params?.name,
                arguments: params?.arguments ?? {},
              }),
            });
            if (!response.ok) {
              const detail = await response.json().catch(() => ({}));
              fail(msg.id, String(detail.detail ?? response.status));
              return;
            }
            respond(msg.id, await response.json());
          } catch {
            fail(msg.id, "The request could not be completed.");
          }
          return;
        }

        case "resources/read":
          fail(msg.id, "Resource reads are not relayed.");
          return;

        default:
          // Unknown methods with an id must still be answered, or the View
          // waits forever.
          if (msg.id !== undefined) {
            fail(msg.id, `Unsupported method: ${msg.method}`);
          }
      }
    }

    window.addEventListener("message", handle);
    return () => window.removeEventListener("message", handle);
  }, [resource, send, respond, fail]);

  // Deliver a result that arrives after the View is already up.
  useEffect(() => {
    if (initialised.current && toolResult) {
      send({
        jsonrpc: "2.0",
        method: "ui/notifications/tool-result",
        params: toolResult,
      });
    }
  }, [toolResult, send]);

  if (error) {
    return (
      <div
        className="card"
        style={{ padding: "0.75rem 1rem", color: "var(--stop)", fontSize: "0.875rem" }}
      >
        {error}
      </div>
    );
  }

  if (!resource) {
    return (
      <div className="card" style={{ padding: "0.75rem 1rem" }}>
        <span className="eyebrow">Loading</span>
      </div>
    );
  }

  return (
    <div
      className={resource.prefers_border ? "card" : undefined}
      style={{ overflow: "hidden" }}
    >
      <iframe
        ref={frameRef}
        src={SANDBOX}
        title={toolName}
        // The iframe is created only once the resource is in hand. Mounting
        // it earlier races the proxy's sandbox-proxy-ready announcement
        // against the fetch: the proxy speaks, nothing is listening yet, and
        // the View waits forever on a handshake that already happened.
        onLoad={() => {
          send({
            jsonrpc: "2.0",
            method: "ui/notifications/sandbox-resource-ready",
            params: { html: resource.html, csp: resource.csp },
          });
        }}
        style={{ width: "100%", height, border: 0, display: "block" }}
      />
    </div>
  );
}
