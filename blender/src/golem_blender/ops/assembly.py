"""An ASSEMBLY: many pieces, defined, measured, gated, rendered and shipped as ONE asset.

Measured need (issue #26, `Landmark_BlacksmithShop`, Sanctuary, 2026-10-24):
a 49-part building of 19,967 triangles and 18 materials could not be shipped
through `export_asset` at all. That op gates ONE mesh — one closed manifold
component under 2000 triangles — and its refusal was accurate and useless:

    triangle count 21328 exceeds budget 2000; 33052 boundary edges (open
    mesh); 6943 disconnected components (budget 1); 6486 self-intersecting
    face pairs ...

because that is what a building assembled from kit pieces IS: 49 closed solids
sharing faces where they meet. So the `.glb` was written by a headless script
outside golem, losing the verification the tool exists to provide, and after 20
turns the assembly existed only in the session's notes.

THE GATE HERE IS NOT `MeshBudget`, AND THE CHOICE IS STATED RATHER THAN IMPLIED:

- every PART is judged by the normal per-piece gate (`analyze_object` with a
  `MeshBudget`), unchanged — a part must still be one closed manifold prop, and
  `export_assembly` fails naming the part that is not;
- parts MAY lap. Part-vs-part interpenetration is REPORTED with the pair's
  names and its box overlap volume, never failed outright, because a kit corner
  leg laps its wall by one wall thickness by design (0.406 m in the session).
  `PartIntersection.kind` separates a LAP (a junction: the two parts' boxes end
  in the SAME plane across the penetration axis, so the pieces were cut to
  meet) from a CLASH (one part's interior pushed through another's face, such
  as a pipe through a bellows — no shared plane bounds it);
- the assembly's own verdict rides on `ExportReport`, not on a report op.
  `AssemblyReport.object_name` names the ASSEMBLY — a registry entry, not a
  scene object — so `gate_target_names` would hand that name to
  `gate_named_object`, which answers "no object named ... in bpy.data.objects"
  on every single call. `ops/_contract.py` forbids claiming a gate verdict for a
  report that names no real object, so `define_assembly` and `assembly_report`
  are NOT gated, and `export_assembly` carries the measurement of the parts it
  actually ships.

`define_assembly` is an ACTION: it moves the parts so the assembly's pivot
holds — footprint centred on X/Y, lowest point on z=0 — which is what makes
`lowest_point_m == 0` a fact instead of a hope. `assembly_report` reads and
changes nothing, so it needs no declared plan.

Every measurement here is SHARED, never re-derived: world bounds come from
`ops/transforms._world_bounds_m` (the one place world extents are measured,
OT-34), the pairwise verdict from `analyze.pair_checks.analyze_pair` (the one
pairwise measurement, whose face-pair count is already gated above
`CONTACT_DEPTH_TOLERANCE_M` so resting contact reads zero), the join arithmetic
from `ops/assets._append_part_into` (the code `join_objects` uses, so "several
meshes become one" means one thing), and the renders from
`capture.views.capture_views`, which already frames a set of objects together.
"""

from __future__ import annotations

from dataclasses import dataclass

from golem_blender.analyze.pair_checks import CONTACT_DEPTH_TOLERANCE_M
from golem_blender.export.gltf import ExportReport
from golem_blender.ops._contract import op

# A part whose base sits within this of the floor, or of another part's top,
# RESTS on it. The same tolerance as resting contact, on purpose: the two
# questions share one answer for "are these touching".
SUPPORT_TOLERANCE_M = CONTACT_DEPTH_TOLERANCE_M

# The pivot the issue asks for, and the only one that makes `lowest_point_m`
# zero: the footprint centred on X/Y with the lowest point on z = 0.
PIVOT_FOOTPRINT_CENTRE_BASE = "footprint_centre_base"
SUPPORTED_PIVOTS = (PIVOT_FOOTPRINT_CENTRE_BASE,)

# What a whole-assembly sheet renders by default: the view names
# `capture.views` knows that look at a building from a useful side. The issue's
# proposed "back"/"left"/"inside" are not directions this renderer has, and a
# view nobody renders is a view nobody inspects.
ASSEMBLY_VIEWS = ("front", "right", "three_quarter", "top")
# A FOCUS capture is a close-up of one junction, from three angles: a bracket
# off its wall, a board hung flat and a pipe through a bellows each read as
# wrong from a side, an end and a corner.
FOCUS_VIEWS = ("front", "right", "three_quarter")

