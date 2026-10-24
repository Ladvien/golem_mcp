"""Bring finished meshes into the scene: pack pieces, generated assets, copies.

A kit built from third-party packs or from generated meshes (TRELLIS) needs
three things the primitive vocabulary lacks: read a .glb in as ONE mesh
object, scale a generated mesh to a stated size, and copy a piece so the next
use of it is a transform rather than a second import.

Every op here returns an AssetReport, never an ObjectName. An op that returns
an object name is measured by the single-mesh acceptance gate
(agent/op_call.py:call_op), which fails every pack piece or generated mesh
that has more than one component or an open boundary. The report carries
those counts as numbers instead; the kitbash procedure reads them.

Pack pieces keep their authored pivot. Generated assets are normalized to the
repo convention (base at z=0, centred on X/Y) because their pivot is
arbitrary.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from golem_blender.ops._objects import ObjectName, object_by_name

MINIMUM_Z_EXTENT_M = 1.0e-6


@dataclass(frozen=True)
class AssetReport:
    """What an import or duplicate left in the scene. Numbers, not opinions."""

    object_name: str
    source_glb: str  # "" for duplicate_object
    triangle_count_before: int  # as imported, before decimation
    triangle_count: int
    extents_m: tuple[float, float, float]
    bounds_min_m: tuple[float, float, float]
    bounds_max_m: tuple[float, float, float]
    scale: float  # uniform factor applied (1.0 when none)
    material_names: tuple[str, ...]
    connected_component_count: int
    boundary_edge_count: int
    # True only for a copy that kept its parent AND was given a non-zero
    # location: `location_m` is then parent-relative and the measured
    # bounds are the only world reading (issue #19).
    location_is_parent_relative: bool = False


def _asset_report(
    blender_object,
    source_glb: str,
    scale: float,
    triangle_count_before: int | None = None,
    location_is_parent_relative: bool = False,
) -> AssetReport:
    """Measure the object as it now stands; `triangle_count_before` defaults to the measured count."""
    from golem_blender.analyze.mesh_checks import analyze_object
    from golem_blender.ops.transforms import _world_bounds_m

    minimum, maximum = _world_bounds_m([blender_object])
    mesh_report = analyze_object(blender_object)
    return AssetReport(
        object_name=blender_object.name,
        source_glb=source_glb,
        triangle_count_before=(
            mesh_report.triangle_count
            if triangle_count_before is None
            else triangle_count_before
        ),
        triangle_count=mesh_report.triangle_count,
        extents_m=(
            maximum[0] - minimum[0],
            maximum[1] - minimum[1],
            maximum[2] - minimum[2],
        ),
        bounds_min_m=(minimum[0], minimum[1], minimum[2]),
        bounds_max_m=(maximum[0], maximum[1], maximum[2]),
        scale=scale,
        material_names=tuple(
            material.name for material in blender_object.data.materials if material
        ),
        connected_component_count=mesh_report.connected_component_count,
        boundary_edge_count=mesh_report.boundary_edge_count,
        location_is_parent_relative=location_is_parent_relative,
    )


@dataclass(frozen=True)
class JoinReport:
    """What a join left in the scene: one mesh, measured, and what it ate."""

    object_name: str
    triangles: int
    parts_joined: int
    material_slots: int
    # Every source, in the order given. They no longer exist.
    consumed_names: tuple[str, ...]
    # Measured on the result, so "two overlapping solids intersect and two
    # touching ones do not" is a number rather than a claim.
    connected_component_count: int
    boundary_edge_count: int
    self_intersecting_face_pair_count: int


def _append_part_into(
    working_mesh, part_mesh, part_world_matrix, slot_of_material
) -> None:
    """Append `part_mesh` into `working_mesh`, baked by `part_world_matrix`.

    The arithmetic every "several meshes become one" path needs: bake the
    world matrix into the vertices (matrix_world evaluates lazily, so a part
    that was only MOVED reads stale until the dependency graph refreshes),
    reverse the faces under a mirroring matrix (a negative determinant turns
    every face inside out), and translate the part's material indices into
    the target's slots. `_import_joined` and `join_objects` share it so the
    two cannot disagree about what a join means geometrically.

    `bmesh.from_mesh` APPENDS, which is what makes the accumulation work:
    the caller calls this once per part and `to_mesh` once at the end.
    """
    import bmesh
    import bpy

    part_slot_to_target_slot = [
        slot_of_material(part_material.name if part_material else None, part_material)
        for part_material in part_mesh.materials
    ]

    part_working_mesh = bmesh.new()
    part_temporary_mesh = bpy.data.meshes.new("__join_part")
    try:
        part_working_mesh.from_mesh(part_mesh)
        for vertex in part_working_mesh.verts:
            vertex.co = part_world_matrix @ vertex.co
        if part_world_matrix.determinant() < 0:
            bmesh.ops.reverse_faces(
                part_working_mesh, faces=list(part_working_mesh.faces)
            )
        if part_slot_to_target_slot:
            last_slot = len(part_slot_to_target_slot) - 1
            for face in part_working_mesh.faces:
                face.material_index = part_slot_to_target_slot[
                    min(face.material_index, last_slot)
                ]
        part_working_mesh.to_mesh(part_temporary_mesh)
    finally:
        part_working_mesh.free()
    try:
        working_mesh.from_mesh(part_temporary_mesh)
    finally:
        bpy.data.meshes.remove(part_temporary_mesh)


def join_objects(
    object_names: list[str],
    result_name: str,
    keep_material_slots: bool = True,
) -> ObjectName:
    """Join the named mesh objects into one mesh named result_name and consume the sources.

    The result carries the first object's origin and every part's WORLD
    transform, so a part that was only moved keeps its place. Material slots
    are deduplicated by material, so sixteen tufts of one material are ONE
    slot; keep_material_slots=False keeps the first material only, for a
    consumer that wants a single draw call. At least two distinct names are
    required and each is resolved as a MESH first, so a call that cannot
    succeed consumes nothing.
    """
    import bmesh
    import bpy

    from golem_blender.ops.primitives import NameTaken, remove_object_and_mesh
    from golem_blender.ops.transforms import _refresh_dependency_graph

    # Everything that can fail is checked BEFORE anything mutates: a join
    # that raised halfway would have already eaten its sources.
    if len(object_names) < 2:
        raise ValueError(
            f"join_objects needs at least two objects, got {len(object_names)}: "
            f"joining one object is a rename, not a join (use rename_object)"
        )
    if len(set(object_names)) != len(object_names):
        raise ValueError(
            f"join_objects got a name twice in {object_names}: joining an object "
            f"with itself would double its geometry and then delete it"
        )
    if not result_name.strip():
        raise ValueError("result_name must be non-empty")
    if result_name in bpy.data.objects:
        raise NameTaken(
            f"an object named {result_name!r} already exists "
            f"(remove_object_and_mesh it first, or pick another name)"
        )
    sources = [object_by_name(name, "MESH") for name in object_names]
    _refresh_dependency_graph()

    result_object_matrix = sources[0].matrix_world.copy()
    inverse_result_matrix = result_object_matrix.inverted()

    joined_materials: list = []  # slot order of the joined mesh; None is an empty slot
    joined_slot_of: dict[str | None, int] = {}

    def slot_of_material(material_key, material):
        if not keep_material_slots and joined_materials:
            return 0  # one slot: the first material seen wins
        if material_key not in joined_slot_of:
            joined_slot_of[material_key] = len(joined_materials)
            joined_materials.append(material)
        return joined_slot_of[material_key]

    target_mesh = bpy.data.meshes.new(result_name)
    working_mesh = bmesh.new()
    try:
        for source in sources:
            # Each part is baked in WORLD space and expressed in the FIRST
            # part's space, so the result's origin is that part's origin and
            # the piece's base check still means something.
            _append_part_into(
                working_mesh,
                source.data,
                source.matrix_world @ inverse_result_matrix,
                slot_of_material,
            )
        working_mesh.to_mesh(target_mesh)
    finally:
        working_mesh.free()
    for joined_material in joined_materials:
        target_mesh.materials.append(joined_material)

    joined_object = bpy.data.objects.new(result_name, target_mesh)
    bpy.context.scene.collection.objects.link(joined_object)
    joined_object.matrix_world = result_object_matrix

    for source_name in object_names:
        remove_object_and_mesh(source_name)
    _refresh_dependency_graph()

    from golem_blender.analyze.mesh_checks import analyze_object

    measured = analyze_object(joined_object)
    return JoinReport(
        object_name=joined_object.name,
        triangles=measured.triangle_count,
        parts_joined=len(object_names),
        material_slots=len(joined_materials),
        consumed_names=tuple(object_names),
        connected_component_count=measured.connected_component_count,
        boundary_edge_count=measured.boundary_edge_count,
        self_intersecting_face_pair_count=measured.self_intersecting_face_pair_count,
    )


def _import_joined(glb_path: str, object_name: str):
    """Import a .glb as one linked mesh object, materials kept, no recentring.

    Every imported mesh part is joined with its world matrix baked in; each
    part's material slots are remapped onto the joined mesh's slots, which
    ingest/import_glb.py does not do (it drops materials).
    """
    import bmesh
    import bpy
    from mathutils import Matrix

    from golem_blender.ops.primitives import NameTaken
    from golem_blender.ops.transforms import _refresh_dependency_graph

    path = Path(glb_path)
    if not path.is_file():
        raise FileNotFoundError(f"No GLB at {path}")
    if not object_name.strip():
        raise ValueError("object_name must be non-empty")
    if object_name in bpy.data.objects:
        raise NameTaken(
            f"an object named {object_name!r} already exists "
            f"(remove_object_and_mesh it first, or pick another name)"
        )

    objects_before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(path))
    imported_objects = [
        scene_object
        for scene_object in bpy.data.objects
        if scene_object not in objects_before
    ]
    imported_meshes = [
        scene_object for scene_object in imported_objects if scene_object.type == "MESH"
    ]
    if not imported_meshes:
        _remove_imported(imported_objects)
        raise ValueError(f"{path} contained no mesh objects.")
    # matrix_world is evaluated lazily; read stale it is identity (see transforms.py).
    _refresh_dependency_graph()

    joined_materials: list = []  # slot order of the joined mesh; None is an empty slot
    joined_slot_of: dict[str | None, int] = {}

    def slot_of_material(material_key, material):
        if material_key not in joined_slot_of:
            joined_slot_of[material_key] = len(joined_materials)
            joined_materials.append(material)
        return joined_slot_of[material_key]

    working_mesh = bmesh.new()
    try:
        for mesh_object in imported_meshes:
            _append_part_into(
                working_mesh,
                mesh_object.data,
                mesh_object.matrix_world,
                slot_of_material,
            )
        joined_mesh = bpy.data.meshes.new(object_name)
        working_mesh.to_mesh(joined_mesh)
    finally:
        working_mesh.free()
    for joined_material in joined_materials:
        joined_mesh.materials.append(joined_material)

    _remove_imported(imported_objects)

    joined_object = bpy.data.objects.new(object_name, joined_mesh)
    bpy.context.scene.collection.objects.link(joined_object)
    joined_object.matrix_world = Matrix.Identity(4)
    return joined_object


def _remove_imported(imported_objects) -> None:
    """Remove the importer's objects and the data only they used (meshes, armatures)."""
    import bpy

    for imported_object in imported_objects:
        object_data = imported_object.data
        bpy.data.objects.remove(imported_object)
        if object_data is not None and object_data.users == 0:
            if isinstance(object_data, bpy.types.Mesh):
                bpy.data.meshes.remove(object_data)
            elif isinstance(object_data, bpy.types.Armature):
                bpy.data.armatures.remove(object_data)


