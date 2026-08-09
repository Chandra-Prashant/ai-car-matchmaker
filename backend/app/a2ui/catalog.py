"""A2UI component catalog.

Defines the component vocabulary the agent may use to describe UI, per the
A2UI v1.0 specification.

WHY A CUSTOM CATALOG RATHER THAN THE BASIC ONE
----------------------------------------------
The specification anticipates this: "most production applications will define
their own catalog to reflect their specific design system." Composing a
ranked car card out of Rows, Columns and Texts would produce a generic
layout and hand the agent responsibility for visual decisions it should not
be making.

Instead the catalog exposes the vocabulary of this product — CarCard,
RankedCarCard, ContributionBar — and the renderer owns how each one looks.
The agent describes *what* to show; the client decides *how*. That is the
point of the protocol, and it also means the existing React components are
the implementation rather than something to be replaced.

STRUCTURAL RULES (spec section: Catalog Schema Rules and Conventions)
--------------------------------------------------------------------
- Component names follow UAX #31 identifier rules.
- Every component schema declares `component` as a const matching its key.
- Components combine `ComponentCommon` with their own properties via allOf.
- Child references use ComponentId; child lists use ChildList — validators
  detect structural links by these refs, and a bare string would be treated
  as static text.
- `$defs` holds only `anyComponent` and `anyFunction`.
- Only the permitted root-level keys appear.
"""

from __future__ import annotations

from typing import Any

CATALOG_ID = "https://carmatchmaker.dev/catalogs/v1"
PROTOCOL_VERSION = "1.0"
A2UI_VERSION = "v1.0"

_COMMON = "https://a2ui.org/specification/v1_0/common_types.json"


def _ref(name: str) -> dict[str, str]:
    return {"$ref": f"{_COMMON}#/$defs/{name}"}


def _component(
    name: str,
    description: str,
    properties: dict[str, Any],
    required: list[str] | None = None,
    allowed_parents: list[str] | None = None,
) -> dict[str, Any]:
    """Build one catalog component entry in the shape the spec mandates."""
    schema: dict[str, Any] = {
        "type": "object",
        "description": description,
        "allOf": [
            {"$ref": f"{_COMMON}#/$defs/ComponentCommon"},
            {
                "type": "object",
                "properties": {
                    "component": {"const": name},
                    **properties,
                },
                "required": ["component", *(required or [])],
            },
        ],
        "unevaluatedProperties": False,
    }
    if allowed_parents:
        schema["allowedParents"] = allowed_parents
    return schema


# --------------------------------------------------------------------------
# Components
# --------------------------------------------------------------------------

