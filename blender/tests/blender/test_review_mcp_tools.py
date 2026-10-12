"""
Blender-side regression tests for ``blender_mcp/mcp/blmcp/tools`` tool-code
(slice ``mcp_tools``, 2026-10-07), measured on Blender 5.2:

* ``scene.node_tree`` no longer exists, so ``get_blendfile_summary_usage_guess``
  scored Compositing 0 and ignored Render Layers for every file; the tree is
  ``scene.compositing_node_group``.
* ``scene.render.engine`` has no ``BLENDER_EEVEE_NEXT``; a comparison against it
  never matched, so the thumbnail's EEVEE sample cap never applied.
* ``_image_downscale_to_size_limit`` returned the full-size PNG when no
  downscale fit ``size_limit_in_bytes``, so the screenshot tools' "caps the
  image size" held only when a downscale happened to fit; it now raises.
"""

import ast
import importlib.util
from pathlib import Path

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module (pip install bpy)")

pytestmark = pytest.mark.blender

TOOLS_DIRECTORY = (
    Path(__file__).resolve().parents[2] / "blender_mcp" / "mcp" / "blmcp" / "tools"
)
COMPOSITOR_NODE_COUNT_ABOVE_STARTER = 3
RENDER_LAYERS_ONLY_SCORE = 33  # one of three rendering signals, round(100 / 3)