WELDED_OBJECT_SUFFIX = "_welded"
REIMPORT_OBJECT_SUFFIX = "_reimport_check"
# Two bounding planes within this are the SAME plane: pieces cut to meet, not
# two edges a micron apart by accident.
SHARED_PLANE_TOLERANCE_M = 1.0e-6
# A box overlap thinner than a face is a shared plane, not shared volume; the
# AABB of a cylinder or a sphere is also larger than the solid it bounds, so the
# volume below is a size, never an integral.
LAP_KIND = "lap"
CLASH_KIND = "clash"


@dataclass(frozen=True)
class PartIntersection:
    """One pair of parts whose boxes share volume: how deep, how much, and which kind."""

    first_object_name: str
    second_object_name: str
    # LAP (a junction by design) or CLASH (an interior pushed through a face).
    kind: str
    # The world-AABB minimum translation depth, from `analyze_pair`.
    penetration_depth_m: float
    # The two parts' box overlap: an over-estimate for anything not a box.
    overlap_volume_m3: float
    # The triangle pairs that actually intersect. `analyze_pair` reports these
    # only above CONTACT_DEPTH_TOLERANCE_M, so resting contact reads zero.
    intersecting_face_pair_count: int


@dataclass(frozen=True)
class AssemblyReport:
    """What an assembly IS, measured now. Numbers, not opinions."""

    # The ASSEMBLY's name — a registry entry, not a scene object, which is why
    # no op returning this report claims a gate verdict.
    object_name: str
    objects: tuple[str, ...]
    triangles_total: int
    dimensions_m: tuple[float, float, float]
    lowest_point_m: float
    materials: tuple[str, ...]
    # Named parts with no MESH object in the scene right now: never linked, or
    # removed after the assembly was defined. Excluded from every total, and
    # listed so the exclusion is never silent.
    unlinked: tuple[str, ...]
    part_intersections: tuple[PartIntersection, ...]
    # Off the ground, and nothing beneath whose top meets its base.
    unsupported: tuple[str, ...]
    # The narrower case: unsupported AND sharing no volume with any other part.
    floating: tuple[str, ...]
    # The name pairs `part_intersections` calls a LAP.
    laps: tuple[tuple[str, str], ...]
    pivot: str = PIVOT_FOOTPRINT_CENTRE_BASE


# The session's assemblies: name -> part names. NAMES only, so a part removed
# after definition shows up in `unlinked` instead of quietly shrinking every
# total. Module-level because an assembly is a fact about the session, like an
# object's name — and two assemblies sharing pieces each read their own totals
# because each holds its own tuple.
_ASSEMBLIES: dict[str, tuple[str, ...]] = {}


def _mesh_part(object_name: str):
    """The named MESH object, or None when there is no such mesh to measure."""
    import bpy

    blender_object = bpy.data.objects.get(object_name)
    if blender_object is None or blender_object.type != "MESH":
        return None
    return blender_object


def _assembly_bounds(part_objects) -> tuple[list[float], list[float]]:
    """The parts' JOINT world box; one shared measurement for the whole report."""
    from golem_blender.ops.transforms import _world_bounds_m

    if not part_objects:
        return [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]
    return _world_bounds_m(part_objects)


def _overlap_on_axis(first_bounds, second_bounds, axis: int) -> float:
    (first_minimum, first_maximum), (second_minimum, second_maximum) = (
        first_bounds,
        second_bounds,
    )
    return min(first_maximum[axis], second_maximum[axis]) - max(
        first_minimum[axis], second_minimum[axis]
    )


