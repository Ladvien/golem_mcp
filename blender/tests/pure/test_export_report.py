"""Pure layer: round-trip verdict logic on fabricated reports."""

from pathlib import Path

from blended.analyze.mesh_checks import MeshBudget, MeshReport
from blended.export.gltf import ExportReport


def _clean_report(triangle_count=100):
    return MeshReport(
        object_name="Thing",
        triangle_count=triangle_count,
        non_manifold_edge_count=0,
        boundary_edge_count=0,
        zero_area_face_count=0,
        non_finite_coordinate_count=0,
        connected_component_count=1,
        duplicate_vertex_pair_count=0,
        self_intersecting_face_pair_count=0,
        flipped_normal_triangle_count=0,
    )


def _shattered_report(triangle_count=100):
    """What a raw glTF re-import actually looks like: split vertices."""
    return MeshReport(
        object_name="Thing",
        triangle_count=triangle_count,
        non_manifold_edge_count=0,
        boundary_edge_count=376,
        zero_area_face_count=0,
        non_finite_coordinate_count=0,
        connected_component_count=46,
        duplicate_vertex_pair_count=248,
        self_intersecting_face_pair_count=0,
        flipped_normal_triangle_count=0,
    )


def _export_report(
    pre, post, pre_dims=(1.0, 1.0, 1.0), post_dims=(1.0, 1.0, 1.0), raw=None
):
    return ExportReport(
        export_path=Path("/tmp/thing.glb"),
        file_size_bytes=1234,
        pre_export=pre,
        reimported_raw=raw if raw is not None else _shattered_report(),
        reimported_welded=post,
        pre_export_dimensions_m=pre_dims,
        reimported_dimensions_m=post_dims,
    )


def test_clean_round_trip_passes():
    assert _export_report(_clean_report(), _clean_report()).passes()


def test_triangle_drift_is_flagged():
    report = _export_report(_clean_report(100), _clean_report(96))
    assert any("triangle count drifted" in f for f in report.round_trip_failures())


def test_dimension_drift_is_flagged_as_axis_error():
    swapped_dims = (1.0, 0.5, 2.0)  # the classic y/z swap signature
    report = _export_report(
        _clean_report(),
        _clean_report(),
        pre_dims=(1.0, 2.0, 0.5),
        post_dims=swapped_dims,
    )
    failures = report.round_trip_failures()
    assert any("axis-convention" in f for f in failures)


def test_pre_export_gate_failure_is_reported_first():
    dirty = MeshReport(
        object_name="Dirty",
        triangle_count=100,
        non_manifold_edge_count=3,
        boundary_edge_count=0,
        zero_area_face_count=0,
        non_finite_coordinate_count=0,
        connected_component_count=1,
        duplicate_vertex_pair_count=0,
        self_intersecting_face_pair_count=0,
        flipped_normal_triangle_count=0,
    )
    report = _export_report(dirty, _clean_report())
    assert any("BEFORE export" in f for f in report.round_trip_failures(MeshBudget()))


def test_shattered_raw_reimport_is_fine_when_welded_is_clean():
    """The glTF vertex-split lesson: raw re-import topology is
    informational; only the welded report judges the file."""
    report = _export_report(_clean_report(), _clean_report(), raw=_shattered_report())
    assert report.passes()