def _triangle_count(mesh) -> int:
    mesh.calc_loop_triangles()
    return len(mesh.loop_triangles)


def _normalise_to_height(blender_object, height_m: float) -> float:
    """Recentre on X/Y, put the base at z=0, scale uniformly to height_m; bake it into the mesh.

    The object's matrix is identity here, so mesh-local and world agree.
    Returns the uniform scale applied.
    """
    from mathutils import Matrix, Vector

    from golem_blender.ops.transforms import _world_bounds_m

    minimum, maximum = _world_bounds_m([blender_object])
    z_extent_m = maximum[2] - minimum[2]
    if z_extent_m < MINIMUM_Z_EXTENT_M:
        raise ValueError(
            f"{blender_object.name!r} has a z extent of {z_extent_m} m; "
            f"it cannot be scaled to a height"
        )
    scale = height_m / z_extent_m
    center_x_m = (minimum[0] + maximum[0]) / 2
    center_y_m = (minimum[1] + maximum[1]) / 2
    blender_object.data.transform(
        Matrix.Scale(scale, 4)
        @ Matrix.Translation(Vector((-center_x_m, -center_y_m, -minimum[2])))
    )
    return scale


def import_glb_piece(glb_path: str, object_name: str) -> AssetReport:
    """Import a .glb as ONE mesh object named object_name, keeping its materials and authored pivot.

    For pieces of a third-party pack: the object is NOT recentred, scaled,
    welded or cleaned, so its bounds match the pack's. glTF stores vertices
    per face, so the report's component and boundary counts are as imported
    and a closed piece usually reads as many components until it is welded.
    Raises NameTaken when object_name exists and FileNotFoundError when the
    file is missing.
    """
    joined_object = _import_joined(glb_path, object_name)
    return _asset_report(joined_object, source_glb=str(glb_path), scale=1.0)