def _shares_a_bounding_plane_on(first_bounds, second_bounds, axis: int) -> bool:
    """Do the two boxes END in the same plane across the penetration axis?

    That is the shape of kit joinery: a wall's end face and a return's end face
    lie in one plane, so on the penetration axis BOTH parts own the overlap's
    end. A clash is the other shape — the overlap's ends belong to different
    parts on that axis, which is exactly one solid's interior pushed through the
    other's face and stopped nowhere.
    """
    (first_minimum, first_maximum), (second_minimum, second_maximum) = (
        first_bounds,
        second_bounds,
    )
    overlap_minimum = max(first_minimum[axis], second_minimum[axis])
    overlap_maximum = min(first_maximum[axis], second_maximum[axis])
    shares_maximum = (
        abs(overlap_maximum - first_maximum[axis]) <= SHARED_PLANE_TOLERANCE_M
        and abs(overlap_maximum - second_maximum[axis]) <= SHARED_PLANE_TOLERANCE_M
    )
    shares_minimum = (
        abs(overlap_minimum - first_minimum[axis]) <= SHARED_PLANE_TOLERANCE_M
        and abs(overlap_minimum - second_minimum[axis]) <= SHARED_PLANE_TOLERANCE_M
    )
    return shares_maximum or shares_minimum


def _shared_volume(first_bounds, second_bounds):
    """(kind, depth_m, volume_m3) for a box overlap, or None when disjoint."""
    overlaps = [
        _overlap_on_axis(first_bounds, second_bounds, axis) for axis in range(3)
    ]
    if any(overlap <= 0.0 for overlap in overlaps):
        return None
    depth_axis = min(range(3), key=lambda axis: overlaps[axis])
    depth_m = overlaps[depth_axis]
    if depth_m <= CONTACT_DEPTH_TOLERANCE_M or _shares_a_bounding_plane_on(
        first_bounds, second_bounds, depth_axis
    ):
        kind = LAP_KIND
    else:
        kind = CLASH_KIND
    return kind, depth_m, overlaps[0] * overlaps[1] * overlaps[2]


def _supported_by(part_bounds, other_bounds) -> bool:
    """Does `other` hold `part` up?

    Two answers, both a measurement of the boxes: the other part's TOP meets the
    part's BASE (a lid on a crate, a floor under a leg), or the part's base lies
    inside the other's z-range with their footprints overlapping (a bracket
    embedded in a wall). Support is deliberately NOT transitive — one level is
    what tells a writer which part to move.
    """
    part_minimum, part_maximum = part_bounds
    other_minimum, other_maximum = other_bounds
    if not all(
        _overlap_on_axis(part_bounds, other_bounds, axis) > 0.0 for axis in range(2)
    ):
        return False
    if abs(other_maximum[2] - part_minimum[2]) <= SUPPORT_TOLERANCE_M:
        return True
    return (
        other_minimum[2] - SUPPORT_TOLERANCE_M
        <= part_minimum[2]
        <= other_maximum[2] + SUPPORT_TOLERANCE_M
        and part_maximum[2] > other_minimum[2]
    )


