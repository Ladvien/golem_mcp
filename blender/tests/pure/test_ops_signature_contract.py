"""OPS-21 (OT-2): every facade op satisfies a machine-checkable contract.

The schema generator (OT-3) can only emit what the signature carries, so
the signature has to carry everything: annotated parameters, a return
annotation, unit suffixes on quantities, a one-line description, and no
bpy type anywhere — object references are NAMES. The manifest already
renders these signatures into the prompt; a violation here is a
violation the model reads.

Pure: introspection only, no Blender. A seeded-defect op (NFR-15)
proves each rule can fail.
"""

from __future__ import annotations

import inspect
import typing

import pytest

from blended.ops._contract import (
    UNITLESS_NUMERIC_NAMES,
    contract_violations,
    facade_ops,
    is_gated,
    op,
    returns_object_names,
)
from blended.ops._objects import ObjectName

# --- the fixture that proves the gate can fail (NFR-15) ------------------


def _seeded_defect_op(blender_object, width: float, count: int = 2):
    """First line.
    Second line on the same string is not a one-line summary."""
    return blender_object


# --- tests ---------------------------------------------------------------


@pytest.mark.parametrize(
    "op_name,function", facade_ops(), ids=lambda x: x if isinstance(x, str) else ""
)
def test_facade_op_satisfies_the_signature_contract(op_name, function):
    violations = contract_violations(function)
    assert not violations, f"{op_name}: " + "; ".join(violations)


def test_the_contract_trips_on_a_seeded_defect():
    """NFR-15: the gate can fail. Every rule fires on the fixture op."""
    violations = contract_violations(_seeded_defect_op)
    joined = "\n".join(violations)
    assert "blender_object" in joined and "names a bpy object" in joined
    assert "no annotation" in joined
    assert "carries no unit suffix" in joined  # count is allowed; width is not
    assert "no return annotation" in joined
    assert "not a single line" in joined


def test_unitless_allowlist_is_all_in_use():
    """An allowlist entry no op uses is a loophole waiting for a caller."""
    used = {
        parameter
        for _, function in facade_ops()
        for parameter in inspect.signature(function).parameters
    }
    unused = sorted(UNITLESS_NUMERIC_NAMES - used)
    assert not unused, f"UNITLESS_NUMERIC_NAMES entries no op uses: {unused}"


def test_typing_is_not_needed_at_import():
    """Facade ops resolve under `from __future__ import annotations`; the
    generator (OT-3) reads strings, so a forward ref must be a plain name."""
    for op_name, function in facade_ops():
        hints = typing.get_type_hints(function)
        assert hints, f"{op_name}: no resolvable type hints"


# --- gating markers (OT-5) ----------------------------------------------------


def test_returns_object_names_reads_the_annotation_not_the_runtime_type():
    def names_one(name: str) -> ObjectName:
        """Returns the object."""
        return ObjectName(name)

    def names_many(name_prefix: str, count: int) -> list[ObjectName]:
        """Returns the objects."""
        return []

    def names_none(object_name: str) -> str:
        """Returns a material name."""
        return "Wood"

    assert returns_object_names(names_one) and returns_object_names(names_many)
    assert not returns_object_names(names_none)
    assert is_gated(names_one) and not is_gated(op(gated=False)(names_one))


def test_the_ungated_marker_on_a_text_returning_op_is_a_violation():
    @op(gated=False)
    def marked_but_returns_text(name: str) -> str:
        """Returns text, so there is nothing to exempt from the gate."""
        return name

    assert any(
        "nothing to exempt" in v for v in contract_violations(marked_but_returns_text)
    )


def test_an_ungated_constructor_must_take_the_name_it_returns():
    @op(gated=False)
    def anonymous(width_m: float) -> ObjectName:
        """Creates something it will not let the caller name."""
        return ObjectName("x")

    assert any("takes no `name` parameter" in v for v in contract_violations(anonymous))


def test_a_reader_that_returns_an_object_name_is_a_violation():
    @op(reads_only=True)
    def reader_that_writes(object_name: str) -> ObjectName:
        """Claims to read, returns what it modified."""
        return ObjectName(object_name)

    assert any(
        "a reader creates or modifies nothing" in v
        for v in contract_violations(reader_that_writes)
    )
