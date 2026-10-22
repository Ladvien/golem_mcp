"""A NODE GRAPH: a stack of fields, composed rather than chosen.

The lane used to answer a description with ONE pattern - and a
description is not one pattern but a STACK. A marble is a base of
flat stone with a network of veins over it. A leather is a fine
grain with a stain on it. A metal is a sheet with a brushed
direction and a scratch or two.

Material Maker's answer is a node graph, and this is the same idea
in a form an agent can write: a list of nodes, each a named FIELD
producer, and each node's inputs naming other nodes. The graph
renders to one field, and the field becomes the base colour.

The composition happens in the FIELD domain and not in the image
domain. A blend of two fields is a blend of two fields, and the
image is written once at the end - so a graph is cheap, and a graph
is exact.

Material Maker (MIT, RodZill4) is the blueprint. Its `blend` node
carries normal, dissolve, multiply, screen, overlay, hard-light,
soft-light, burn and dodge; its `warp` node displaces the sample
coordinates along a field's gradient; and its `splatter`, `scratches`
and `crystal` nodes are primitives this lane had no equivalent of.
"""

from __future__ import annotations

import numpy

# The BLEND MODES, and they are Material Maker's list: the same
# Photoshop-style set a node graph has to have for the composites to
# read as composites.
#
# The modes are named for what they do to the two fields, and the
# normal one is the first - a blend with nothing special is a MIX.
BLEND_MODES = (
    "normal",
    "multiply",
    "screen",
    "overlay",
    "hard_light",
    "soft_light",
    "burn",
    "dodge",
    "lighten",
    "darken",
    "difference",
    "additive",
    "addsub",
    "dissolve",
)

# How a DISSOLVE decides, and it is the field's own value against a
# threshold - the same as Material Maker's, which compares a random
# against the opacity.
DISSOLVE_SEED = 17


def _blend_normal(a: numpy.ndarray, b: numpy.ndarray, amount: float) -> numpy.ndarray:
    return amount * a + (1.0 - amount) * b


def _blend_multiply(a: numpy.ndarray, b: numpy.ndarray, amount: float) -> numpy.ndarray:
    return amount * (a * b) + (1.0 - amount) * b


def _blend_screen(a: numpy.ndarray, b: numpy.ndarray, amount: float) -> numpy.ndarray:
    return amount * (1.0 - (1.0 - a) * (1.0 - b)) + (1.0 - amount) * b


def _blend_overlay(a: numpy.ndarray, b: numpy.ndarray, amount: float) -> numpy.ndarray:
    def one(x: numpy.ndarray, y: numpy.ndarray) -> numpy.ndarray:
        return numpy.where(x < 0.5, 2.0 * x * y, 1.0 - 2.0 * (1.0 - x) * (1.0 - y))

    return amount * one(a, b) + (1.0 - amount) * b


def _blend_hard_light(
    a: numpy.ndarray, b: numpy.ndarray, amount: float
) -> numpy.ndarray:
    def one(x: numpy.ndarray, y: numpy.ndarray) -> numpy.ndarray:
        return numpy.where(x < 0.5, 2.0 * x * y, 1.0 - 2.0 * (1.0 - x) * (1.0 - y))

    return amount * (0.5 * (a * b + one(a, b))) + (1.0 - amount) * b


def _blend_soft_light(
    a: numpy.ndarray, b: numpy.ndarray, amount: float
) -> numpy.ndarray:
    def one(x: numpy.ndarray, y: numpy.ndarray) -> numpy.ndarray:
        low = 2.0 * x * y + x * x * (1.0 - 2.0 * y)
        high = 2.0 * x * (1.0 - y) + numpy.sqrt(numpy.clip(x, 0.0, 1.0)) * (
            2.0 * y - 1.0
        )
        return numpy.where(y < 0.5, low, high)

    return amount * one(a, b) + (1.0 - amount) * b


def _blend_burn(a: numpy.ndarray, b: numpy.ndarray, amount: float) -> numpy.ndarray:
    def one(x: numpy.ndarray, y: numpy.ndarray) -> numpy.ndarray:
        return numpy.where(y <= 0.0, 0.0, 1.0 - numpy.minimum(1.0, (1.0 - x) / y))

    return amount * one(a, b) + (1.0 - amount) * b