def _measure(name: str, object_names: tuple[str, ...]) -> AssemblyReport:
    """The assembly's numbers, measured now from the scene."""
    from golem_blender.analyze.pair_checks import analyze_pair
    from golem_blender.ops.transforms import _world_bounds_m

    part_objects = []
    unlinked: list[str] = []
    for object_name in object_names:
        blender_object = _mesh_part(object_name)
        if blender_object is None:
            unlinked.append(object_name)
        else:
            part_objects.append(blender_object)

    minimum, maximum = _assembly_bounds(part_objects)
    dimensions_m = tuple(float(maximum[axis] - minimum[axis]) for axis in range(3))
    lowest_point_m = float(minimum[2]) if part_objects else 0.0

    part_bounds = [_world_bounds_m([part_object]) for part_object in part_objects]

    triangles_total = 0
    material_names: set[str] = set()
    for part_object in part_objects:
        triangles_total += sum(
            len(polygon.vertices) - 2 for polygon in part_object.data.polygons
        )
        for material in part_object.data.materials:
            if material is not None:
                material_names.add(material.name)

    part_intersections: list[PartIntersection] = []
    touching: set[int] = set()
    for first_index in range(len(part_objects)):
        for second_index in range(first_index + 1, len(part_objects)):
            shared = _shared_volume(part_bounds[first_index], part_bounds[second_index])
            if shared is None:
                continue
            kind, _depth_m, volume_m3 = shared
            pair_report = analyze_pair(
                part_objects[first_index], part_objects[second_index]
            )
            part_intersections.append(
                PartIntersection(
                    first_object_name=part_objects[first_index].name,
                    second_object_name=part_objects[second_index].name,
                    kind=kind,
                    penetration_depth_m=float(pair_report.aabb_penetration_depth_m),
                    overlap_volume_m3=volume_m3,
                    intersecting_face_pair_count=(
                        pair_report.intersecting_face_pair_count
                    ),
                )
            )
            touching.update((first_index, second_index))

    unsupported: list[str] = []
    floating: list[str] = []
    for part_index, bounds in enumerate(part_bounds):
        if bounds[0][2] <= SUPPORT_TOLERANCE_M:
            continue  # standing on the ground
        if any(
            _supported_by(bounds, other_bounds)
            for other_index, other_bounds in enumerate(part_bounds)
            if other_index != part_index
        ):
            continue
        unsupported.append(part_objects[part_index].name)
        if part_index not in touching:
            floating.append(part_objects[part_index].name)

    return AssemblyReport(
        object_name=name,
        objects=object_names,
        triangles_total=triangles_total,
        dimensions_m=(dimensions_m[0], dimensions_m[1], dimensions_m[2]),
        lowest_point_m=lowest_point_m,
        materials=tuple(sorted(material_names)),
        unlinked=tuple(unlinked),
        part_intersections=tuple(part_intersections),
        unsupported=tuple(unsupported),
        floating=tuple(floating),
        laps=tuple(
            (intersection.first_object_name, intersection.second_object_name)
            for intersection in part_intersections
            if intersection.kind == LAP_KIND
        ),
    )


def _apply_pivot(part_objects, pivot: str) -> None:
    """Move every part so the assembly's pivot holds, in world space."""
    from mathutils import Matrix, Vector

    from golem_blender.ops.transforms import _refresh_dependency_graph, _world_bounds_m

    if pivot not in SUPPORTED_PIVOTS:
        raise ValueError(
            f"unknown pivot {pivot!r}; the supported pivots are "
            f"{list(SUPPORTED_PIVOTS)}"
        )
    if not part_objects:
        return
    minimum, maximum = _world_bounds_m(part_objects)
    # Translated in WORLD space rather than by writing `.location`, so a part
    # carrying a rotation or scale keeps it; the depsgraph is refreshed
    # afterwards so the very next read is truthful (the stale-`matrix_world`
    # trap ops/transforms.py's docstring exists for).
    shift = Matrix.Translation(
        Vector(
            (
                -((minimum[0] + maximum[0]) / 2.0),
                -((minimum[1] + maximum[1]) / 2.0),
                -minimum[2],
            )
        )
    )
    for part_object in part_objects:
        part_object.matrix_world = shift @ part_object.matrix_world
    _refresh_dependency_graph()


def _resolved_parts(name: str) -> tuple[tuple[str, ...], list]:
    """(the names, the live MESH objects) of a defined assembly."""
    object_names = _ASSEMBLIES.get(name)
    if object_names is None:
        raise KeyError(
            f"no assembly named {name!r}; define one with define_assembly "
            f"(defined: {sorted(_ASSEMBLIES)})"
        )
    part_objects = [
        part
        for part in (_mesh_part(object_name) for object_name in object_names)
        if part is not None
    ]
    return object_names, part_objects


@op()
def define_assembly(
    name: str,
    object_names: list[str],
    pivot: str = "footprint_centre_base",
) -> AssemblyReport:
    """Define the named objects as ONE assembly called `name`, moved so its pivot holds.

    The assembly is a registry entry, so `name` is NOT a scene object: nothing
    is joined, linked or renamed, and the parts keep their own names, meshes and
    materials. The parts are moved so the footprint is centred on X/Y and the
    lowest point sits on z=0. A name listed twice is refused loudly — counting
    one part twice would double its triangles and lie about the total — and a
    name with no mesh yet is kept in `objects` and reported in `unlinked`, so a
    later report says what went missing instead of shrinking silently.
    Re-running under the same name replaces the definition.
    """
    if not name.strip():
        raise ValueError("an assembly needs a non-empty name")
    if not object_names:
        raise ValueError(f"assembly {name!r} names no parts")
    if len(set(object_names)) != len(object_names):
        duplicated = sorted(
            {item for item in object_names if object_names.count(item) > 1}
        )
        raise ValueError(
            f"assembly {name!r} lists {duplicated} twice; every part is counted "
            f"once, so a repeat would double its triangles"
        )
    part_objects = [
        part
        for part in (_mesh_part(object_name) for object_name in object_names)
        if part
    ]
    _apply_pivot(part_objects, pivot)
    _ASSEMBLIES[name] = tuple(object_names)
    return _measure(name, _ASSEMBLIES[name])


