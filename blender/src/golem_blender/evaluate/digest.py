"""A semantic digest of built geometry: same build, same hash.

Two builds of the same parameters must produce the same asset. Proving
that needs a comparison that is neither too tight nor too loose, and
both failure modes were measured in scp:

* `.blend` BYTES carry a Blender version stamp and a file-write
  timestamp, so a byte hash reports drift on a build that did not
  change.
* RAW FLOATS carry last-bit noise from the order the arithmetic
  happened in, so a float hash cries wolf for the same reason.

So this hashes QUANTIZED SEMANTIC TUPLES: the numbers a consumer of the
asset can perceive, rounded onto a grid an order of magnitude finer
than any gate tolerance in this repository. The comparison itself is
then exact string equality — a digest with a numeric tolerance is not a
digest, it is a second, undocumented gate.

Components are hashed SEPARATELY so a mismatch names the drifted
datablock. "The build is not reproducible" starts an investigation;
"mesh:Barrel drifted, transform:Barrel did not" ends one.

MAIN THREAD ONLY: everything below touches bpy.
"""

from __future__ import annotations

import hashlib
import json

# 0.1 mm: finer than any gate tolerance in this repo
# (GROUNDING_TOLERANCE_M is 2 mm), coarse enough to swallow the
# last-bit noise two evaluation orders produce for the same vertex.
POSITION_GRID_M = 1.0e-4

# UVs and matrix entries are unitless and normalized-ish, so they get a
# finer grid than metres do; a 1e-5 UV step is well below one texel of
# a 16k map.
UV_GRID = 1.0e-5
MATRIX_GRID = 1.0e-5

# Skin weights are stored by glTF as normalized bytes (1/255 ~ 4e-3),
# so a grid finer than 1e-4 would hash noise the export cannot carry.
WEIGHT_GRID = 1.0e-4


def quantize(value: float, grid: float) -> int:
    """Round `value` onto `grid`, half-to-even, as an integer.

    Half-to-even (Python's own `round`) rather than half-up because
    half-up biases every tie in one direction, which turns a symmetric
    mesh into an asymmetric digest. `+0.0` and `-0.0` both map to `0`:
    a sign on zero is not a difference a consumer can perceive, and
    mirroring operations produce it constantly.
    """
    quantized = round(float(value) / grid)
    return 0 if quantized == 0 else int(quantized)


def _hash_component(payload) -> str:
    """sha256 of one component's canonical JSON."""
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _canonical_face(vertex_indices: tuple[int, ...]) -> tuple[int, ...]:
    """Rotate a face's index cycle to start at its lowest index, KEEPING
    ORDER.

    Loop rotation and face storage order are nondeterministic — bmesh
    operators emit geometry in pointer-hash order — and neither affects
    the shipped `.glb`. Winding direction DOES affect it: a flipped
    face lights inside-out. So the rotation is canonicalized and the
    direction is not. Do not "fix" this by sorting each face's
    indices: that would make an inverted facet hash identical to a
    correct one, and the digest would stop being able to see the defect
    it exists to catch.
    """
    if not vertex_indices:
        return ()
    lowest_position = vertex_indices.index(min(vertex_indices))
    return vertex_indices[lowest_position:] + vertex_indices[:lowest_position]


def _mesh_component(mesh) -> dict:
    positions = [
        [
            quantize(vertex.co[0], POSITION_GRID_M),
            quantize(vertex.co[1], POSITION_GRID_M),
            quantize(vertex.co[2], POSITION_GRID_M),
        ]
        for vertex in mesh.vertices
    ]
    edges = sorted(tuple(sorted(edge.vertices)) for edge in mesh.edges)
    faces = sorted(
        _canonical_face(tuple(polygon.vertices)) for polygon in mesh.polygons
    )
    return {
        "positions": positions,
        "edges": [list(edge) for edge in edges],
        "faces": [list(face) for face in faces],
    }


def _uv_component(mesh) -> dict:
    """Every UV layer, by name, with its per-loop coordinates.

    Layer NAMES are part of the digest because a renamed layer breaks
    material bindings while every coordinate stays identical.
    """
    layers = {}
    for uv_layer in mesh.uv_layers:
        layers[uv_layer.name] = [
            [quantize(datum.uv[0], UV_GRID), quantize(datum.uv[1], UV_GRID)]
            for datum in uv_layer.data
        ]
    return layers