def _blend_dodge(a: numpy.ndarray, b: numpy.ndarray, amount: float) -> numpy.ndarray:
    def one(x: numpy.ndarray, y: numpy.ndarray) -> numpy.ndarray:
        return numpy.where(
            y >= 1.0, 1.0, numpy.minimum(1.0, x / numpy.maximum(1e-6, 1.0 - y))
        )

    return amount * one(a, b) + (1.0 - amount) * b


def _blend_dissolve(a: numpy.ndarray, b: numpy.ndarray, amount: float) -> numpy.ndarray:
    """A dissolve picks one field or the other, per pixel.

    Material Maker's dissolve compares a random against the opacity,
    and the random is the field's own - so a dissolve over a texture
    is a TEXTURED dissolve and not a salt-and-pepper one.
    """
    from golem_blender.pbr import noise_perlin

    shape = a.shape
    samples = numpy.linspace(0.0, 1.0, shape[0], endpoint=False)
    grid_x, grid_y = numpy.meshgrid(samples, samples, indexing="ij")
    pick = noise_perlin.perlin_2d(
        grid_x * 32.0, grid_y * 32.0, period=32, seed=DISSOLVE_SEED
    )
    pick = (pick - float(pick.min())) / max(1e-9, float(pick.max() - pick.min()))
    return numpy.where(pick < amount, a, b)


def _blend_lighten(a: numpy.ndarray, b: numpy.ndarray, amount: float) -> numpy.ndarray:
    return amount * numpy.maximum(a, b) + (1.0 - amount) * b


def _blend_darken(a: numpy.ndarray, b: numpy.ndarray, amount: float) -> numpy.ndarray:
    return amount * numpy.minimum(a, b) + (1.0 - amount) * b


def _blend_difference(
    a: numpy.ndarray, b: numpy.ndarray, amount: float
) -> numpy.ndarray:
    return amount * numpy.abs(a - b) + (1.0 - amount) * b


def _blend_additive(a: numpy.ndarray, b: numpy.ndarray, amount: float) -> numpy.ndarray:
    return amount * numpy.clip(a + b, 0.0, 1.0) + (1.0 - amount) * b


def _blend_addsub(a: numpy.ndarray, b: numpy.ndarray, amount: float) -> numpy.ndarray:
    """A blend that ADDS the top and SUBTRACTS the bottom.

    It is the mode that draws a dark vein on a pale stone and a pale
    vein on a dark one, and it is the one a material's tone ramp
    needs.
    """
    return amount * numpy.clip(a + (1.0 - b), 0.0, 1.0) + (1.0 - amount) * b


_BLEND_FUNCTIONS = {
    "normal": _blend_normal,
    "multiply": _blend_multiply,
    "screen": _blend_screen,
    "overlay": _blend_overlay,
    "hard_light": _blend_hard_light,
    "soft_light": _blend_soft_light,
    "burn": _blend_burn,
    "dodge": _blend_dodge,
    "lighten": _blend_lighten,
    "darken": _blend_darken,
    "difference": _blend_difference,
    "additive": _blend_additive,
    "addsub": _blend_addsub,
    "dissolve": _blend_dissolve,
}


class NodeGraphError(ValueError):
    """A graph that cannot be rendered."""


def blend_fields(
    a: numpy.ndarray,
    b: numpy.ndarray,
    mode: str = "normal",
    amount: float = 0.5,
) -> numpy.ndarray:
    """Blend two fields together, the way a node graph's blend node does.

    `a` is the TOP field and `b` the one underneath, and `amount` is
    the top's opacity - Material Maker's convention, and the one
    that makes a graph read top-down.
    """
    if mode not in BLEND_MODES:
        raise NodeGraphError(
            f"Unknown blend mode {mode!r}. Expected one of {BLEND_MODES}."
        )
    if not 0.0 <= amount <= 1.0:
        raise NodeGraphError(f"A blend's amount must be 0 to 1, got {amount}.")
    if a.shape != b.shape:
        raise NodeGraphError(
            f"A blend needs two fields of the same shape: {a.shape} and {b.shape}."
        )
    return _BLEND_FUNCTIONS[mode](a, b, amount)


def apply_warp(
    field: numpy.ndarray,
    strength: numpy.ndarray,
    amount: float = 0.1,
    step: float = 0.1,
) -> numpy.ndarray:
    """Warp a field along a STRENGTH field's slope.

    This is Material Maker's `warp` node: the second input is a
    height field and the first is displaced along its gradient, so
    the first one's own detail is dragged along the second's shape.

    The lane's own warp works the same way - it is
    `golem_blender.pbr.warp.warp_field` - and this is the same
    thing wrapped for a graph, so a graph's warp and the pattern's
    own warp are ONE implementation.
    """
    from golem_blender.pbr import warp

    return warp.warp_field(field, strength, amount=amount, step=step)


