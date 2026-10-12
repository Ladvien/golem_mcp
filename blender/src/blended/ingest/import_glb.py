"""GLB ingestion: the entry point of the neural/generated lane.

A generated GLB arrives as an arbitrary object tree (mesh parts,
empties, sometimes armatures) with arbitrary transforms. Ingestion
flattens that into ONE mesh object under OUR conventions: world
transforms baked in, base at z=0, centered on X/Y, deterministic name,
identity matrix. Materials are not preserved at this stage — the
geometry lane runs first; texture handling is its own stage.

Everything downstream (analyzer, cleanup, capture) then treats a
generated mesh exactly like a built one. One set of gates, two lanes.
"""

from __future__ import annotations

from pathlib import Path


def import_glb(glb_path: Path, object_name: str):
    """Import a .glb/.gltf, join its meshes into one normalized object."""
    import bmesh
    import bpy
    from mathutils import Matrix, Vector

    from blended.ops.primitives import remove_object_and_mesh

    glb_path = Path(glb_path)
    if not glb_path.exists():
        raise FileNotFoundError(f"No GLB at {glb_path}")

    objects_before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(glb_path))
    imported_objects = [
        scene_object
        for scene_object in bpy.data.objects
        if scene_object not in objects_before
    ]
    imported_meshes = [
        scene_object for scene_object in imported_objects if scene_object.type == "MESH"
    ]
    if not imported_meshes:
        raise ValueError(f"{glb_path} contained no mesh objects.")

    # Join every mesh part with its world transform baked in.
    remove_object_and_mesh(object_name)
    joined_mesh = bpy.data.meshes.new(object_name)
    working_mesh = bmesh.new()
    try:
        for mesh_object in imported_meshes:
            part_mesh = mesh_object.data.copy()
            part_mesh.transform(mesh_object.matrix_world)
            working_mesh.from_mesh(part_mesh)
            bpy.data.meshes.remove(part_mesh)
        working_mesh.to_mesh(joined_mesh)
    finally:
        working_mesh.free()

    joined_object = bpy.data.objects.new(object_name, joined_mesh)
    bpy.context.scene.collection.objects.link(joined_object)

    # Remove the imported originals (meshes, empties, armatures alike).
    for imported_object in imported_objects:
        object_data = imported_object.data
        bpy.data.objects.remove(imported_object)
        if object_data is not None and object_data.users == 0:
            if isinstance(object_data, bpy.types.Mesh):
                bpy.data.meshes.remove(object_data)
            elif isinstance(object_data, bpy.types.Armature):
                bpy.data.armatures.remove(object_data)

    # Normalize into repo conventions: identity matrix, base at z=0,
    # centered on X/Y (the bounding-box centre, not the vertex mean, which
    # a mesh that is denser on one side drags off-centre) — baked into the
    # mesh, not hidden in the matrix.
    joined_object.matrix_world = Matrix.Identity(4)
    vertex_coordinates = [vertex.co for vertex in joined_mesh.vertices]
    minimum_z_m = min(coordinate.z for coordinate in vertex_coordinates)
    center_x_m = (
        min(c.x for c in vertex_coordinates) + max(c.x for c in vertex_coordinates)
    ) / 2
    center_y_m = (
        min(c.y for c in vertex_coordinates) + max(c.y for c in vertex_coordinates)
    ) / 2
    joined_mesh.transform(
        Matrix.Translation(Vector((-center_x_m, -center_y_m, -minimum_z_m)))
    )
    return joined_object
