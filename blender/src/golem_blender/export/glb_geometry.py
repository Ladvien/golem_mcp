"""A shipped .glb measured the way the ENGINE sees it: per node, pivot, tops, profile.

`export/glb_report.py` reads the same file for its mesh INTEGRITY — inverted
facets, boundary edges, weight sums. It deliberately works in mesh-local space,
which is right for integrity and wrong for everything a level designer asks: a
part's height, whether it stands on its base, what its pivot is off by, and
which of its faces a character could stand on all depend on where the NODE puts
the mesh. This module applies those transforms, so its numbers match what the
game loads rather than what the exporter wrote.

Two conventions are named explicitly and never assumed:

- **The frame.** glTF is +Y up, -Z forward. Blender is +Z up, +Y forward. The
  engine frame is left as the file has it; the Blender frame maps
  `(x, y, z) -> (x, -z, y)`, the same mapping `export_yup` inverts and
  `analyze/view_geometry` uses for camera directions. A caller that reads a
  height in the wrong frame gets a plausible number for the wrong axis, so the
  call states which frame it answered in and the report echoes it.

- **The units.** The file is metres (glTF's own unit). Sanctuary's own kit scale
  is 3.2808 feet per metre (`src/prototype/palette.rs`), and that factor is what
  `units="ft"` multiplies by — the ENGINE's factor, not a rounded 3.28084, so a
  height compared against the engine matches the engine.

Pure: json, math and struct only. No bpy, no numpy.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from golem_blender.export.glb_report import parse_glb, read_accessor

# Sanctuary's own feet-per-metre (src/prototype/palette.rs KIT_SCALE): the
# engine's factor, so a height reported in feet compares against the engine's.
FEET_PER_METRE = 3.2808
# Two upward faces within this height that share a welded vertex are ONE top: a
# table's top is four boxes and a dozen triangles at the same height, and a
# height reported twelve times is not a top.
TOP_HEIGHT_TOLERANCE_M = 0.005
# The 2-D bin used to find which triangles cover a profile point.
PROFILE_BIN_M = 0.25
# A profile longer than this is a mistake in the call, not a measurement: at the
# default 0.1 m step it is 200 m of section.
MAXIMUM_PROFILE_SAMPLES = 2000
# Welding precision for "these two corners are the same place after the node's
# transform", which is what makes a component count and a top group mean
# something rather than counting every export split.
POSITION_WELD_DECIMALS = 6

FRAME_AXIS_MAPPING = {
    "engine": "glTF/Bevy: +X right, +Y up, -Z forward (= Blender +Y)",
    "blender": "Blender: +X right, +Z up, +Y forward (= glTF -Z)",
}


@dataclass(frozen=True)
class _NodeGeometry:
    """One node's world triangles, in the FILE's frame (glTF)."""

    node_name: str
    mesh_name: str
    material_names: tuple[str, ...]
    triangles: tuple[tuple[tuple[float, float, float], ...], ...]


def _identity() -> list[list[float]]:
    return [
        [1.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ]


def _multiply(first: list[list[float]], second: list[list[float]]) -> list[list[float]]:
    """4x4 row-major product, first @ second."""
    return [
        [
            sum(first[row][k] * second[k][column] for k in range(4))
            for column in range(4)
        ]
        for row in range(4)
    ]


def _from_gltf_matrix(values) -> list[list[float]]:
    """A glTF `matrix` is COLUMN-major 16 floats; this returns row-major."""
    return [
        [float(values[column * 4 + row]) for column in range(4)] for row in range(4)
    ]


def _from_trs(translation, rotation, scale) -> list[list[float]]:
    """T * R * S from a node's own `translation`, `rotation` ([x, y, z, w]), `scale`."""
    tx, ty, tz = translation if translation is not None else (0.0, 0.0, 0.0)
    qx, qy, qz, qw = rotation if rotation is not None else (0.0, 0.0, 0.0, 1.0)
    sx, sy, sz = scale if scale is not None else (1.0, 1.0, 1.0)
    rotation_matrix = [
        [
            1.0 - 2.0 * (qy * qy + qz * qz),
            2.0 * (qx * qy - qz * qw),
            2.0 * (qx * qz + qy * qw),
        ],
        [
            2.0 * (qx * qy + qz * qw),
            1.0 - 2.0 * (qx * qx + qz * qz),
            2.0 * (qy * qz - qx * qw),
        ],
        [
            2.0 * (qx * qz - qy * qw),
            2.0 * (qy * qz + qx * qw),
            1.0 - 2.0 * (qx * qx + qy * qy),
        ],
    ]
    return [
        [
            rotation_matrix[0][0] * sx,
            rotation_matrix[0][1] * sy,
            rotation_matrix[0][2] * sz,
            float(tx),
        ],
        [
            rotation_matrix[1][0] * sx,
            rotation_matrix[1][1] * sy,
            rotation_matrix[1][2] * sz,
            float(ty),
        ],
        [
            rotation_matrix[2][0] * sx,
            rotation_matrix[2][1] * sy,
            rotation_matrix[2][2] * sz,
            float(tz),
        ],
        [0.0, 0.0, 0.0, 1.0],
    ]


