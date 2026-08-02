"""Schema capture and normalization for before/after parity checks."""

import json
from pathlib import Path

from mcp.client.client import Client

BASELINE = Path(__file__).parent / "schema_baseline.json"


def normalize_schema(schema: dict) -> dict:
    """Strip the cosmetic differences between hand-written and generated schemas."""
    if not isinstance(schema, dict):
        return schema

    out = {}
    for key, value in schema.items():
        if key == "title":
            continue
        if key == "prefixItems":
            normalized_items = [normalize_schema(item) for item in value]
            if normalized_items and any(
                item != normalized_items[0] for item in normalized_items[1:]
            ):
                raise ValueError("heterogeneous tuple schemas are not supported")
            out["items"] = normalized_items[0] if normalized_items else {}
            out["minItems"] = len(value)
            out["maxItems"] = len(value)
            continue
        if key == "anyOf" and len(value) == 2 and {"type": "null"} in value:
            inner = next(v for v in value if v != {"type": "null"})
            out.update(normalize_schema(inner))
            continue
        if isinstance(value, dict):
            out[key] = normalize_schema(value)
        elif isinstance(value, list):
            out[key] = [normalize_schema(v) for v in value]
        else:
            out[key] = value
    return out


async def capture_tools(app) -> dict:
    """Return {name: {description, input_schema}} for every tool the server exposes."""
    async with Client(app) as client:
        result = await client.list_tools()
    return {
        t.name: {
            "description": t.description,
            "input_schema": normalize_schema(t.input_schema),
        }
        for t in result.tools
    }


def load_baseline() -> dict:
    return json.loads(BASELINE.read_text(encoding="utf-8"))