def import_generated_asset(
    glb_path: str, object_name: str, height_m: float, triangle_count: int = 2000
) -> AssetReport:
    """Import a generated .glb, scale it uniformly to height_m, base at z=0, centred on X/Y, decimated to triangle_count.

    A glb_path under big's codex root (/mnt/codex_fs/...) is read through the
    Mac mount, so generate_3d's published_to + "/asset.glb" can be passed
    verbatim. Holes are never filled. Decimation shrinks the silhouette a
    little, so the size is applied again after it: the report's extents are
    the final ones.
    """
    import bpy

    from golem_blender.ingest.cleanup import CleanupSettings, cleanup_mesh
    from golem_blender.kitbash import paths
    from golem_blender.ops.primitives import remove_object_and_mesh

    if not height_m > 0 or not math.isfinite(height_m):
        raise ValueError(f"height_m must be a positive number, got {height_m}")
    # A glb_path under big's codex root (/mnt/codex_fs/...) is read
    # through the Mac mount, so generate_3d's published_to + "/asset.glb"
    # can be passed verbatim. A path that is NOT under that root is
    # already a path this machine can open — and one that is neither
    # under the root nor an existing file is REFUSED rather than
    # assumed: a path on big's own filesystem, read as a Mac path,
    # either fails with a confusing "not found" or, worse, finds an
    # unrelated file at the same absolute path.
    try:
        local_glb_path = str(paths.mac_path(glb_path))
    except ValueError:
        candidate = Path(glb_path)
        if not candidate.is_file():
            raise ValueError(
                f"{glb_path} is not under the codex root "
                f"({paths.CODEX_ROOT_ON_BIG}) and is not a file this machine "
                f"can open. Pass the big path of a file on the codex mount, "
                f"or a local path."
            ) from None
        local_glb_path = glb_path

    generated_object = _import_joined(local_glb_path, object_name)
    try:
        triangle_count_before = _triangle_count(generated_object.data)
        scale = _normalise_to_height(generated_object, height_m)
        cleanup_report = cleanup_mesh(
            generated_object,
            CleanupSettings(
                triangle_budget=triangle_count, maximum_hole_perimeter_m=0.0
            ),
        )
        if cleanup_report.after.triangle_count != cleanup_report.before.triangle_count:
            scale *= _normalise_to_height(generated_object, height_m)
    except Exception:
        if object_name in bpy.data.objects:
            remove_object_and_mesh(object_name)
        raise
    return _asset_report(
        generated_object,
        source_glb=local_glb_path,
        scale=scale,
        triangle_count_before=triangle_count_before,
    )