def splatter_field(
    resolution: int,
    count: int = 25,
    radius: float = 0.05,
    seed: int = 5,
    shape: str = "round",
) -> tuple[numpy.ndarray, numpy.ndarray]:
    """DROPLETS at scattered points - Material Maker's `splatter` node.

    The droplets are POISSON-scattered, so they never overlap, and
    each carries its own radius and its own tone.

    Returns the droplets' coverage and their tone.
    """
    from golem_blender.pbr import noise_scatter

    # The Poisson-disk sampler gives the points and not the count, so
    # the radius is what decides how many fit.
    points = noise_scatter.poisson_disk_2d(
        1.0, 1.0, radius=max(1e-6, radius), seed=seed
    )
    field = numpy.zeros((resolution, resolution), dtype=numpy.float32)
    tone = numpy.zeros((resolution, resolution), dtype=numpy.float32)
    xs = numpy.linspace(0.0, 1.0, resolution, endpoint=False)
    grid_x, grid_y = numpy.meshgrid(xs, xs, indexing="ij")
    for index, (px, py) in enumerate(points):
        # Each droplet's own size, and its own tone, and they are
        # hashed from the index so the map is reproducible.
        own = ((index * 2654435761) % 1000) / 1000.0
        drop_radius = radius * (0.5 + own)
        distance = numpy.hypot(grid_x - px, grid_y - py)
        inside = numpy.clip(1.0 - distance / max(1e-9, drop_radius), 0.0, 1.0)
        if shape == "streak":
            inside = inside**3
        field = numpy.maximum(field, inside)
        tone = numpy.where(inside > 0.0, own, tone)
    return field, tone


def scratches_field(
    resolution: int,
    layers: int = 5,
    length: float = 0.25,
    width: float = 0.4,
    waviness: float = 0.3,
    angle: float = 0.0,
    randomness: float = 0.3,
    seed: int = 9,
) -> numpy.ndarray:
    """SCRATCHES - Material Maker's `scratches2` node.

    A scratch is a line with a WAVY path, and the waviness is what
    makes it read as a scratch and not as a ruled line.
    """
    xs = numpy.linspace(0.0, 1.0, resolution, endpoint=False)
    grid_x, grid_y = numpy.meshgrid(xs, xs, indexing="ij")
    from golem_blender.pbr import noise_perlin

    field = numpy.zeros((resolution, resolution), dtype=numpy.float32)
    for layer in range(max(1, layers)):
        layer_seed = seed + layer * 977
        # The line's own direction, and its own place.
        theta = angle + (randomness * (layer_seed % 97) / 97.0 - randomness / 2.0)
        span = length * (0.4 + 0.6 * ((layer_seed % 53) / 53.0))
        centre_x = ((layer_seed * 37) % 100) / 100.0
        centre_y = ((layer_seed * 71) % 100) / 100.0
        # The waviness, as a field along the line.
        wobble = noise_perlin.perlin_2d(
            grid_x * 8.0,
            grid_y * 8.0,
            period=8,
            seed=layer_seed,
        )
        wobble = (wobble - float(wobble.min())) / max(
            1e-9, float(wobble.max() - wobble.min())
        )
        along = (grid_x - centre_x) * numpy.cos(theta) + (
            grid_y - centre_y
        ) * numpy.sin(theta)
        across = -(grid_x - centre_x) * numpy.sin(theta) + (
            grid_y - centre_y
        ) * numpy.cos(theta)
        offset = (wobble - 0.5) * waviness * span
        distance = numpy.abs(across - offset)
        # The scratch is only its own LENGTH long.
        half = width * 0.01
        line = numpy.clip(1.0 - distance / max(1e-9, half), 0.0, 1.0)
        line = numpy.where(numpy.abs(along) < span * 0.5, line, 0.0)
        field = numpy.maximum(field, line)
    return field


