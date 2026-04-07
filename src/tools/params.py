"""Parameter cast and validation for tool calls."""

from __future__ import annotations

import json


def cast_params(params: dict, schema: dict) -> dict:
    """Safe type coercion based on JSON Schema type declarations.

    Converts common LLM type mistakes (e.g. "123" for integer).
    Non-convertible values are returned unchanged for validate to catch.
    """
    properties = schema.get("properties", {})
    result = {}
    for key, value in params.items():
        prop_schema = properties.get(key)
        if prop_schema is None:
            result[key] = value
            continue
        expected = prop_schema.get("type")
        result[key] = _cast_value(value, expected) if expected else value
    return result


def _cast_value(value: object, expected_type: str) -> object:
    if expected_type == "integer":
        if isinstance(value, str):
            try:
                return int(value)
            except ValueError:
                try:
                    f = float(value)
                    if f == int(f):
                        return int(f)
                except ValueError:
                    pass
        elif isinstance(value, float) and value == int(value):
            return int(value)

    elif expected_type == "number":
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                pass

    elif expected_type == "boolean":
        if isinstance(value, str):
            low = value.lower()
            if low == "true":
                return True
            if low == "false":
                return False

    elif expected_type == "string":
        if not isinstance(value, str):
            return str(value)

    elif expected_type == "array" and isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return parsed
        except (json.JSONDecodeError, ValueError):
            pass

    return value


def validate_params(params: dict, schema: dict) -> list[str]:
    """Validate params against JSON Schema. Returns list of error strings (empty = valid)."""
    errors: list[str] = []
    properties = schema.get("properties", {})
    required = set(schema.get("required", []))

    # Check required fields
    for field_name in required:
        if field_name not in params:
            errors.append(f"Missing required field: '{field_name}'")

    # Check types
    for key, value in params.items():
        prop_schema = properties.get(key)
        if prop_schema is None:
            continue
        expected = prop_schema.get("type")
        if expected and not _type_matches(value, expected):
            errors.append(
                f"Field '{key}': expected {expected}, got {type(value).__name__} ({value!r})"
            )

    return errors


_TYPE_MAP: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
    "array": (list,),
    "object": (dict,),
}


def _type_matches(value: object, expected: str) -> bool:
    types = _TYPE_MAP.get(expected)
    if types is None:
        return True  # Unknown type, skip check
    # Python bool is subclass of int; "integer" should not accept True/False
    if expected == "integer" and isinstance(value, bool):
        return False
    return isinstance(value, types)