COMPONENTS: dict[str, dict[str, Any]] = {
    # ---- layout ----------------------------------------------------------
    "Column": _component(
        "Column",
        "A vertical stack of components.",
        {
            "children": _ref("ChildList"),
            "gap": _ref("DynamicString"),
        },
        required=["children"],
    ),
    "Section": _component(
        "Section",
        "A titled group. The title renders as a small uppercase eyebrow.",
        {
            "title": _ref("DynamicString"),
            "child": _ref("ComponentId"),
        },
        required=["child"],
    ),
    "Text": _component(
        "Text",
        "A run of text. Supports simple Markdown.",
        {
            "text": _ref("DynamicString"),
            "variant": {
                "type": "string",
                "enum": ["body", "caption", "eyebrow", "display"],
                "description": "Typographic role. Defaults to body.",
            },
        },
        required=["text"],
    ),
    "Button": _component(
        "Button",
        "A button that dispatches an action to the agent.",
        {
            "label": _ref("DynamicString"),
            "variant": {"type": "string", "enum": ["primary", "quiet"]},
            "action": _ref("Action"),
        },
        required=["label"],
    ),

    # ---- domain ----------------------------------------------------------
    "CarCard": _component(
        "CarCard",
        (
            "One listing shown as a specification card: make, model, year, "
            "seller and price. Use inside a List bound to a listings array; "
            "bind each property with a relative path."
        ),
        {
            "brand": _ref("DynamicString"),
            "model": _ref("DynamicString"),
            "year": _ref("DynamicNumber"),
            "seller": _ref("DynamicString"),
            "city": _ref("DynamicString"),
            "pricePerDay": _ref("DynamicNumber"),
            "purchasePrice": _ref("DynamicNumber"),
            "action": _ref("Action"),
        },
        required=["brand", "model"],
    ),
    "RankedCarCard": _component(
        "RankedCarCard",
        (
            "A ranked recommendation: the listing, its position, its score, "
            "the criteria it satisfies and the compromises it makes. Expands "
            "to reveal a ContributionBar when one is supplied as `working`."
        ),
        {
            "rank": _ref("DynamicNumber"),
            "brand": _ref("DynamicString"),
            "model": _ref("DynamicString"),
            "year": _ref("DynamicNumber"),
            "city": _ref("DynamicString"),
            "score": _ref("DynamicNumber"),
            "pricePerDay": _ref("DynamicNumber"),
            "purchasePrice": _ref("DynamicNumber"),
            "matched": _ref("DynamicStringList"),
            "tradeoffs": _ref("DynamicStringList"),
            "working": _ref("ComponentId"),
            "action": _ref("Action"),
        },
        required=["rank", "brand", "model"],
    ),
    "ContributionBar": _component(
        "ContributionBar",
        (
            "Why a listing scored as it did: each criterion's weighted "
            "contribution as a segment of one bar, with the per-criterion "
            "breakdown beneath. Bind `breakdown` to a list of objects with "
            "criterion, rawScore and weight."
        ),
        {
            "breakdown": {
                "description": "Path to a list of score components.",
                "oneOf": [
                    {"type": "array", "items": {"type": "object"}},
                    {"type": "object", "properties": {"path": {"type": "string"}}},
                ],
            },
            "weightSource": _ref("DynamicString"),
        },
        required=["breakdown"],
    ),
    "ConstraintPanel": _component(
        "ConstraintPanel",
        (
            "What the agent has understood so far, as a specification sheet: "
            "captured requirements, what is still needed, and any conflicts. "
            "Created once per session and refreshed with updateDataModel."
        ),
        {
            "phase": _ref("DynamicString"),
            "known": {
                "description": "Path to an object of captured constraints.",
                "oneOf": [
                    {"type": "object"},
                    {"type": "object", "properties": {"path": {"type": "string"}}},
                ],
            },
            "missing": _ref("DynamicStringList"),
            "conflicts": _ref("DynamicStringList"),
            "shortlistSize": _ref("DynamicNumber"),
        },
        required=["phase"],
    ),
    "ProgressTimeline": _component(
        "ProgressTimeline",
        (
            "Live view of what the agent is doing: the current step and how "
            "many candidates remain. Refreshed with updateDataModel as the "
            "search narrows."
        ),
        {
            "steps": {
                "description": "Path to a list of {label, status} objects.",
                "oneOf": [
                    {"type": "array", "items": {"type": "object"}},
                    {"type": "object", "properties": {"path": {"type": "string"}}},
                ],
            },
            "remaining": _ref("DynamicNumber"),
        },
        required=["steps"],
    ),
    "TcoComparison": _component(
        "TcoComparison",
        (
            "Cost of buying against renting over a stated period, with the "
            "crossover point and the assumptions behind it."
        ),
        {
            "durationDays": _ref("DynamicNumber"),
            "buyTotal": _ref("DynamicNumber"),
            "rentTotal": _ref("DynamicNumber"),
            "crossoverDays": _ref("DynamicNumber"),
            "recommendation": _ref("DynamicString"),
            "assumptions": _ref("DynamicStringList"),
        },
        required=["durationDays"],
    ),
    "ConflictNotice": _component(
        "ConflictNotice",
        (
            "A requirement that cannot be satisfied, with the specific "
            "relaxations that would resolve it."
        ),
        {
            "description": _ref("DynamicString"),
            "relaxations": _ref("DynamicStringList"),
        },
        required=["description"],
    ),
    "List": _component(
        "List",
        (
            "A scrollable list. Bind `children` to a data path with a "
            "template componentId to repeat a component per item."
        ),
        {"children": _ref("ChildList")},
        required=["children"],
    ),
}


