"""
handler_args.py — argument coercion shared by the domain handler modules

Tool arguments arrive unvalidated: the SDK does not check them against the
declared inputSchema, so a non-numeric value reaches the handler and makes a
bare int()/float() raise, which surfaces as an opaque -32603. These helpers
convert the same values the handlers already accepted, and turn a failed
conversion into an INVALID_PARAMS error naming the parameter.
"""

import mcp.types as types
from mcp.shared.exceptions import MCPError


def to_int(value, key: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as err:
        raise MCPError(
            types.INVALID_PARAMS, f"'{key}' must be an integer, got: {value!r}"
        ) from err


def to_float(value, key: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as err:
        raise MCPError(
            types.INVALID_PARAMS, f"'{key}' must be a number, got: {value!r}"
        ) from err