def _node_local_matrix(node: dict) -> list[list[float]]:
    """A node's own transform: its `matrix` when present, else T * R * S."""
    if "matrix" in node:
        return _from_gltf_matrix(node["matrix"])
    return _from_trs(node.get("translation"), node.get("rotation"), node.get("scale"))


def node_world_matrices(gltf: dict) -> dict[int, list[list[float]]]:
    """{node index: world matrix} for every node reachable from the scene.

    Roots are the scene's own `nodes` when the file names a scene, otherwise
    every node no node lists as a child — a file with no `scenes` array is
    still a file, and skipping its nodes would report an empty model.
    """
    nodes = gltf.get("nodes", [])
    scenes = gltf.get("scenes")
    if scenes:
        scene_index = gltf.get("scene", 0)
        if not 0 <= scene_index < len(scenes):
            raise ValueError(
                f"the file names scene {scene_index} but has {len(scenes)}"
            )
        roots = list(scenes[scene_index].get("nodes", []))
    else:
        children = {child for node in nodes for child in node.get("children", [])}
        roots = [index for index in range(len(nodes)) if index not in children]

    world: dict[int, list[list[float]]] = {}
    stack = [(root, _identity()) for root in roots]
    while stack:
        index, parent_world = stack.pop()
        if not 0 <= index < len(nodes):
            raise ValueError(f"a node references child {index}, out of range")
        if index in world:
            continue  # a node reachable twice is placed once
        world[index] = _multiply(parent_world, _node_local_matrix(nodes[index]))
        for child in nodes[index].get("children", []):
            stack.append((child, world[index]))
    return world


def _apply(matrix: list[list[float]], point) -> tuple[float, float, float]:
    x, y, z = point
    return (
        matrix[0][0] * x + matrix[0][1] * y + matrix[0][2] * z + matrix[0][3],
        matrix[1][0] * x + matrix[1][1] * y + matrix[1][2] * z + matrix[1][3],
        matrix[2][0] * x + matrix[2][1] * y + matrix[2][2] * z + matrix[2][3],
    )


def node_triangles(gltf: dict, binary: bytes, node_index: int, world) -> list:
    """Every TRIANGLES primitive of the node's mesh, positions taken to world.

    An unindexed primitive takes its vertices in accessor order, which glTF
    defines as the sequence of triangles; a primitive of another mode (points,
    lines, strips) contributes nothing, because it has no surface to measure.
    """
    node = gltf["nodes"][node_index]
    if "mesh" not in node:
        return []
    mesh = gltf["meshes"][node["mesh"]]
    triangles = []
    for primitive in mesh["primitives"]:
        if primitive.get("mode", 4) != 4:  # 4 == TRIANGLES
            continue
        positions = read_accessor(gltf, binary, primitive["attributes"]["POSITION"])
        if "indices" in primitive:
            flat = [
                int(value[0])
                for value in read_accessor(gltf, binary, primitive["indices"])
            ]
        else:
            flat = list(range(len(positions)))
        for start in range(0, len(flat) - 2, 3):
            triangles.append(
                tuple(
                    _apply(world, positions[corner])
                    for corner in flat[start : start + 3]
                )
            )
    return triangles


def to_frame(point, frame: str) -> tuple[float, float, float]:
    """A glTF point in the named frame. "engine" is unchanged; "blender" is
    (x, -z, y)."""
    x, y, z = point
    if frame == "engine":
        return (x, y, z)
    if frame == "blender":
        return (x, -z, y)
    raise ValueError(f"frame must be 'engine' or 'blender', got {frame!r}")


def _cross(first, second):
    return (
        first[1] * second[2] - first[2] * second[1],
        first[2] * second[0] - first[0] * second[2],
        first[0] * second[1] - first[1] * second[0],
    )