@op(reads_only=True)
def assembly_report(name: str) -> AssemblyReport:
    """Re-measure the named assembly as it stands now; changes nothing at all.

    Every number is recomputed from the scene, so a part moved, removed or
    replaced since the definition shows up here: a removed part appears in
    `unlinked` and is excluded from every total. Reading is all this does — no
    transform, material or object is touched, so it needs no declared plan.
    """
    object_names, _part_objects = _resolved_parts(name)
    return _measure(name, object_names)


def _combined_object(part_objects, name: str):
    """The parts' geometry as ONE mesh object built in the scene, sources untouched.

    The join arithmetic is `ops/assets._append_part_into`, the code
    `join_objects` uses, so a welded export and a join cannot disagree about
    what baking a world matrix, reversing a mirrored face and re-indexing a
    material slot means. The parts STAY in the scene: an export must not eat
    the assembly it exports.
    """
    import bmesh
    import bpy

    from golem_blender.ops.assets import _append_part_into

    materials: list = []
    slot_of: dict[str | None, int] = {}

    def slot_of_material(material_key, material):
        if material_key not in slot_of:
            slot_of[material_key] = len(materials)
            materials.append(material)
        return slot_of[material_key]

    combined_mesh = bpy.data.meshes.new(name)
    working_mesh = bmesh.new()
    try:
        for part_object in part_objects:
            _append_part_into(
                working_mesh,
                part_object.data,
                part_object.matrix_world,
                slot_of_material,
            )
        working_mesh.to_mesh(combined_mesh)
    finally:
        working_mesh.free()
    for material in materials:
        combined_mesh.materials.append(material)
    combined = bpy.data.objects.new(name, combined_mesh)
    bpy.context.scene.collection.objects.link(combined)
    bpy.context.view_layer.update()
    return combined


def _reimport_measurements(glb_path, joined_name: str) -> dict:
    """Import the written .glb and measure EXACTLY what it delivers.

    The file's own nodes are what an engine walks, so the object count is read
    off a real import and not off the scene that produced it; the triangle
    counts are the joined import measured raw (glTF splits vertices along
    flat-shading seams) and again after welding. Both are removed afterwards.
    """
    import bpy

    from golem_blender.analyze.mesh_checks import analyze_object
    from golem_blender.ops.heal import weld_and_dissolve
    from golem_blender.ops.primitives import remove_object_and_mesh
    from golem_blender.ops.transforms import _world_bounds_m

    objects_before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(glb_path))
    imported_objects = [
        scene_object
        for scene_object in bpy.data.objects
        if scene_object not in objects_before
    ]
    imported_meshes = [
        imported_object
        for imported_object in imported_objects
        if imported_object.type == "MESH"
    ]
    try:
        if not imported_meshes:
            raise ValueError(f"{glb_path} re-imported with no mesh objects")
        minimum, maximum = _world_bounds_m(imported_meshes)
        joined = _combined_object(imported_meshes, joined_name)
        try:
            raw_report = analyze_object(joined)
            weld_and_dissolve(joined.name)
            welded_report = analyze_object(joined)
        finally:
            remove_object_and_mesh(joined.name)
        return {
            "object_count": len(imported_meshes),
            "dimensions_m": tuple(
                float(maximum[axis] - minimum[axis]) for axis in range(3)
            ),
            "raw": raw_report,
            "welded": welded_report,
        }
    finally:
        for imported_object in imported_objects:
            remove_object_and_mesh(imported_object.name)


def _material_names_in(glb_path) -> tuple[str, ...]:
    """The material names the written file carries, read from its own bytes."""
    from golem_blender.export.glb_report import parse_glb

    gltf, _binary = parse_glb(glb_path)
    names = [str(material.get("name", "")) for material in gltf.get("materials", [])]
    return tuple(sorted(name for name in names if name))


