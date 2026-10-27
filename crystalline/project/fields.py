"""Declarative field-type expressions used in project config files.

A project file describes a type as a mapping of field name -> type
expression, e.g. `price: float` or `product_ids: list[str]`. This module
compiles those expressions into real Python/Pydantic types (and back, for
saving), so a config file never embeds anything beyond simple strings.

Supported expressions: `str`, `int`, `float`, `bool`, `datetime`, `date`,
`any`; `list[X]`; `dict[K, V]`; `X | None` / `Optional[X]`; and the name
of any type already registered earlier in the same project (for simple
references between types, e.g. an Order referencing a Customer).
"""

from __future__ import annotations

import datetime
import types
from typing import Any, Union, get_args, get_origin

from pydantic import BaseModel, Field, create_model

from crystalline.schema import CrystallineModel, SchemaRegistry

_PRIMITIVES: dict[str, Any] = {
    "str": str,
    "int": int,
    "float": float,
    "bool": bool,
    "datetime": datetime.datetime,
    "date": datetime.date,
    "any": Any,
}
_PRIMITIVE_NAMES: dict[Any, str] = {v: k for k, v in _PRIMITIVES.items() if v is not Any}


class FieldSpecError(ValueError):
    """Raised for an invalid or unresolvable field type expression."""


def resolve_type(type_expr: str, registry: SchemaRegistry) -> Any:
    """Compile a type expression string into a real Python/Pydantic type."""
    expr = type_expr.strip()

    if expr.endswith("| None"):
        return resolve_type(expr[: -len("| None")], registry) | None

    if expr.startswith("Optional[") and expr.endswith("]"):
        return resolve_type(expr[len("Optional[") : -1], registry) | None

    if expr.startswith("list[") and expr.endswith("]"):
        return list[resolve_type(expr[len("list[") : -1], registry)]

    if expr.startswith("dict[") and expr.endswith("]"):
        key_expr, _, value_expr = expr[len("dict[") : -1].partition(",")
        return dict[
            resolve_type(key_expr, registry), resolve_type(value_expr, registry)
        ]

    if expr in _PRIMITIVES:
        return _PRIMITIVES[expr]

    referenced = registry.get(expr)
    if referenced is not None:
        return referenced

    raise FieldSpecError(f"Unknown field type: {type_expr!r}")


def type_to_expr(py_type: Any, registry: SchemaRegistry) -> str:
    """Inverse of `resolve_type`: render a Python/Pydantic type back to
    the expression that would compile to it, for saving a project back
    out to a config file."""
    origin = get_origin(py_type)

    if origin is Union or origin is types.UnionType:
        args = get_args(py_type)
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) == 1 and type(None) in args:
            return f"{type_to_expr(non_none[0], registry)} | None"
        raise FieldSpecError(f"Unsupported union type: {py_type!r}")

    if origin is list:
        (item_type,) = get_args(py_type)
        return f"list[{type_to_expr(item_type, registry)}]"

    if origin is dict:
        key_type, value_type = get_args(py_type)
        return f"dict[{type_to_expr(key_type, registry)}, {type_to_expr(value_type, registry)}]"

    if py_type in _PRIMITIVE_NAMES:
        return _PRIMITIVE_NAMES[py_type]

    if isinstance(py_type, type) and issubclass(py_type, BaseModel):
        for name, model in registry.types.items():
            if model is py_type:
                return name
        raise FieldSpecError(
            f"Type {py_type!r} is not registered in the given registry"
        )

    raise FieldSpecError(f"Cannot express {py_type!r} as a field type expression")


def _parse_field_entry(entry: Any) -> tuple[str, bool, Any, str | None]:
    """Return (type_expr, required, default, description) for one field
    entry, which is either a bare type string (required field) or a
    mapping with `type` and optional `required`/`default`/`description`.
    """
    if isinstance(entry, str):
        return entry, True, ..., None

    type_expr = entry["type"]
    has_default = "default" in entry
    required = entry.get("required", not has_default)
    # An explicit `required: false` with no `default` implies `None` —
    # without this, `default` stays `...` (Pydantic's "no default"
    # sentinel) and the field would be required despite `required: false`.
    if has_default:
        default = entry.get("default")
    else:
        default = ... if required else None
    description = entry.get("description")
    return type_expr, required, default, description


def build_model_from_field_spec(
    name: str, field_spec: dict[str, Any], registry: SchemaRegistry
) -> type[CrystallineModel]:
    """Build (but do not register) a `CrystallineModel` subclass from a
    `{field_name: type_expr_or_entry}` mapping."""
    field_definitions: dict[str, Any] = {}
    for field_name, entry in field_spec.items():
        type_expr, required, default, description = _parse_field_entry(entry)
        py_type = resolve_type(type_expr, registry)
        default_value = ... if required else default
        field_definitions[field_name] = (
            py_type,
            Field(default=default_value, description=description),
        )
    return create_model(name, __base__=CrystallineModel, **field_definitions)


def field_spec_from_model(
    model: type[BaseModel], registry: SchemaRegistry
) -> dict[str, Any]:
    """Inverse of `build_model_from_field_spec`, for saving a project."""
    field_spec: dict[str, Any] = {}
    for field_name, info in model.model_fields.items():
        type_expr = type_to_expr(info.annotation, registry)
        if info.is_required():
            field_spec[field_name] = type_expr
            continue
        entry: dict[str, Any] = {"type": type_expr, "required": False}
        entry["default"] = info.default
        if info.description:
            entry["description"] = info.description
        field_spec[field_name] = entry
    return field_spec
