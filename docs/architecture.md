# Architecture Notes

## MCP Apps — confirmed protocol shape (T008)

Verified against `modelcontextprotocol/ext-apps`, specification `2026-01-26`.
**Status: Stable.** Field names below are copied from the specification, not
from memory or secondary tutorials.

### Extension identity

| Item | Value |
|---|---|
| Extension identifier | `io.modelcontextprotocol/ui` |
| UI resource URI scheme | `ui://` |
| UI resource mimeType | `text/html;profile=mcp-app` |
| Reserved prefix | `ui://` and the label `io.modelcontextprotocol/ui` |

### Capability negotiation

The host advertises support in the standard `initialize` request:

```json
{
  "method": "initialize",
  "params": {
    "capabilities": {
      "extensions": {
        "io.modelcontextprotocol/ui": {
          "mimeTypes": ["text/html;profile=mcp-app"]
        }
      }
    }
  }
}
```

`mimeTypes` is REQUIRED. Servers SHOULD check this before registering
UI-enabled tools and register text-only variants otherwise.

### Tool → UI linkage

```json
{
  "name": "open_booking_form",
  "description": "...",
  "inputSchema": { "type": "object" },
  "_meta": {
    "ui": {
      "resourceUri": "ui://booking/form",
      "visibility": ["model", "app"]
    }
  }
}
```

- The key is **`_meta.ui.resourceUri`** (nested).
- The flat form `_meta["ui/resourceUri"]` is **deprecated** and will be removed
  before GA. Do not use it.
- `visibility` defaults to `["model", "app"]`.
  - `"model"` — visible to and callable by the agent.
  - `"app"` — callable by the View, from the same server connection only.
  - App-only tools (`["app"]`) MUST NOT appear in the agent's tool list. This
    is how form submission and checkout actions stay out of the model's
    surface while remaining callable from the UI.

### UI resource declaration and content

Declared like any MCP resource; content served via `resources/read`:

```json
{
  "contents": [{
    "uri": "ui://booking/form",
    "mimeType": "text/html;profile=mcp-app",
    "text": "<!DOCTYPE html>...",
    "_meta": {
      "ui": {
        "csp": {
          "connectDomains": [],
          "resourceDomains": [],
          "frameDomains": [],
          "baseUriDomains": []
        },
        "prefersBorder": true
      }
    }
  }]
}
```

Content MUST be a valid HTML5 document, supplied as `text` or base64 `blob`.

Omitting `ui.csp` makes the host apply a restrictive default
(`default-src 'none'`, `connect-src 'none'`, self-only scripts and styles).
**For this project that default is correct** — neither the booking form nor the
checkout needs an external origin, so both declare no CSP domains.

### Web host architecture — double iframe (MANDATORY)

> This corrects `plan.md` §7.4, which described a single sandboxed iframe and
> advised against combining `allow-scripts` with `allow-same-origin`.

If the host is a web page, it MUST wrap the View in an intermediate **Sandbox
Proxy**:

1. Host and Sandbox MUST be on **different origins**.
2. The Sandbox iframe MUST have `allow-scripts` and `allow-same-origin`. This
   is safe precisely because of (1) — origin separation is the containment
   boundary, not the sandbox attribute.
3. Sandbox sends `ui/notifications/sandbox-proxy-ready` to the host.
4. Host replies with `ui/notifications/sandbox-resource-ready`, carrying the
   raw HTML plus CSP and permission metadata.
5. Sandbox renders the View in an inner iframe under the host-constructed CSP.
6. Sandbox forwards messages both ways, except any method prefixed
   `ui/notifications/sandbox-`.
7. Sandbox SHOULD NOT originate its own requests.
8. Host MAY forward View messages to the MCP server for any method not
   prefixed `ui/`, and MAY block or gate them on user approval.

**Practical consequence for this project:** the frontend needs a second origin
in development. A different port suffices, since origin is scheme + host +
port. Plan for `localhost:3000` (host) and `localhost:3001` (sandbox proxy).

### Lifecycle

```
tools/call (host → server, tool carries _meta.ui)
  ├─ Host renders Sandbox Proxy (separate origin)
  ├─ Sandbox → Host   ui/notifications/sandbox-proxy-ready
  ├─ Host → Sandbox   ui/notifications/sandbox-resource-ready  (HTML + CSP)
  ├─ View  → Host     ui/initialize            (appCapabilities)
  ├─ Host  → View     McpUiInitializeResult    (hostCapabilities, hostContext)
  ├─ View  → Host     ui/notifications/initialized
  ├─ Host  → View     ui/notifications/tool-input-partial   (0..n, optional)
  ├─ Host  → View     ui/notifications/tool-input           (complete, once)
  └─ Host  → View     ui/notifications/tool-result | ui/notifications/tool-cancelled
```

The host MUST NOT send anything to the View before `initialized`.
Teardown: host sends `ui/resource-teardown` and SHOULD await the response
before destroying the iframe, to prevent data loss.

### Message inventory

**Standard MCP subset available to the View:**
`tools/call`, `resources/read`, `notifications/message`, `ping`.

**View → Host (MCP Apps specific):**

| Method | Purpose |
|---|---|
| `ui/open-link` | Open an external URL in the host's browser |
| `ui/message` | Push a message into the host's chat |
| `ui/request-display-mode` | Request `inline` / `fullscreen` / `pip` |
| `ui/update-model-context` | Set context for future model turns (overwrites) |

**Host → View:**

| Method | Purpose |
|---|---|
| `ui/notifications/tool-input` | Complete tool arguments (once, required) |
| `ui/notifications/tool-input-partial` | Streaming partial arguments (optional) |
| `ui/notifications/tool-result` | `CallToolResult` on completion |
| `ui/notifications/tool-cancelled` | Execution cancelled, with reason |
| `ui/notifications/host-context-changed` | Partial `HostContext` update |
| `ui/resource-teardown` | Pre-teardown, expects a response |

**View → Host (notification):** `ui/notifications/size-changed` with
`{width, height}`, sent when content size changes. Required when the host
uses flexible dimensions.

### Data passing

- `content` — text representation, goes into model context and serves
  text-only hosts. This is the graceful-degradation path (Constitution VII).
- `structuredContent` — structured data for UI rendering; **not** added to
  model context.
- `_meta` — metadata not intended for model context.

This split matters for us: listing data for `CarCard` rendering belongs in
`structuredContent`, while the text summary in `content` is what a non-UI host
and the model itself see.

### Theming

The host may pass CSS custom properties via `hostContext.styles.variables`
(e.g. `--color-background-primary`, `--color-text-primary`, `--font-sans`,
`--border-radius-md`). Views SHOULD declare fallback values for every variable
they use, since hosts may pass a partial set or none at all.

Spacing variables are deliberately absent from the standard set.

---

## Known limitations

### Inventory model years

`app/inventory/generator.py` does not model when a given car model was
introduced, so a listing may carry a model year predating that model's real
launch. Correcting this would require a `since` field on every catalogue
entry. Judged not worth the cost for mock inventory; recorded here rather than
left for a reviewer to discover.

### Currency conversion

EUR prices are derived from INR at a single fixed rate declared in
`app/inventory/taxonomy.py`. Real prices for the same vehicle diverge between
markets for tax and regulatory reasons this project does not model.