def _load_toolcode(file_name: str):
    spec = importlib.util.spec_from_file_location(
        "review_mcp_tools_" + file_name[:-3], TOOLS_DIRECTORY / file_name
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def factory_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    yield bpy.context.scene


def _usage_scores(scene) -> dict[str, dict[str, int]]:
    usage = _load_toolcode("get_blendfile_summary_usage_guess_toolcode.py")
    return usage.main(None).usage_guesses


def _give_compositing_group(scene, node_types: tuple[str, ...]):
    group = bpy.data.node_groups.new("ReviewComposite", "CompositorNodeTree")
    for node_type in node_types:
        group.nodes.new(node_type)
    scene.compositing_node_group = group
    return group


def test_usage_guess_sees_a_compositor_tree(factory_scene):
    baseline = _usage_scores(factory_scene)["Compositing"]["score"]
    assert baseline == 0, "an untouched scene must not read as compositing"

    node_types = ("CompositorNodeRLayers", "NodeGroupOutput", "CompositorNodeBlur")
    assert len(node_types) == COMPOSITOR_NODE_COUNT_ABOVE_STARTER
    _give_compositing_group(factory_scene, node_types)
    assert _usage_scores(factory_scene)["Compositing"]["score"] == 100


def test_usage_guess_counts_render_layers_node_as_rendering(factory_scene):
    baseline = _usage_scores(factory_scene)["Rendering"]["score"]
    _give_compositing_group(factory_scene, ("CompositorNodeRLayers",))
    assert (
        _usage_scores(factory_scene)["Rendering"]["score"] - baseline
        == RENDER_LAYERS_ONLY_SCORE
    )


def _engine_ids_compared_in(path: Path) -> set[str]:
    """String constants compared against an ``.engine`` attribute in ``path``."""
    ids: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not isinstance(node, ast.Compare):
            continue
        operands = [node.left, *node.comparators]
        if not any(
            isinstance(operand, ast.Attribute) and operand.attr == "engine"
            for operand in operands
        ):
            continue
        for operand in operands:
            if isinstance(operand, ast.Constant) and isinstance(operand.value, str):
                ids.add(operand.value)
            if isinstance(operand, ast.Tuple):
                ids.update(e.value for e in operand.elts if isinstance(e, ast.Constant))
    return ids


def test_every_engine_id_tool_code_compares_against_exists_in_blender():
    valid_ids = {
        item.identifier
        for item in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items
    }
    compared: dict[str, set[str]] = {}
    for path in sorted(TOOLS_DIRECTORY.glob("*_toolcode.py")):
        ids = _engine_ids_compared_in(path)
        if ids:
            compared[path.name] = ids
    # The probe must see something: both known comparisons live in these files.
    assert set(compared) == {
        "get_blendfile_summary_usage_guess_toolcode.py",
        "render_thumbnail_to_path_toolcode.py",
    }
    for file_name, ids in compared.items():
        # CYCLES is an add-on engine, listed only when Cycles is enabled.
        stale = ids - valid_ids - {"CYCLES"}
        assert not stale, (
            f"{file_name} compares scene.render.engine to ids Blender does not have: {stale}"
        )


NOISE_IMAGE_SIZE_PX = 512
NOISE_SEED = 0
IMPOSSIBLE_LIMIT_BYTES = 16
FEASIBLE_LIMIT_BYTES = 200_000


def _noise_png(directory: Path) -> Path:
    """An incompressible PNG: random pixels, far above FEASIBLE_LIMIT_BYTES at full size."""
    import numpy as np

    image = bpy.data.images.new("ReviewNoise", NOISE_IMAGE_SIZE_PX, NOISE_IMAGE_SIZE_PX)
    rng = np.random.default_rng(NOISE_SEED)
    image.pixels.foreach_set(
        rng.random(NOISE_IMAGE_SIZE_PX * NOISE_IMAGE_SIZE_PX * 4, dtype=np.float32)
    )
    image.filepath_raw = str(directory / "noise.png")
    image.file_format = "PNG"
    image.save()
    return directory / "noise.png"


def test_image_downscale_fits_a_feasible_limit(factory_scene, tmp_path):
    template = _load_toolcode("_template_image_downscale_to_size_limit.py")
    source = _noise_png(tmp_path)
    assert source.stat().st_size > FEASIBLE_LIMIT_BYTES, "the probe must start oversize"
    data = template._image_downscale_to_size_limit(
        str(tmp_path), str(source), FEASIBLE_LIMIT_BYTES
    )
    assert 0 < len(data) <= FEASIBLE_LIMIT_BYTES


def test_image_downscale_raises_when_no_downscale_fits(factory_scene, tmp_path):
    template = _load_toolcode("_template_image_downscale_to_size_limit.py")
    source = _noise_png(tmp_path)
    with pytest.raises(RuntimeError, match="byte limit"):
        template._image_downscale_to_size_limit(
            str(tmp_path), str(source), IMPOSSIBLE_LIMIT_BYTES
        )


# --- review follow-up 2026-10-07 (D5): render paths and the objects summary ---

THUMBNAIL_RESOLUTION_PX = 32
HIDDEN_OBJECT_NAME = "HiddenInViewport"


@pytest.mark.parametrize(
    "toolcode_file",
    ["render_viewport_to_path_toolcode.py", "render_thumbnail_to_path_toolcode.py"],
)
def test_a_render_tool_returns_the_file_it_wrote(toolcode_file):
    """`write_still` appends the format's extension to `filepath`, so the tool
    answered with 'probe' while the file on disk was 'probe.png': the returned
    path named a file Blender never wrote."""
    import os

    bpy.ops.wm.read_factory_settings()  # not empty: the render needs the default camera
    render = bpy.context.scene.render
    render.engine = "BLENDER_WORKBENCH"
    render.resolution_x = THUMBNAIL_RESOLUTION_PX
    render.resolution_y = THUMBNAIL_RESOLUTION_PX
    toolcode = _load_toolcode(toolcode_file)

    result = toolcode.main(toolcode.Params(output_path="probe"))

    assert result.status == "ok", result
    assert result.filepath.endswith(".png"), result.filepath
    assert os.path.isfile(result.filepath), result.filepath


def test_the_objects_summary_separates_viewport_hide_from_view_layer_hide(
    factory_scene,
):
    """`hide_viewport` was filled from `obj.hide_get()`, the VIEW LAYER eye, so
    an object disabled in viewports (the monitor icon) read as not hidden."""
    mesh = bpy.data.meshes.new(HIDDEN_OBJECT_NAME)
    hidden = bpy.data.objects.new(HIDDEN_OBJECT_NAME, mesh)
    factory_scene.collection.objects.link(hidden)
    hidden.hide_viewport = True
    summary = _load_toolcode("get_objects_summary_toolcode.py")

    result = summary.main(None)

    objects = [o for c in result.collections for o in c["objects"]]
    (info,) = [o for o in objects if o["name"] == HIDDEN_OBJECT_NAME]
    assert info["hide_viewport"] is True
    assert info["hide_in_view_layer"] is False
