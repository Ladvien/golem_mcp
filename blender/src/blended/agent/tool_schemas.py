"""Tool schemas GENERATED from the ops facade (OT-3).

PRM-2 forbids hand-written manifest prose because prose drifts from the
code it describes. A hand-written tool schema drifts the same way, so
the op tools the agent can call are introspected from the facade
signatures the OPS-21 contract guarantees: every parameter annotated,
quantities unit-suffixed, object references as names. Adding an op to
the facade adds a tool; changing a signature changes the tool; nothing
is written twice.

One tool per op, not a single `call_op(name, arguments)`: a per-op tool
carries its typed argument schema into the transport's constrained
decoding (the Claude Code lane builds a `oneOf` variant per tool,
`claude_code.envelope_schema`). That decision is a HYPOTHESIS to be
measured in OT-13, not a result: Tam et al. measured that adding a
schema constraint raised prompt sensitivity and lowered average
performance on reasoning tasks while helping classification, where the
restriction narrows the answer space (DOI
10.18653/v1/2024.emnlp-industry.91). Whether a modeling op call is more
"classification" than "reasoning" is exactly what the paired roll asks.

Pure: introspection and JSON only, no Blender. `bpy` never appears in a
generated schema because OPS-21 keeps it out of the signatures.
"""

from __future__ import annotations

import dataclasses
import hashlib
import inspect
import json
import pathlib
import types
import typing

from blended.agent.plan import PLAN_STEP_ARGUMENT, PLAN_STEP_SCHEMA
from blended.ops._contract import (
    assert_satisfies_contract,
    changes_scene,
    facade_ops,
    is_gated,
    returns_object_names,
)

# The fingerprint of the tool set the model can call. Prefixed `t` so it
# can never be mistaken in a log for the working-agreement identity
# (`v`) or the assembled-prompt fingerprint (`a`); same digest width as
# the assembled fingerprint so the two read alike beside each other.
TOOL_SCHEMAS_FINGERPRINT_PREFIX = "t"

# Python scalars the JSON-schema vocabulary names directly.
JSON_TYPE_FOR_SCALAR: dict[type, str] = {
    str: "string",
    float: "number",
    int: "integer",
    bool: "boolean",
}


# What the model reads about gating (OT-5), verbatim in every op tool
# description whose return names an object.
GATED_DESCRIPTION = (
    "Gated: the returned object is located and measured against the "
    "analyzer and scene-state gate; the verdict comes back with the result."
)
UNGATED_DESCRIPTION = (
    "UNGATED: returns an unlinked intermediate. link_into_scene it, "
    "consume it in a boolean, or remove it before you answer — the turn "
    "cannot end while it is unresolved."
)


class UnsupportedAnnotation(TypeError):
    """A facade signature carries a type the generator cannot express.

    Deliberately loud: a parameter silently rendered as `{}` would let
    the model pass anything and learn nothing, which is the failure a
    generated schema exists to prevent.
    """


def json_schema_for_type(hint) -> dict:
    """JSON schema for one resolved typing object, recursively."""
    if hint is type(None):
        return {"type": "null"}
    supertype = getattr(hint, "__supertype__", None)  # a NewType, e.g. ObjectName
    if supertype is not None:
        return json_schema_for_type(supertype)
    if hint in JSON_TYPE_FOR_SCALAR:
        return {"type": JSON_TYPE_FOR_SCALAR[hint]}
    if hint is pathlib.Path:
        return {"type": "string", "description": "Filesystem path."}
    origin = typing.get_origin(hint)
    arguments = typing.get_args(hint)
    if origin is typing.Literal:
        # A closed set of strings (a selector's `kind`): an enum.
        if not arguments or not all(isinstance(member, str) for member in arguments):
            raise UnsupportedAnnotation(
                f"Literal {hint!r}: only string literals map to an enum"
            )
        return {"type": "string", "enum": list(arguments)}
    if origin in (types.UnionType, typing.Union):
        return {"anyOf": [json_schema_for_type(member) for member in arguments]}
    if origin is tuple:
        if len(arguments) == 2 and arguments[1] is Ellipsis:
            return {"type": "array", "items": json_schema_for_type(arguments[0])}
        if not arguments or len(set(arguments)) != 1:
            raise UnsupportedAnnotation(
                f"tuple {hint!r}: only homogeneous fixed-arity tuples map to a "
                f"JSON array with minItems == maxItems"
            )
        return {
            "type": "array",
            "items": json_schema_for_type(arguments[0]),
            "minItems": len(arguments),
            "maxItems": len(arguments),
        }
    if origin is list:
        if len(arguments) != 1:
            raise UnsupportedAnnotation(f"list {hint!r} names no element type")
        return {"type": "array", "items": json_schema_for_type(arguments[0])}
    if dataclasses.is_dataclass(hint) and isinstance(hint, type):
        return _json_schema_for_dataclass(hint)
    raise UnsupportedAnnotation(
        f"no JSON schema for {hint!r}: extend json_schema_for_type or change "
        f"the signature (OPS-21)"
    )