def _subtract(first, second):
    return (first[0] - second[0], first[1] - second[1], first[2] - second[2])


def _dot(first, second):
    return first[0] * second[0] + first[1] * second[1] + first[2] * second[2]


def _length(vector):
    return math.sqrt(_dot(vector, vector))


def triangle_normal(corners) -> tuple[float, float, float]:
    """Unit normal by the right-hand rule, or (0, 0, 0) for a degenerate triangle."""
    cross = _cross(_subtract(corners[1], corners[0]), _subtract(corners[2], corners[0]))
    size = _length(cross)
    if size == 0.0:
        return (0.0, 0.0, 0.0)
    return (cross[0] / size, cross[1] / size, cross[2] / size)


def triangle_area(corners) -> float:
    """Half the cross product's length."""
    return 0.5 * _length(
        _cross(_subtract(corners[1], corners[0]), _subtract(corners[2], corners[0]))
    )


def convex_hull_2d(points) -> list[tuple[float, float]]:
    """The convex hull of 2-D points, counter-clockwise, collinear dropped.

    Andrew's monotone chain: sort, then walk up and down keeping only left
    turns. Collinear points are dropped because a hull's job here is an
    OUTLINE — a dozen points along one straight edge say nothing a corner does.
    Fewer than 3 distinct points give the points themselves back.
    """
    unique = sorted({(round(x, 12), round(y, 12)) for x, y in points})
    if len(unique) < 3:
        return unique

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list[tuple[float, float]] = []
    for point in unique:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], point) <= 0.0:
            lower.pop()
        lower.append(point)
    upper: list[tuple[float, float]] = []
    for point in reversed(unique):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], point) <= 0.0:
            upper.pop()
        upper.append(point)
    return lower[:-1] + upper[:-1]


def _ground_axes(frame: str) -> tuple[int, int, int]:
    """(index of the up axis, index of the first ground axis, index of the second)."""
    if frame == "engine":
        return 1, 0, 2
    if frame == "blender":
        return 2, 0, 1
    raise ValueError(f"frame must be 'engine' or 'blender', got {frame!r}")


def _component_count(triangles) -> int:
    """Connected components of the welded triangle soup."""
    if not triangles:
        return 0
    welded: dict[tuple[float, ...], int] = {}
    parent: list[int] = []

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(first: int, second: int) -> None:
        first_root, second_root = find(first), find(second)
        if first_root != second_root:
            parent[second_root] = first_root

    for triangle in triangles:
        indices = []
        for corner in triangle:
            key = tuple(
                round(component, POSITION_WELD_DECIMALS) for component in corner
            )
            if key not in welded:
                welded[key] = len(parent)
                parent.append(welded[key])
            indices.append(welded[key])
        union(indices[0], indices[1])
        union(indices[1], indices[2])
    return len({find(index) for index in range(len(parent))})


@dataclass(frozen=True)
class GlbTop:
    """One standable top surface: how high, how big, and which way its outline runs."""

    height: float
    area: float
    outline: tuple[tuple[float, float], ...]
    node_names: tuple[str, ...]
    above_base: float
    bucket: str


@dataclass(frozen=True)
class GlbProfileSample:
    """The highest surface above one point of a section, or a miss."""

    distance: float
    height: float
    hit: bool


@dataclass(frozen=True)
class GlbNodeMeasure:
    """One node's geometry, in the requested frame and units."""

    name: str
    mesh_name: str
    material_names: tuple[str, ...]
    triangle_count: int
    component_count: int
    bounds_min: tuple[float, float, float]
    bounds_max: tuple[float, float, float]


def read_glb_geometry(path) -> tuple[dict, bytes]:
    """(gltf json, binary) of a .glb — one place, so every reader agrees."""
    return parse_glb(path)