# --------------------------------------------------------------------------
# Functions
# --------------------------------------------------------------------------


def _function(
    name: str,
    description: str,
    args: dict[str, Any] | None,
    return_type: str,
    callable_from: str = "rendererOnly",
) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "type": "object",
        "description": description,
        "returnType": return_type,
        "callableFrom": callable_from,
        "properties": {"call": {"const": name}},
        "required": ["call"],
        "unevaluatedProperties": False,
    }
    if args is not None:
        schema["properties"]["args"] = {
            "type": "object",
            "properties": args,
            "additionalProperties": False,
        }
        schema["required"].append("args")
    return schema


FUNCTIONS: dict[str, dict[str, Any]] = {
    "formatString": _function(
        "formatString",
        "Interpolates data model values into a string using ${...} syntax.",
        {"value": {"type": "string"}},
        "string",
    ),
    "formatRupees": _function(
        "formatRupees",
        (
            "Formats a number as Indian rupees with lakh/crore grouping — "
            "1052000 becomes Rs.10,52,000."
        ),
        {"value": {"description": "The amount in rupees."}},
        "string",
    ),
    "categoryLabel": _function(
        "categoryLabel",
        "Turns a catalogue category into prose: compact_suv -> Compact SUV.",
        {"value": {"description": "The category key."}},
        "string",
    ),
}


CATALOG: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": CATALOG_ID,
    "protocolVersion": PROTOCOL_VERSION,
    "title": "Car Matchmaker Catalog",
    "description": (
        "Components for describing car listings, ranked recommendations and "
        "agent progress."
    ),
    "catalogId": CATALOG_ID,
    "instructions": (
        "Use CarCard for search results and RankedCarCard for explained "
        "recommendations — never compose them from Rows and Texts. Bind "
        "repeated content with a List whose children reference a template "
        "component and a data path, rather than emitting one component per "
        "item. Every RankedCarCard should reference a ContributionBar as its "
        "`working` so the user can see how the score was reached. Keep "
        "surfaces small: one surface per result set."
    ),
    "components": COMPONENTS,
    "functions": FUNCTIONS,
    "$defs": {
        "anyComponent": {
            "oneOf": [{"$ref": f"#/components/{name}"} for name in COMPONENTS],
            "discriminator": {"propertyName": "component"},
        },
        "anyFunction": {
            "oneOf": [{"$ref": f"#/functions/{name}"} for name in FUNCTIONS],
        },
    },
}


def validate_catalog() -> None:
    """Assert the structural rules the spec requires of a catalog.

    Cheap to run and catches the mistakes that would otherwise surface as a
    renderer silently skipping a component.
    """
    import re

    identifier = re.compile(r"^[^\W\d]\w*$", re.UNICODE)

    allowed_root = {
        "$schema", "$id", "protocolVersion", "title", "description",
        "catalogId", "instructions", "components", "functions", "$defs",
    }
    extra = set(CATALOG) - allowed_root
    assert not extra, f"disallowed root keys: {extra}"

    assert set(CATALOG["$defs"]) == {"anyComponent", "anyFunction"}

    for name, schema in COMPONENTS.items():
        assert identifier.match(name), f"{name} is not a valid identifier"
        assert name != "Surface", "Surface is reserved by the protocol"
        const = schema["allOf"][1]["properties"]["component"]["const"]
        assert const == name, f"{name} declares component const {const!r}"

    for name, schema in FUNCTIONS.items():
        assert identifier.match(name), f"{name} is not a valid identifier"
        assert not name.startswith("@"), "the @ namespace is reserved"
        assert schema["properties"]["call"]["const"] == name
        assert schema["returnType"]
        assert schema["callableFrom"] in {
            "rendererOnly", "agentOnly", "rendererOrAgent"
        }