def render_graph(
    graph: dict,
    resolution: int = 1024,
) -> numpy.ndarray:
    """Render a NODE GRAPH into one field.

    The graph is a dict with a "nodes" list. Each node is a dict with
    a "name", a "type", optional "params" and optional "inputs" -
    and the inputs map a socket name to another node's name.

    The node types are the ones this lane knows how to make: "field"
    (a named pattern), "blend", "warp", "splatter", "scratches" and
    "math".
    """
    nodes = graph.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        raise NodeGraphError("A graph needs a non-empty 'nodes' list.")
    by_name: dict[str, dict] = {}
    for node in nodes:
        if not isinstance(node, dict):
            raise NodeGraphError("Every node must be a dict.")
        name = node.get("name")
        if not name:
            raise NodeGraphError("Every node needs a name.")
        if name in by_name:
            raise NodeGraphError(f"Two nodes are called {name!r}.")
        by_name[name] = node
    output = graph.get("output")
    if output is None:
        # The last node is the output, and that is Material Maker's
        # own convention.
        output = nodes[-1].get("name")
    if output not in by_name:
        raise NodeGraphError(f"The output node {output!r} is not in the graph.")

    resolved: dict[str, numpy.ndarray] = {}

    def field_of(name: str) -> numpy.ndarray:
        if name in resolved:
            return resolved[name]
        node = by_name.get(name)
        if node is None:
            raise NodeGraphError(f"No node called {name!r}.")
        value = _render_node(node, field_of, resolution)
        resolved[name] = value
        return value

    return field_of(output)


def _render_node(
    node: dict,
    field_of,
    resolution: int,
) -> numpy.ndarray:
    kind = node.get("type")
    params = dict(node.get("params") or {})
    inputs = dict(node.get("inputs") or {})

    if kind == "field":
        # A named PATTERN, and the pattern's own field is the base.
        pattern_name = params.get("pattern", "voronoi")
        cells = int(params.get("cells", 8))
        field = _pattern_field(pattern_name, cells, resolution)
        strength = float(params.get("strength", 1.0))
        return numpy.clip(field * strength, 0.0, 1.0)

    if kind == "blend":
        a = field_of(inputs["a"])
        b = field_of(inputs["b"])
        return numpy.clip(
            blend_fields(
                a,
                b,
                mode=params.get("mode", "normal"),
                amount=float(params.get("amount", 0.5)),
            ),
            0.0,
            1.0,
        )

    if kind == "warp":
        source = field_of(inputs["source"])
        strength = field_of(inputs["strength"])
        return numpy.clip(
            apply_warp(
                source,
                strength,
                amount=float(params.get("amount", 0.1)),
                step=float(params.get("step", 0.1)),
            ),
            0.0,
            1.0,
        )

    if kind == "splatter":
        field, _tone = splatter_field(
            resolution,
            count=int(params.get("count", 25)),
            radius=float(params.get("radius", 0.05)),
            seed=int(params.get("seed", 5)),
        )
        if "mask" in inputs:
            field = field * field_of(inputs["mask"])
        return numpy.clip(field, 0.0, 1.0)

    if kind == "scratches":
        return numpy.clip(
            scratches_field(
                resolution,
                layers=int(params.get("layers", 5)),
                length=float(params.get("length", 0.25)),
                width=float(params.get("width", 0.4)),
                waviness=float(params.get("waviness", 0.3)),
                angle=float(params.get("angle", 0.0)),
                randomness=float(params.get("randomness", 0.3)),
                seed=int(params.get("seed", 9)),
            ),
            0.0,
            1.0,
        )

    if kind == "colorize":
        source = field_of(inputs["source"])
        stops = params.get("stops") or []
        return numpy.clip(
            colorize_field(
                source,
                stops,
                interpolation=int(params.get("interpolation", 1)),
            ),
            0.0,
            1.0,
        )

    if kind == "math":
        a = field_of(inputs["a"])
        operation = params.get("op", "add")
        b = field_of(inputs["b"]) if "b" in inputs else None
        return numpy.clip(
            _math(a, operation, b, float(params.get("scale", 1.0))), 0.0, 1.0
        )

    raise NodeGraphError(f"Unknown node type {kind!r}.")


def _math(
    a: numpy.ndarray,
    operation: str,
    b: numpy.ndarray | None,
    scale: float,
) -> numpy.ndarray:
    if operation == "add":
        return a * scale if b is None else a + b * scale
    if operation == "subtract":
        return a * scale if b is None else a - b * scale
    if operation == "multiply":
        return a * scale if b is None else a * b * scale
    if operation == "invert":
        return 1.0 - a * scale
    if operation == "max":
        return a * scale if b is None else numpy.maximum(a, b * scale)
    if operation == "min":
        return a * scale if b is None else numpy.minimum(a, b * scale)
    raise NodeGraphError(f"Unknown math operation {operation!r}.")


