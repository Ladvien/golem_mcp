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
from dataclasses import dataclass

import pytest

from golem_blender.ops._contract import (
    UNITLESS_NUMERIC_NAMES,
    contract_violations,
    facade_ops,
    is_gated,
    op,
    returns_object_names,
)
from golem_blender.ops._objects import ObjectName

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


def test_a_plural_name_parameter_takes_a_list_of_names():
    """`object_names` is several names, so a list of str is legal there.

    Measured need: join_objects(object_names: list[str], ...) — issue #21.
    The element rule is unchanged: a list of scene types is refused exactly
    as a bare scene type is, so the plural form widens the container, not
    the type.
    """

    class Mesh:  # a forbidden type token, standing in for bpy.types.Mesh
        pass

    def plural_ok(object_names: list[str], result_name: str) -> str:
        """Joins them."""
        return result_name

    def plural_bpy(object_names: list[Mesh], result_name: str) -> str:
        """Joins bpy objects."""
        return result_name

    assert not contract_violations(plural_ok)
    violations = contract_violations(plural_bpy)
    assert any("looks like a name" in v for v in violations), violations
    assert any("a bpy type" in v for v in violations), violations


@dataclass(frozen=True)
class _NamedReport:
    """A report that names the object it left in the scene."""

    object_name: str
    triangles: int


@dataclass(frozen=True)
class _AnonymousReport:
    """A report with nowhere for the gate to look."""

    triangles: int


def test_a_gated_op_may_return_a_report_whose_object_the_gate_measures():
    """Issue #21 needs a gate verdict AND the report's counts, so a gated op
    can return a report. Measured need: `join_objects` was annotated
    `-> ObjectName`, returned `JoinReport`, and the dispatcher iterated the
    dataclass and raised `TypeError: 'JoinReport' object is not iterable`
    on a LIVE call. The contract now refuses that shape at the source: a
    marked-gated op whose return carries no `object_name` is a violation.
    """
    from golem_blender.ops._contract import gate_target_names

    # Module-level report types: `from __future__ import annotations` makes
    # these hints strings, and `get_type_hints` cannot resolve a local class.
    @op(gated=True)
    def reports_named(object_names: list[str]) -> _NamedReport:
        """Joins them, and the gate measures object_name."""
        return _NamedReport(object_names[0], 24)

    @op(gated=True)
    def reports_anonymous(object_names: list[str]) -> _AnonymousReport:
        """Joins them, and the gate has nowhere to look."""
        return _AnonymousReport(24)

    assert is_gated(reports_named)
    assert not contract_violations(reports_named)
    # The gate target IS the report's own field, so the dispatcher never
    # iterates the dataclass.
    assert gate_target_names(reports_named(["Joined"])) == ("Joined",)
    assert gate_target_names("Joined") == ("Joined",)
    assert gate_target_names(("A", "B")) == ("A", "B")
    assert gate_target_names(_AnonymousReport(24)) == ()

    violations = contract_violations(reports_anonymous)
    assert any("carries no 'object_name'" in v for v in violations), violations
