"""Issue #23's report shape and reader marker, on a machine with no Blender.

The measurement itself is proven in `tests/blender/test_measure_set_ops.py`
(the issue's six acceptance criteria, against a real scene). This file pins
what a regression would otherwise show only where Blender runs: the report's
fields, the unit suffixes on the quantities the schema generator reads, the
reader marker that keeps the op off the plan requirement, and that the op
issues no gate verdict.
"""

import dataclasses
import inspect

import pytest

from golem_blender.ops import SetReport, measure_objects
from golem_blender.ops._contract import (
    changes_scene,
    contract_violations,
    is_gated,
    is_reads_only,
)
from golem_blender.ops.measure_set import AXIS_COUNT


def test_the_report_carries_every_field_the_issue_asked_for():
    """The issue's proposed JSON, including the two fields that make an
    absent answer readable: `unlinked` and whether the pairs were checked."""
    field_names = [field.name for field in dataclasses.fields(SetReport)]
    assert field_names == [
        "object_name",
        "objects",
        "triangles_total",
        "triangles_by_object",
        "dimensions_m",
        "lowest_point_m",
        "unlinked",
        "material_slots",
        "part_intersections",
        "part_intersections_checked",
    ]


def test_the_report_is_frozen():
    """A measurement does not change under the reader: a caller that could
    edit it would hold numbers nothing measured."""
    report = SetReport(
        object_name="Part",
        objects=("Part",),
        triangles_total=12,
        triangles_by_object={"Part": 12},
        dimensions_m=(0.0, 0.0, 0.0),
        lowest_point_m=0.0,
        unlinked=(),
        material_slots=0,
        part_intersections=(),
    )
    assert report.part_intersections_checked is False
    with pytest.raises(dataclasses.FrozenInstanceError):
        report.triangles_total = 0


def test_the_pair_measurement_is_off_by_default():
    """The pairwise measurement is the expensive one, so the DEFAULT is what
    keeps a routine LOD check cheap — and it is in the generated schema."""
    parameters = inspect.signature(measure_objects).parameters
    assert parameters["check_part_intersections"].default is False


def test_the_op_is_a_reader_and_claims_no_gate_verdict():
    """A reader needs no declared plan (OT-6). It must also not claim a gate
    verdict: the gate measures ONE scene object against a mesh budget, and a
    set of parts is not that object."""
    assert is_reads_only(measure_objects)
    assert not changes_scene(measure_objects)
    assert not is_gated(measure_objects)


def test_the_report_survives_the_signature_contract():
    assert contract_violations(measure_objects) == []


def test_the_dimensions_are_three_axes():
    """`dimensions_m` is one length per world axis, so `AXIS_COUNT` is what a
    reader can rely on without knowing Blender."""
    assert AXIS_COUNT == 3