def _pattern_field(pattern_name: str, cells: int, resolution: int) -> numpy.ndarray:
    """The field of one of the lane's patterns.

    Every pattern's field is NORMALISED to the same meaning before it
    enters a graph: ONE is the feature and ZERO is the ground.

    The lane's own patterns do not agree on that. A Voronoi's field
    is the distance to the cell's edge, so the JOINT is the far end
    of its range; a marble's fibre is the vein's coverage, so the
    VEIN is the top of its range; and a grain's fibre is its own
    line. Blending them raw mixes meanings and the result is noise.

    So each is flipped or scaled into "one is the feature" here, and
    the graph's blend modes mean what they say.
    """
    from golem_blender.pbr import pattern

    if pattern_name == "voronoi":
        _cell, edge, _grid = pattern.cell_and_edge(resolution, cells)
        # The edge distance is ZERO at the joint and LARGEST in the
        # middle of a stone, so the joint is ONE minus the distance.
        reach = max(1e-9, float(edge.max()))
        return numpy.clip(
            1.0 - numpy.asarray(edge, dtype=numpy.float32) / reach, 0.0, 1.0
        )
    if pattern_name == "brick":
        _cell, edge, _grid, _fibre = pattern.brick_field(resolution, cells)
        reach = max(1e-9, float(edge.max()))
        return numpy.clip(
            1.0 - numpy.asarray(edge, dtype=numpy.float32) / reach, 0.0, 1.0
        )
    if pattern_name == "grain":
        _cell, _edge, _grid, fibre = pattern.grain_field(resolution, cells)
        return _normalise(numpy.asarray(fibre, dtype=numpy.float32))
    if pattern_name == "marble":
        _cell, _edge, _grid, fibre = pattern.marble_field(resolution, cells)
        return _normalise(numpy.asarray(fibre, dtype=numpy.float32))
    if pattern_name == "leather":
        _cell, _edge, _grid, fibre = pattern.leather_field(resolution, cells)
        return _normalise(numpy.asarray(fibre, dtype=numpy.float32))
    if pattern_name == "metal":
        _cell, _edge, _grid, fibre = pattern.metal_field(resolution, cells)
        return _normalise(numpy.asarray(fibre, dtype=numpy.float32))
    if pattern_name == "flat":
        return numpy.zeros((resolution, resolution), dtype=numpy.float32)
    raise NodeGraphError(f"Unknown pattern {pattern_name!r}.")


def colorize_field(
    field: numpy.ndarray,
    stops: list,
    interpolation: int = 1,
) -> numpy.ndarray:
    """A material's TONE, shaped by a ramp - Material Maker's `colorize`.

    The lane darkens a surface by a linear amount, and a ramp says
    something a linear darkening cannot: where the STONE goes from
    one tone to another, and how fast.

    Material Maker's own Marble and Wood templates both use it, and
    the marble's ramp has its veins at 0.09 and 0.34 and its stone
    between them - so the vein is a narrow band in a ramp and not a
    darkening of the whole stone.

    `stops` is a list of (position, value) pairs, the position in
    ZERO to ONE and the value in ZERO to ONE.
    """
    if not stops:
        raise NodeGraphError("A colour ramp needs at least one stop.")
    ordered = sorted(stops, key=lambda stop: float(stop[0]))
    positions = numpy.array([float(stop[0]) for stop in ordered], dtype=numpy.float32)
    values = numpy.array([float(stop[1]) for stop in ordered], dtype=numpy.float32)
    source = numpy.clip(numpy.asarray(field, dtype=numpy.float32), 0.0, 1.0)
    if interpolation == 2:
        # CONSTANT, and each stop holds until the next one.
        indices = numpy.searchsorted(positions, source, side="right") - 1
        indices = numpy.clip(indices, 0, len(values) - 1)
        return values[indices]
    return numpy.interp(source, positions, values).astype(numpy.float32)


def _normalise(field: numpy.ndarray) -> numpy.ndarray:
    """Scale a field so its full range is ZERO to ONE."""
    low = float(field.min())
    high = float(field.max())
    if high - low < 1e-9:
        return numpy.zeros_like(field)
    return numpy.clip((field - low) / (high - low), 0.0, 1.0)


__all__ = (
    "BLEND_MODES",
    "NodeGraphError",
    "apply_warp",
    "blend_fields",
    "colorize_field",
    "render_graph",
    "scratches_field",
    "splatter_field",
)
