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

from golem_blender.ops._objects import object_by_name

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


def _asset_report(
    blender_object,
    source_glb: str,
    scale: float,
    triangle_count_before: int | None = None,
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
    working_mesh = bmesh.new()
    try:
        for mesh_object in imported_meshes:
            part_slot_to_joined_slot: list[int] = []
            for part_material in mesh_object.data.materials:
                material_key = part_material.name if part_material else None
                if material_key not in joined_slot_of:
                    joined_slot_of[material_key] = len(joined_materials)
                    joined_materials.append(part_material)
                part_slot_to_joined_slot.append(joined_slot_of[material_key])

            part_working_mesh = bmesh.new()
            part_mesh = bpy.data.meshes.new(f"{object_name}__part")
            try:
                part_working_mesh.from_mesh(mesh_object.data)
                world_matrix = mesh_object.matrix_world.copy()
                for vertex in part_working_mesh.verts:
                    vertex.co = world_matrix @ vertex.co
                if world_matrix.determinant() < 0:
                    # A mirroring matrix turns every face inside out.
                    bmesh.ops.reverse_faces(
                        part_working_mesh, faces=list(part_working_mesh.faces)
                    )
                if part_slot_to_joined_slot:
                    last_slot = len(part_slot_to_joined_slot) - 1
                    for face in part_working_mesh.faces:
                        face.material_index = part_slot_to_joined_slot[
                            min(face.material_index, last_slot)
                        ]
                part_working_mesh.to_mesh(part_mesh)
            finally:
                part_working_mesh.free()
            working_mesh.from_mesh(part_mesh)
            bpy.data.meshes.remove(part_mesh)

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
    big_prefix = paths.CODEX_ROOT_ON_BIG.rstrip("/") + "/"
    local_glb_path = (
        str(paths.CODEX_ROOT_MAC / glb_path[len(big_prefix) :])
        if glb_path.startswith(big_prefix)
        else glb_path
    )

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
) -> AssetReport:
    """Copy the named object (own mesh data, materials shared) to new_name at location_m, turned z_rad about Z.

    Location and rotation are SET on the copy, not inherited. The copy has
    its own mesh data, so a boolean on one copy cannot change the others.
    Raises NameTaken when new_name exists.
    """
    import bpy

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
    for collection in source_object.users_collection:
        collection.objects.link(copied_object)
    copied_object.location = location_m
    copied_object.rotation_mode = "XYZ"
    copied_object.rotation_euler = (0.0, 0.0, z_rad)
    _refresh_dependency_graph()
    return _asset_report(copied_object, source_glb="", scale=1.0)