def _json_schema_for_dataclass(config_class: type) -> dict:
    """A config dataclass (`SplayedLegSpec`, `BoneSpec`) as an object schema."""
    hints = typing.get_type_hints(config_class)
    properties: dict[str, dict] = {}
    required: list[str] = []
    for config_field in dataclasses.fields(config_class):
        property_schema = json_schema_for_type(hints[config_field.name])
        if config_field.default is not dataclasses.MISSING:
            property_schema["default"] = _json_value(config_field.default)
        elif config_field.default_factory is not dataclasses.MISSING:
            property_schema["default"] = _json_value(config_field.default_factory())
        else:
            required.append(config_field.name)
        properties[config_field.name] = property_schema
    return {
        "type": "object",
        "description": _summary(config_class),
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def _json_value(value):
    """A default value as JSON, loudly: a default the schema cannot carry
    would be a parameter the model cannot see."""
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        # A config default (`VertexSelector(kind="all")`): its fields.
        return _json_value(dataclasses.asdict(value))
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    raise UnsupportedAnnotation(f"default {value!r} is not JSON")


def _summary(documented) -> str:
    docstring = inspect.getdoc(documented) or ""
    return docstring.split("\n", 1)[0].strip()


def op_tool_schema(op_name: str, function) -> dict:
    """One tool entry, in the shape the transports already consume."""
    assert_satisfies_contract(op_name, function)
    signature = inspect.signature(function)
    hints = typing.get_type_hints(function)
    properties: dict[str, dict] = {}
    required: list[str] = []
    for parameter in signature.parameters.values():
        property_schema = json_schema_for_type(hints[parameter.name])
        if parameter.default is inspect.Parameter.empty:
            required.append(parameter.name)
        else:
            property_schema["default"] = _json_value(parameter.default)
        properties[parameter.name] = property_schema
    return_text = signature.return_annotation
    if not isinstance(return_text, str):
        return_text = getattr(return_text, "__name__", str(return_text))
    if changes_scene(function):
        # A scene-changing op is an ACTION tool: it requires a declared
        # plan and carries the step it belongs to (AGT-5, AGT-7, OT-6).
        # Stripped again before binding; the op never sees it.
        properties[PLAN_STEP_ARGUMENT] = dict(PLAN_STEP_SCHEMA)
    description = f"{_summary(function)} Returns {return_text}."
    if returns_object_names(function):
        description += " " + (
            GATED_DESCRIPTION if is_gated(function) else UNGATED_DESCRIPTION
        )
    return {
        "type": "function",
        "function": {
            "name": op_name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
        },
    }


def build_tool_schemas() -> list[dict]:
    """One generated tool per facade op, in facade order."""
    return [op_tool_schema(op_name, function) for op_name, function in facade_ops()]


def tool_schemas_fingerprint(schemas: list[dict]) -> str:
    """Content hash of a tool set: `t:{hex12}`, sha256 of its canonical JSON."""
    from blended.agent.system_prompt import ASSEMBLED_FINGERPRINT_DIGEST_CHARACTERS

    canonical = json.dumps(schemas, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return (
        f"{TOOL_SCHEMAS_FINGERPRINT_PREFIX}:"
        f"{digest[:ASSEMBLED_FINGERPRINT_DIGEST_CHARACTERS]}"
    )