def duplicate_object(
    object_name: str,
    new_name: str,
    location_m: tuple[float, float, float] = (0.0, 0.0, 0.0),
    z_rad: float = 0.0,
    keep_parent: bool = False,
) -> AssetReport:
    """Copy the named object (own mesh data) to new_name at world location_m, turned z_rad about Z; parent dropped.

    The copy's `location` is the WORLD location: the source's parent, its
    type and bone, and matrix_parent_inverse are cleared first, because
    `Object.copy()` carries them and would leave `location_m`
    parent-relative (issue #19). keep_parent=True keeps today's
    behaviour exactly — the copy stays parent-relative and the report
    says so. The copy has its own mesh data, so a boolean on one copy
    cannot change the others. Raises NameTaken when new_name exists.
    """
    import bpy
    from mathutils import Matrix

    from golem_blender.ops.primitives import NameTaken
    from golem_blender.ops.transforms import _refresh_dependency_graph

    source_object = object_by_name(object_name, "MESH")
    if not new_name.strip():
        raise ValueError("new_name must be non-empty")
    if new_name in bpy.data.objects:
        raise NameTaken(
            f"an object named {new_name!r} already exists "
            f"(remove_object_and_mesh it first, or pick another name)"
        )

    copied_object = source_object.copy()
    copied_object.data = source_object.data.copy()
    copied_object.name = new_name
    copied_object.data.name = new_name
    if not keep_parent:
        # `Object.copy()` carries the parent, its type and bone, and the
        # matrix_parent_inverse. Left in place, `location` stays
        # PARENT-RELATIVE and the copy lands somewhere other than
        # location_m (measured: a child of an empty at z=3 given
        # location z=3 landed at world z=6). Clearing the parent alone is
        # not enough — a bone parent survives it as parent_type='BONE'.
        # Same trap `move_object_to` handles for a parented object.
        copied_object.parent = None
        copied_object.parent_type = "OBJECT"
        copied_object.parent_bone = ""
        copied_object.matrix_parent_inverse = Matrix.Identity(4)
    for collection in source_object.users_collection:
        collection.objects.link(copied_object)
    copied_object.location = location_m
    copied_object.rotation_mode = "XYZ"
    copied_object.rotation_euler = (0.0, 0.0, z_rad)
    _refresh_dependency_graph()
    return _asset_report(
        copied_object,
        source_glb="",
        scale=1.0,
        # Only meaningful while the copy keeps a parent: with the parent
        # dropped, location_m IS the world location.
        location_is_parent_relative=keep_parent and location_m != (0.0, 0.0, 0.0),
    )