def _write_selection(selected_objects, path) -> int:
    """Write exactly the selected objects to `path`; return the byte count."""
    import bpy

    for scene_object in bpy.context.scene.objects:
        scene_object.select_set(scene_object in selected_objects)
    bpy.context.view_layer.objects.active = selected_objects[0]
    bpy.ops.export_scene.gltf(
        filepath=str(path),
        export_format="GLB",
        use_selection=True,
        export_apply=True,
    )
    return path.stat().st_size


def _part_gate_failures(part_objects, budget) -> tuple[tuple[str, str], ...]:
    """Every part's own piece-gate verdict: a part is still judged as a prop."""
    from golem_blender.analyze.mesh_checks import analyze_object

    failures: list[tuple[str, str]] = []
    for part_object in part_objects:
        part_failures = analyze_object(part_object, budget).failures(budget)
        if part_failures:
            failures.append((part_object.name, "; ".join(part_failures)))
    return tuple(failures)


@op()
def export_assembly(
    name: str,
    path: str,
    blend_path: str,
    keep_parts: bool = True,
) -> ExportReport:
    """Ship the named assembly as ONE .glb + .blend, gated per part and verified by re-import.

    `keep_parts=True` (the default) ships the parts as their own objects, which
    is what an assembly IS: 49 closed solids sharing faces. The gate is the
    per-piece one, applied to every part, and the export fails naming the part
    that is not closed; part-vs-part interpenetration is reported by
    `assembly_report` and never fails the export, because a kit corner laps by
    design. `keep_parts=False` welds them into one mesh and REPORTS what welding
    did — its component and boundary counts, measured, not assumed — because
    welding kit pieces does not close an assembly.

    The `.blend` holds exactly what shipped: the parts, or the welded mesh.
    `blend_path` is required, as for `export_asset`: an asset without its source
    cannot be edited and re-exported. A part removed since the definition fails
    the export instead of shipping a silently shorter assembly.
    """
    from pathlib import Path

    from golem_blender.analyze.mesh_checks import MeshBudget, analyze_object
    from golem_blender.export.blend import save_blend, validate_blend_request
    from golem_blender.export.glb_report import asset_report
    from golem_blender.ops.primitives import remove_object_and_mesh
    from golem_blender.ops.transforms import _world_bounds_m

    object_names, part_objects = _resolved_parts(name)
    unlinked = [
        object_name
        for object_name in object_names
        if object_name not in {part.name for part in part_objects}
    ]
    if unlinked:
        raise ValueError(
            f"assembly {name!r} names part(s) {unlinked} with no mesh object in "
            f"the scene; link or re-create them, or re-define the assembly"
        )

    welded_name = f"{name}{WELDED_OBJECT_SUFFIX}"
    shipped_names = (
        tuple(part.name for part in part_objects) if keep_parts else (welded_name,)
    )
    # Both arguments are checked BEFORE anything is written, so no .glb is ever
    # left without its source.
    _, blend_destination = validate_blend_request(shipped_names, blend_path)
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    budget = MeshBudget()
    part_failures = _part_gate_failures(part_objects, budget)
    minimum, maximum = _world_bounds_m(part_objects)
    pre_export_dimensions_m = tuple(
        float(maximum[axis] - minimum[axis]) for axis in range(3)
    )
    expected_material_names = tuple(
        sorted(
            {
                material.name
                for part_object in part_objects
                for material in part_object.data.materials
                if material is not None
            }
        )
    )

    combined = _combined_object(part_objects, welded_name)
    try:
        pre_export_report = analyze_object(combined)
        shipped_objects = part_objects if keep_parts else [combined]
        file_size_bytes = _write_selection(shipped_objects, output_path)
        file_report = asset_report(output_path)
        measurements = _reimport_measurements(
            output_path, f"{name}{REIMPORT_OBJECT_SUFFIX}"
        )
        blend_report = save_blend(shipped_names, blend_destination)
    finally:
        remove_object_and_mesh(welded_name)

    return ExportReport(
        export_path=output_path,
        file_size_bytes=file_size_bytes,
        pre_export=pre_export_report,
        reimported_raw=measurements["raw"],
        reimported_welded=measurements["welded"],
        pre_export_dimensions_m=pre_export_dimensions_m,
        reimported_dimensions_m=measurements["dimensions_m"],
        file_report=file_report,
        blend=blend_report,
        assembly_name=name,
        keep_parts=len(shipped_objects),
        part_count=len(part_objects),
        part_failures=part_failures,
        reimported_object_count=measurements["object_count"],
        material_names=_material_names_in(output_path),
        expected_material_names=expected_material_names,
        expected_root_node_names=shipped_names,
    )