def measure_file(
    path,
    *,
    frame: str = "engine",
    units: str = "m",
    top_minimum_area_m2: float = 0.01,
    top_normal_tolerance_deg: float = 5.0,
    profile_from=None,
    profile_to=None,
    profile_step: float = 0.1,
    step_thresholds=(),
):
    """Everything the op reports, computed without touching a scene.

    Split from the op so the arithmetic is testable against a fixture .glb in
    the pure suite — the scene-free half is where every number comes from, and
    the op is a thin wrapper that names the file.
    """
    from pathlib import Path

    glb_path = Path(path)
    if not glb_path.is_file():
        raise FileNotFoundError(f"no .glb file at {glb_path}")
    if glb_path.suffix.lower() != ".glb":
        raise ValueError(f"measure_glb reads a .glb, got {glb_path}")
    if frame not in FRAME_AXIS_MAPPING:
        raise ValueError(f"frame must be 'engine' or 'blender', got {frame!r}")
    if units not in ("m", "ft"):
        raise ValueError(f"units must be 'm' or 'ft', got {units!r}")
    if top_normal_tolerance_deg < 0.0 or top_normal_tolerance_deg > 90.0:
        raise ValueError(
            f"top_normal_tolerance_deg must be within 0..90, got "
            f"{top_normal_tolerance_deg!r}"
        )
    if (profile_from is None) != (profile_to is None):
        raise ValueError(
            "profile_from and profile_to go together: give both ends of the "
            "section or neither"
        )

    gltf, binary = read_glb_geometry(glb_path)
    world_matrices = node_world_matrices(gltf)
    scale = FEET_PER_METRE if units == "ft" else 1.0
    up_axis, ground_a, ground_b = _ground_axes(frame)

    node_geometries: list[_NodeGeometry] = []
    for node_index in sorted(world_matrices):
        node = gltf["nodes"][node_index]
        triangles = node_triangles(gltf, binary, node_index, world_matrices[node_index])
        if not triangles:
            continue
        mesh_name = ""
        material_names: list[str] = []
        if "mesh" in node:
            mesh = gltf["meshes"][node["mesh"]]
            mesh_name = mesh.get("name", "")
            for primitive in mesh["primitives"]:
                if "material" not in primitive:
                    continue
                material = gltf.get("materials", [])[primitive["material"]]
                name = material.get("name", "")
                if name not in material_names:
                    material_names.append(name)
        node_geometries.append(
            _NodeGeometry(
                node_name=node.get("name", f"node_{node_index}"),
                mesh_name=mesh_name,
                material_names=tuple(material_names),
                triangles=tuple(triangles),
            )
        )

    if not node_geometries:
        raise ValueError(f"{glb_path} holds no triangle geometry to measure")

    # EVERY point in the requested frame, so bounds, pivot and tops agree about
    # which axis is up. Frame conversion is a permutation, so converting per
    # point and converting the bounds are the same thing.
    framed_points = [
        to_frame(corner, frame)
        for geometry in node_geometries
        for triangle in geometry.triangles
        for corner in triangle
    ]
    bounds_min = tuple(min(point[axis] for point in framed_points) for axis in range(3))
    bounds_max = tuple(max(point[axis] for point in framed_points) for axis in range(3))
    centre = tuple((bounds_min[axis] + bounds_max[axis]) / 2.0 for axis in range(3))
    # The pivot offset is where the file's ORIGIN sits relative to the geometry's
    # centre: a part modelled in place has 0, and a part whose mesh was authored
    # around its own corner reports the corner's distance from the centre, which
    # is what a placement in the engine has to subtract.
    pivot_offset = tuple(-centre[axis] * scale for axis in range(3))
    base_height = bounds_min[up_axis] * scale
    top_height = bounds_max[up_axis] * scale

    # Tops: upward triangles grouped into surfaces that share a height.
    cos_limit = math.cos(math.radians(top_normal_tolerance_deg))
    upward: list[tuple[float, float, tuple, str]] = []
    for geometry in node_geometries:
        for triangle in geometry.triangles:
            framed = tuple(to_frame(corner, frame) for corner in triangle)
            normal = triangle_normal(framed)
            if normal[up_axis] < cos_limit:
                continue
            area = triangle_area(framed)
            if area <= 0.0:
                continue
            heights = [corner[up_axis] for corner in framed]
            upward.append(
                (
                    sum(heights) / 3.0,
                    area,
                    framed,
                    geometry.node_name,
                )
            )
    tops = _group_tops(
        upward,
        up_axis=up_axis,
        ground_a=ground_a,
        ground_b=ground_b,
        scale=scale,
        base=base_height / scale,
        minimum_area_m2=top_minimum_area_m2,
        step_thresholds=tuple(step_thresholds),
    )

    profile = ()
    if profile_from is not None and profile_to is not None:
        profile = _profile_samples(
            node_geometries,
            profile_from=tuple(profile_from),
            profile_to=tuple(profile_to),
            step=profile_step,
            frame=frame,
            up_axis=up_axis,
            ground_a=ground_a,
            ground_b=ground_b,
            scale=scale,
        )

    nodes = []
    for geometry in node_geometries:
        framed = [
            to_frame(corner, frame)
            for triangle in geometry.triangles
            for corner in triangle
        ]
        nodes.append(
            GlbNodeMeasure(
                name=geometry.node_name,
                mesh_name=geometry.mesh_name,
                material_names=geometry.material_names,
                triangle_count=len(geometry.triangles),
                component_count=_component_count(
                    [
                        tuple(to_frame(corner, frame) for corner in triangle)
                        for triangle in geometry.triangles
                    ]
                ),
                bounds_min=tuple(
                    min(point[axis] for point in framed) * scale for axis in range(3)
                ),
                bounds_max=tuple(
                    max(point[axis] for point in framed) * scale for axis in range(3)
                ),
            )
        )
    nodes.sort(key=lambda node: node.name)

    return {
        "path": str(glb_path),
        "frame": frame,
        "units": units,
        "axis_mapping": FRAME_AXIS_MAPPING[frame],
        "nodes": nodes,
        "bounds_min": tuple(bounds_min[axis] * scale for axis in range(3)),
        "bounds_max": tuple(bounds_max[axis] * scale for axis in range(3)),
        "pivot_offset": pivot_offset,
        "base_height": base_height,
        "top_height": top_height,
        "tops": tops,
        "profile": profile,
        "step_thresholds": tuple(step_thresholds),
    }


