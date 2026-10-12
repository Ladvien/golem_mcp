"""The manifest must describe the code that actually exists."""

from blended.manifest import build_manifest


def test_manifest_lists_real_operations():
    manifest_text = build_manifest()
    # Signatures introspected from the live modules, not hand-written.
    assert "add_box(" in manifest_text
    assert "boolean_union(" in manifest_text
    assert "add_lathe(" in manifest_text
    assert "unwrap_uvs(" in manifest_text


def test_manifest_carries_gate_fields_and_budget():
    manifest_text = build_manifest()
    assert "self_intersecting_face_pair_count" in manifest_text
    assert "maximum_triangle_count" in manifest_text


def test_manifest_includes_drift_traps():
    manifest_text = build_manifest()
    assert "Known API traps" in manifest_text
    assert "use_auto_smooth" in manifest_text


def test_drift_catalog_can_be_omitted():
    assert "Known API traps" not in build_manifest(include_drift_catalog=False)


def test_manifest_demands_bare_python():
    assert "No markdown fences" in build_manifest()