def _safe_path_component(text: str) -> str:
    """A file-name-safe rendering of an object name: 'Wall North' -> 'Wall_North'."""
    safe = "".join(
        character if (character.isalnum() or character in "-_") else "_"
        for character in text
    )
    return safe or "unnamed"


def _focus_pairs(focus) -> list[tuple[str, str]]:
    """The `focus` argument as pairs of names, refusing anything else loudly."""
    names = list(focus)
    if len(names) % 2:
        raise ValueError(
            f"focus takes names in PAIRS — a junction is two objects — got "
            f"{len(names)}: {names}"
        )
    return [(names[index], names[index + 1]) for index in range(0, len(names), 2)]


@op()
def render_assembly(
    name: str,
    views: tuple[str, ...] = ASSEMBLY_VIEWS,
    focus: list[str] | None = None,
    output_dir: str | None = None,
) -> list[str]:
    """Render the whole assembly, then a tight close-up per named PAIR from three angles.

    Twelve of the blacksmith session's defects were found only by LOOKING — a
    bracket 111.9 cm off its wall, a board hung flat, a pipe through a bellows,
    two walls 11.10 cm apart — and each needed a close-up of TWO named objects
    at an angle that shows their junction. So `focus` takes names two at a time,
    every returned path names its own pair, and each close-up is FRAMED BY THE
    PAIR (orthographic scale and frame aspect both fitted to it), so the
    junction dominates the image instead of sitting in a building-sized frame.

    A focus capture hides the assembly's other parts for the length of that
    render — a wall in front of the junction is exactly what hid these defects —
    and restores them afterwards. The whole-assembly sheet frames every part
    together.
    """
    from pathlib import Path

    import bpy

    from golem_blender.capture.views import CaptureSettings, capture_views

    _object_names, part_objects = _resolved_parts(name)
    if not part_objects:
        raise ValueError(
            f"assembly {name!r} has no mesh part in the scene, so there is "
            f"nothing to render"
        )

    root_directory = (
        Path(output_dir)
        if output_dir is not None
        else Path(bpy.app.tempdir) / f"assembly_{_safe_path_component(name)}"
    )

    written: list[str] = []
    captured = capture_views(
        part_objects[0],
        root_directory,
        CaptureSettings(),
        extra_objects=tuple(part_objects[1:]),
        view_names=tuple(views),
    )
    written.extend(str(captured[view_name]) for view_name in captured)

    known_names = {part.name for part in part_objects}
    for first_name, second_name in _focus_pairs(focus or ()):
        unknown = [
            part for part in (first_name, second_name) if part not in known_names
        ]
        if unknown:
            raise ValueError(
                f"focus names {unknown}, which are not parts of assembly "
                f"{name!r} (parts: {sorted(known_names)})"
            )
        pair_directory = root_directory / (
            f"focus_{_safe_path_component(first_name)}_"
            f"{_safe_path_component(second_name)}"
        )
        hidden_parts = [
            part for part in part_objects if part.name not in (first_name, second_name)
        ]
        previous_hidden = [bool(part.hide_render) for part in hidden_parts]
        try:
            for part in hidden_parts:
                part.hide_render = True
            captured_pair = capture_views(
                bpy.data.objects[first_name],
                pair_directory,
                CaptureSettings(fit_projection=True),
                extra_objects=(bpy.data.objects[second_name],),
                view_names=FOCUS_VIEWS,
            )
        finally:
            for part, previous in zip(hidden_parts, previous_hidden):
                part.hide_render = previous
        written.extend(str(captured_pair[view_name]) for view_name in captured_pair)

    return written