def _group_tops(
    upward,
    *,
    up_axis: int,
    ground_a: int,
    ground_b: int,
    scale: float,
    base: float,
    minimum_area_m2: float,
    step_thresholds,
):
    """Upward triangles grouped into tops: welded-vertex connectivity at one height.

    Two upward triangles belong to one top when they share a welded corner AND
    their heights agree within `TOP_HEIGHT_TOLERANCE_M`. Sharing a corner
    without the height test would merge a box's lid with the lip below it;
    the height test alone would merge the lids of two separate boxes.
    """
    if not upward:
        return ()

    welded: dict[tuple, int] = {}
    parent: list[int] = []

    def index_of(point) -> int:
        key = tuple(round(component, POSITION_WELD_DECIMALS) for component in point)
        if key not in welded:
            welded[key] = len(parent)
            parent.append(welded[key])
        return welded[key]

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(first: int, second: int) -> None:
        first_root, second_root = find(first), find(second)
        if first_root != second_root:
            parent[second_root] = first_root

    triangle_heights = []
    triangle_vertices = []
    for height, _area, framed, _node in upward:
        vertices = [index_of(corner) for corner in framed]
        triangle_vertices.append(vertices)
        triangle_heights.append(height)
        union(vertices[0], vertices[1])
        union(vertices[1], vertices[2])

    # The union above merges by vertex alone; split again wherever the two
    # triangles' HEIGHTS disagree, by redoing it in height order.
    order = sorted(range(len(upward)), key=lambda index: triangle_heights[index])
    for position in range(len(order) - 1):
        left, right = order[position], order[position + 1]
        if triangle_heights[right] - triangle_heights[left] > TOP_HEIGHT_TOLERANCE_M:
            continue
        left_roots = {find(index) for index in triangle_vertices[left]}
        right_roots = {find(index) for index in triangle_vertices[right]}
        if left_roots & right_roots:
            union(triangle_vertices[left][0], triangle_vertices[right][0])

    groups: dict[int, list[int]] = {}
    for index in range(len(upward)):
        groups.setdefault(find(triangle_vertices[index][0]), []).append(index)

    tops = []
    for member_indices in groups.values():
        total_area = sum(upward[index][1] for index in member_indices)
        if total_area < minimum_area_m2:
            continue
        weighted_height = (
            sum(upward[index][0] * upward[index][1] for index in member_indices)
            / total_area
        )
        outline = convex_hull_2d(
            [
                (upward[index][2][corner][ground_a], upward[index][2][corner][ground_b])
                for index in member_indices
                for corner in range(3)
            ]
        )
        names = sorted({upward[index][3] for index in member_indices})
        above_base = weighted_height - base
        bucket = ""
        if step_thresholds:
            for threshold in step_thresholds:
                if above_base <= threshold:
                    bucket = f"≤{threshold:g}"
                    break
            else:
                bucket = f">{max(step_thresholds):g}"
        tops.append(
            GlbTop(
                height=weighted_height * scale,
                area=total_area,
                outline=tuple((x * scale, y * scale) for x, y in outline),
                node_names=tuple(names),
                above_base=above_base * scale,
                bucket=bucket,
            )
        )
    tops.sort(key=lambda top: (-top.height, -top.area, top.node_names))
    return tuple(tops)