def _transform_component(matrix) -> list:
    return [quantize(value, MATRIX_GRID) for row in matrix for value in row]


def _material_component(mesh) -> list:
    """Material names in SLOT ORDER. An empty slot is an empty string:
    applying a boolean appends one, and that is a difference."""
    return [material.name if material else "" for material in mesh.materials]


def _weights_component(blender_object, mesh) -> list | None:
    """Per-vertex `(group_name, quantized_weight)`, sorted by name.

    None when the object has no vertex groups, so an unrigged build
    carries no weights component at all rather than a list of empties.
    Sorted by NAME because group indices renumber when a group is
    removed, and the name is what the armature binds to.
    """
    if not blender_object.vertex_groups:
        return None
    group_names = {group.index: group.name for group in blender_object.vertex_groups}
    per_vertex: list = []
    for vertex in mesh.vertices:
        entries = [
            [
                group_names.get(element.group, f"<index {element.group}>"),
                quantize(element.weight, WEIGHT_GRID),
            ]
            for element in vertex.groups
        ]
        per_vertex.append(sorted(entries))
    return per_vertex


def _components(blender_object, dependency_graph) -> dict:
    """The component digests of one mesh object.

    The EVALUATED mesh, so modifiers are part of the digest: a build
    whose Solidify silently stopped applying is a different asset, and
    the unevaluated mesh cannot see that.
    """
    if blender_object.type != "MESH":
        raise ValueError(
            f"{blender_object.name!r} is a {blender_object.type}, not a MESH: "
            f"the digest hashes geometry a consumer receives"
        )
    evaluated = blender_object.evaluated_get(dependency_graph)
    mesh = evaluated.to_mesh()
    try:
        name = blender_object.name
        components = {
            f"mesh:{name}": _hash_component(_mesh_component(mesh)),
            f"uv:{name}": _hash_component(_uv_component(mesh)),
            f"transform:{name}": _hash_component(
                _transform_component(evaluated.matrix_world)
            ),
            f"material:{name}": _hash_component(_material_component(mesh)),
        }
        weights = _weights_component(blender_object, mesh)
        if weights is not None:
            components[f"weights:{name}"] = _hash_component(weights)
        return components
    finally:
        evaluated.to_mesh_clear()


def _digest(components: dict) -> dict:
    return {"overall": _hash_component(components), "components": components}


def object_digest(blender_object) -> dict:
    """`{"overall": sha256hex, "components": {"mesh:<name>": hex, ...}}`."""
    import bpy

    bpy.context.view_layer.update()
    dependency_graph = bpy.context.evaluated_depsgraph_get()
    return _digest(_components(blender_object, dependency_graph))


def scene_digest() -> dict:
    """Every mesh object in the current scene, by name order.

    Name order, not scene order: `scene.objects` iteration order is not
    a contract, and a digest whose value depends on link order would
    report drift for a build that linked the same objects in a
    different sequence.
    """
    import bpy

    bpy.context.view_layer.update()
    dependency_graph = bpy.context.evaluated_depsgraph_get()
    components: dict = {}
    mesh_objects = sorted(
        (obj for obj in bpy.context.scene.objects if obj.type == "MESH"),
        key=lambda obj: obj.name,
    )
    for blender_object in mesh_objects:
        components.update(_components(blender_object, dependency_graph))
    return _digest(components)


def compare_digests(first: dict, second: dict) -> list[str]:
    """Per-component differences (empty list = identical builds).

    Returns problems rather than raising, the same shape as
    `validate_catalog` and `validate_modules`, so a caller can print
    every drifted component in one report.
    """
    problems: list[str] = []
    first_components = first["components"]
    second_components = second["components"]
    for missing in sorted(set(first_components) - set(second_components)):
        problems.append(f"{missing}: present in the first build, absent in the second")
    for added in sorted(set(second_components) - set(first_components)):
        problems.append(f"{added}: absent in the first build, present in the second")
    for shared in sorted(set(first_components) & set(second_components)):
        if first_components[shared] != second_components[shared]:
            problems.append(
                f"{shared}: {first_components[shared][:12]} != "
                f"{second_components[shared][:12]}"
            )
    if not problems and first["overall"] != second["overall"]:
        problems.append(
            f"components match but overall differs: {first['overall'][:12]} != "
            f"{second['overall'][:12]}"
        )
    return problems
