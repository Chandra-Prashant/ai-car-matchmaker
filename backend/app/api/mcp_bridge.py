"""MCP bridge — the host side of the MCP Apps flow.

Serves T038-T041 and FR-017, FR-020.

WHY THE BACKEND IS THE MCP CLIENT
---------------------------------
MCP servers speak stdio or streamable HTTP; a browser can speak neither to a
local subprocess. So the backend holds the client connections and exposes two
narrow operations to the frontend:

    GET  /api/mcp/resource   fetch a ui:// resource's HTML and CSP
    POST /api/mcp/call       relay a tool call from a View

The mcp v2 `Client` accepts an `MCPServer` instance directly, so these
connect over an in-memory transport rather than spawning processes. It is the
same protocol — real initialize, real list_tools, real read_resource — with
one less moving part. The servers keep their `main()` entrypoints and still
run standalone under any external MCP host, which is how they were verified.

THE ALLOWLIST
-------------
A View may only call tools its own server marks `visibility: ["app"]` —
app-only, not merely app-visible. The specification's default visibility is
["model", "app"], which would let a View reopen itself or invoke a
model-facing tool; there is no reason a booking form needs to launch a
booking form. Restricting to app-only means a server author opts a tool in to
View access explicitly.

The list is read from the server's own tool metadata rather than configured
here, so this module cannot drift out of sync with what the servers declare.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, HTTPException, Query
from mcp.client import Client
from pydantic import BaseModel

from app.mcp_servers.booking_form.server import mcp as booking_server
from app.mcp_servers.checkout.server import mcp as checkout_server
from app.mcp_servers.marketplace.server import mcp as marketplace_server

router = APIRouter(prefix="/api/mcp", tags=["mcp"])

#: Servers this host will connect to. The key is what a View passes as
#: `server`; nothing outside this mapping is reachable.
SERVERS = {
    "booking-form": booking_server,
    "checkout": checkout_server,
    "marketplace": marketplace_server,
}

#: Which server owns which UI resource, so the frontend only needs the URI.
RESOURCE_OWNERS = {
    "ui://booking/form": "booking-form",
    "ui://checkout/payment": "checkout",
}

UI_MIME = "text/html;profile=mcp-app"

#: Applied when a resource declares no `ui.csp`. Matches the restrictive
#: default the specification requires of hosts.
DEFAULT_CSP: dict[str, list[str]] = {
    "connectDomains": [],
    "resourceDomains": [],
    "frameDomains": [],
    "baseUriDomains": [],
}


class ToolCallRequest(BaseModel):
    server: str
    tool: str
    arguments: dict[str, Any] = {}


class UiResource(BaseModel):
    uri: str
    server: str
    html: str
    csp: dict[str, list[str]]
    prefers_border: bool = False


def _server_or_404(name: str):
    server = SERVERS.get(name)
    if server is None:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown server. Available: {sorted(SERVERS)}",
        )
    return server


def _ui_meta(obj: Any) -> dict[str, Any]:
    meta = getattr(obj, "meta", None) or {}
    return meta.get("ui") or {}


async def _app_only_tools(server) -> set[str]:
    """Tool names a View may call: those marked exactly app-only.

    Read from the server rather than configured here — the server owns the
    decision, and duplicating it would create two sources of truth that can
    disagree.
    """
    async with Client(server) as client:
        result = await client.list_tools()

    return {
        tool.name
        for tool in result.tools
        if _ui_meta(tool).get("visibility") == ["app"]
    }


def _build_csp(declared: dict | None) -> dict[str, list[str]]:
    """Merge a resource's declared CSP over the restrictive default."""
    csp = {key: list(value) for key, value in DEFAULT_CSP.items()}
    for key, value in (declared or {}).items():
        if key in csp and isinstance(value, list):
            csp[key] = [str(v) for v in value]
    return csp


@router.get("/resource", response_model=UiResource)
async def get_ui_resource(
    uri: Annotated[str, Query(description="A ui:// resource URI")],
    server: Annotated[str | None, Query(description="Owning server")] = None,
) -> UiResource:
    """Fetch a UI resource for the sandbox to render.

    HTML and CSP travel together: the host constructs the policy the View
    runs under, and the View never gets to choose its own.
    """
    if not uri.startswith("ui://"):
        raise HTTPException(status_code=400, detail="Not a ui:// resource")

    owner = server or RESOURCE_OWNERS.get(uri)
    if owner is None:
        raise HTTPException(
            status_code=404, detail=f"No server known to own {uri}"
        )

    target = _server_or_404(owner)

    async with Client(target) as client:
        try:
            result = await client.read_resource(uri)
        except Exception as exc:  # noqa: BLE001 - surfaced to the caller
            raise HTTPException(
                status_code=404, detail=f"Cannot read {uri}: {exc}"
            ) from exc

    if not result.contents:
        raise HTTPException(status_code=404, detail=f"{uri} returned no content")

    content = result.contents[0]
    if UI_MIME not in str(content.mime_type or ""):
        raise HTTPException(
            status_code=415,
            detail=f"{uri} is {content.mime_type}, not an MCP App resource",
        )

    ui = _ui_meta(content)

    return UiResource(
        uri=uri,
        server=owner,
        html=content.text or "",
        csp=_build_csp(ui.get("csp")),
        prefers_border=bool(ui.get("prefersBorder")),
    )


@router.post("/call")
async def relay_tool_call(
    body: Annotated[ToolCallRequest, Body()],
) -> dict[str, Any]:
    """Relay a tool call from a View to its MCP server.

    Refused unless the target server marks the tool app-only. A View cannot
    reach model-facing tools, and cannot reach another server at all.
    """
    target = _server_or_404(body.server)

    permitted = await _app_only_tools(target)
    if body.tool not in permitted:
        raise HTTPException(
            status_code=403,
            detail=(
                f"{body.tool} is not callable from a UI on {body.server}. "
                f"Callable: {sorted(permitted) or 'none'}"
            ),
        )

    async with Client(target) as client:
        result = await client.call_tool(body.tool, body.arguments)

    content = [
        {"type": "text", "text": block.text}
        for block in (result.content or [])
        if getattr(block, "text", None)
    ]

    return {
        "content": content,
        "structuredContent": getattr(result, "structured_content", None)
        or getattr(result, "structuredContent", None),
        "isError": bool(getattr(result, "is_error", False)),
    }


@router.get("/servers")
async def list_servers() -> dict[str, Any]:
    """What this host exposes — used by the frontend and for debugging."""
    summary: dict[str, Any] = {}

    for name, server in SERVERS.items():
        async with Client(server) as client:
            tools = (await client.list_tools()).tools
            resources = (await client.list_resources()).resources

        summary[name] = {
            "tools": [
                {
                    "name": tool.name,
                    "visibility": _ui_meta(tool).get("visibility"),
                    "ui_resource": _ui_meta(tool).get("resourceUri"),
                    "app_callable": _ui_meta(tool).get("visibility") == ["app"],
                }
                for tool in tools
            ],
            "ui_resources": [
                str(resource.uri)
                for resource in resources
                if UI_MIME in str(resource.mime_type or "")
            ],
        }

    return summary