def _profile_samples(
    node_geometries,
    *,
    profile_from,
    profile_to,
    step,
    frame: str,
    up_axis: int,
    ground_a: int,
    ground_b: int,
    scale: float,
):
    """The highest surface above each point of a straight section.

    The section runs on the frame's GROUND axes (so it is the plan view the
    engine has), from `profile_from` to `profile_to` inclusive, in the call's
    own units. Each sample takes the highest triangle whose 2-D projection
    contains the ground point — barycentric containment, not a normal test, so a
    steep face is still a surface.
    """
    if step <= 0.0:
        raise ValueError(f"profile_step must be positive, got {step!r}")
    start_a, start_b = profile_from[0] / scale, profile_from[1] / scale
    end_a, end_b = profile_to[0] / scale, profile_to[1] / scale
    length = math.hypot(end_a - start_a, end_b - start_b)
    count = math.floor(length / (step / scale)) + 1
    if count > MAXIMUM_PROFILE_SAMPLES:
        raise ValueError(
            f"a section of {length * scale:g} {('ft' if scale != 1.0 else 'm')} at "
            f"step {step:g} needs {count} samples; the maximum is "
            f"{MAXIMUM_PROFILE_SAMPLES}. Raise profile_step."
        )

    # Bin the triangles by their 2-D bounds so a 20k-triangle part does not
    # turn a 200-sample section into four million containment tests.
    triangles = []
    for geometry in node_geometries:
        for triangle in geometry.triangles:
            framed = tuple(to_frame(corner, frame) for corner in triangle)
            triangles.append(framed)
    bins: dict[tuple[int, int], list[int]] = {}
    for index, triangle in enumerate(triangles):
        low_a = min(corner[ground_a] for corner in triangle)
        high_a = max(corner[ground_a] for corner in triangle)
        low_b = min(corner[ground_b] for corner in triangle)
        high_b = max(corner[ground_b] for corner in triangle)
        for cell_a in range(
            math.floor(low_a / PROFILE_BIN_M), math.floor(high_a / PROFILE_BIN_M) + 1
        ):
            for cell_b in range(
                math.floor(low_b / PROFILE_BIN_M),
                math.floor(high_b / PROFILE_BIN_M) + 1,
            ):
                bins.setdefault((cell_a, cell_b), []).append(index)

    samples = []
    for sample_index in range(count):
        fraction = sample_index / (count - 1) if count > 1 else 0.0
        a = start_a + (end_a - start_a) * fraction
        b = start_b + (end_b - start_b) * fraction
        cell = (math.floor(a / PROFILE_BIN_M), math.floor(b / PROFILE_BIN_M))
        best = None
        for index in bins.get(cell, ()):
            triangle = triangles[index]
            best = _height_at(triangle, a, b, up_axis, ground_a, ground_b, best)
        samples.append(
            GlbProfileSample(
                distance=(length * fraction) * scale,
                height=(best if best is not None else 0.0) * scale,
                hit=best is not None,
            )
        )
    return tuple(samples)


def _height_at(triangle, a, b, up_axis, ground_a, ground_b, best):
    """The triangle's height at the ground point (a, b), or `best` if it misses."""
    p0 = (triangle[0][ground_a], triangle[0][ground_b])
    p1 = (triangle[1][ground_a], triangle[1][ground_b])
    p2 = (triangle[2][ground_a], triangle[2][ground_b])
    denominator = (p1[1] - p2[1]) * (p0[0] - p2[0]) + (p2[0] - p1[0]) * (p0[1] - p2[1])
    if abs(denominator) < 1.0e-15:
        return best  # degenerate in plan view: no area to stand on
    weight_0 = (
        (p1[1] - p2[1]) * (a - p2[0]) + (p2[0] - p1[0]) * (b - p2[1])
    ) / denominator
    weight_1 = (
        (p2[1] - p0[1]) * (a - p2[0]) + (p0[0] - p2[0]) * (b - p2[1])
    ) / denominator
    weight_2 = 1.0 - weight_0 - weight_1
    if weight_0 < 0.0 or weight_1 < 0.0 or weight_2 < 0.0:
        return best
    height = (
        weight_0 * triangle[0][up_axis]
        + weight_1 * triangle[1][up_axis]
        + weight_2 * triangle[2][up_axis]
    )
    if best is None or height > best:
        return height
    return best
