# Frontend

Next.js client for the AI Car Matchmaker. See the [root README](../README.md)
to run the whole system.

- `components/a2ui/` — the A2UI renderer and the catalog's component
  implementations. The agent names components and binds data; how they look
  lives here.
- `components/mcp-host/` — the MCP Apps host: creates the sandbox proxy
  iframe, drives the SEP-1865 handshake, relays permitted tool calls.
- `lib/a2ui/store.ts` — surface state, JSON Pointer resolution, list templates
  with per-item scope.
- `hooks/useAgentSession.ts` — consumes the SSE event stream.

Requires the backend on `:8000` and the sandbox proxy on `:3001`. The latter
must be a separate origin — that separation is what contains MCP App views.
