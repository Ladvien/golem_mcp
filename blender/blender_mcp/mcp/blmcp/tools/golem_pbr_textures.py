# SPDX-FileCopyrightText: 2026 Thomas Brittain
#
# SPDX-License-Identifier: GPL-3.0-or-later

# pylint: disable=C0114  # See tool doc-string.

"""
PBR texture sets: generate the base colour, preview the result, export the set.

Three tools, and the boundary between them is measured rather than
arranged:

- ``generate_texture_base`` runs in this server process and needs no
  Blender: it calls the golem server on big, which runs FLUX, and writes
  the map into the texture directory. It is in TOOLS_WITHOUT_BLENDER, so
  a closed Blender does not pause it.
- ``preview_texture`` renders the object, so it needs the OPEN Blender
  and goes through the add-on's exec. The render is in a shader-accurate
  engine (EEVEE), because the Workbench contact sheet reads only
  ``material.diffuse_color`` and therefore cannot show a texture at all
  (measured: a solid-red texture with a green diffuse_color rendered
  bright green in Workbench and bright red in EEVEE).
- ``export_texture_set`` copies files, so it needs no Blender either.

The apply step is NOT a tool here: the ops ``assign_pbr_texture_set``,
``bake_orm_map``, ``bake_normal_map`` and ``pbr_texture_report`` are
already exposed as tools by the facade, and a second path to the same
action is what ``tests/pure/test_one_path_ops.py`` exists to prevent.
"""

__all__ = ("register",)

import json
from pathlib import Path

from golem_blender.kitbash import paths as kitbash_paths
from golem_blender.pbr import generate as pbr_generate
from golem_blender.pbr import paths as pbr_paths
from mcp.server.fastmcp import (  # pylint: disable=import-error,no-name-in-module
    FastMCP,
    Image,
)
from mcp.types import ToolAnnotations  # pylint: disable=import-error,no-name-in-module

from blmcp.tools.golem_pbr_textures_toolcode import Params
from blmcp.tools_helpers import (
    toolcode_format_call,
    toolcode_load_from_filepath,
    toolcode_wrap_with_calling_convention,
)
from blmcp.tools_helpers.connection import send_code
from blmcp.tools_helpers.golem_blender_bridge import (
    REPOSITORY_SRC,
    VENV_SITE_PACKAGES,
    source_fingerprint,
)
from blmcp.tools_helpers.golem_remote import GolemRemote
from blmcp.tools_helpers.live_blender import require_live_blender

# The golem server's image-generation tool.
GENERATE_IMAGE_TOOL = "generate_image"
# The model the lane generates with by default.
DEFAULT_MODEL = "flux2-klein-4b"
# The default init-image influence.
#
# `image_strength` is how much of the INIT IMAGE the result KEEPS: 1 is
# the init almost unchanged, 0 discards it. That is measured against
# mflux, not assumed — the mean difference from the init was 0.5 at
# strength 1.0, 17.1 at 0.6, 45.2 at 0.25 and 37.3 at 0.0. So to
# REPLACE a map, use a LOW strength; to nudge it, a HIGH one.
DEFAULT_IMAGE_STRENGTH = 0.4

_TOOL_CALL = toolcode_wrap_with_calling_convention(
    toolcode_load_from_filepath(__file__)
)


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        annotations=ToolAnnotations(
            title="Generate Texture Base Colour",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=True,
        )
    )
    async def generate_texture_base(
        prompt: str,
        output_name: str = "",
        model: str = DEFAULT_MODEL,
        seed: int = 42,
        steps: int = 8,
        width: int = pbr_paths.SET_RESOLUTION_PX,
        height: int = pbr_paths.SET_RESOLUTION_PX,
        init_image_path: str = "",
        image_strength: float = DEFAULT_IMAGE_STRENGTH,
        texture_dir: str = "",
        make_tileable: bool = True,
    ) -> list:
        """Generate a base-colour texture on the golem server and write it into the texture set; returns the image and its paths.

        `init_image_path` refines an existing map: it must be a path under
        the codex root (the Mac's `~/mnt/codex_fs/...`). `image_strength`
        is how much of the init image the result KEEPS: 1 is the init
        almost unchanged, 0 discards it. Measured, not assumed — the
        mean difference from the init was 0.5 at strength 1.0, 17.1 at
        0.6, 45.2 at 0.25 and 37.3 at 0.0. So to REPLACE the map, use a
        LOW strength; to keep it and nudge it, use a HIGH one. The
        written file is `T_<output_name>_BaseColor.png`.

        `make_tileable` hides the map's seam, by the method
        material-maker uses: three copies of the map, blended so that
        the edge carries the image's own middle. A GENERATED map does
        not tile otherwise - its seam is a property of the sample, not
        of the size - and the blend is cheap at the width it uses.
        Measured, the seam goes from 1.377x to 0.304x of the texture's
        largest ordinary features, which is better than the reference
        sets ambientcg makes to tile (0.32x to 0.47x), and the
        correlation with the original is 0.7711. It is not free: the
        blend moves the image, so the seam is measured afterwards and
        reported as `tile_seam_ratio`.

        `width` and `height` default to the SET's resolution, the same
        number the bakes use, so a set's three maps agree. Every other
        set on codex_fs has all three at 2048, and the relief is sampled
        FROM the base colour, so the base colour's pixels decide where
        the baked joints land: at 1024 the 512-cell grid gets 2 albedo
        pixels per cell and at 2048 it gets 4, and the occlusion's dark
        fraction rises from 10.29% to 12.13%.
        """
        directory = Path(texture_dir) if texture_dir else pbr_paths.texture_root()
        texture_name = output_name or "Texture"

        arguments = {
            "prompt": prompt,
            "model": model,
            "output_name": f"pbr_{texture_name}",
            "seed": seed,
            "steps": steps,
            "width": width,
            "height": height,
        }
        if init_image_path:
            # big opens the init image, so it must be handed over as the
            # path big sees; a path outside the codex root is refused.
            arguments["image_path"] = pbr_paths.big_path(Path(init_image_path))
            arguments["image_strength"] = image_strength

        remote = GolemRemote()
        result = await remote.call_tool(GENERATE_IMAGE_TOOL, arguments)
        if result.isError:
            return [_error_text(result, "generate_image")]

        payload = _first_json_payload(result)
        if payload is None:
            return [_error_text(result, "generate_image")]
        if not payload.get("success", True):
            return [json.dumps(payload, indent=2)]

        source_png = _resolve_generated_png(payload)
        if source_png is None:
            return [
                json.dumps(
                    {
                        "success": False,
                        "error": (
                            "generate_image reported success but the generated PNG "
                            "is not where it said it would be."
                        ),
                        "result": payload,
                    },
                    indent=2,
                )
            ]

        written = pbr_generate.write_generated_texture(
            source_png=source_png,
            texture_name=texture_name,
            texture_directory=directory,
            model=model,
            seed=seed,
            steps=steps,
            width_px=width,
            height_px=height,
            prompt=prompt,
            image_strength=image_strength,
            init_image_path=init_image_path,
            make_tileable=make_tileable,
        )

        summary = {
            "success": True,
            "texture_name": texture_name,
            "mac_path": written.mac_path,
            "big_path": written.big_path,
            "model": written.model,
            "seed": written.seed,
            "steps": written.steps,
            "width_px": written.width_px,
            "height_px": written.height_px,
            "prompt": written.prompt,
            "image_strength": written.image_strength,
            "init_image_path": written.init_image_path,
            "tile_seam_ratio": written.tile_seam_ratio,
            "tile_seam_limit": pbr_paths.TILE_SEAM_LIMIT,
            "tiles_cleanly": written.tile_seam_ratio <= pbr_paths.TILE_SEAM_LIMIT,
        }

        # Does the generated map TILE? A set is something you repeat
        # across a floor, and a generated image's seam is a property of
        # the SAMPLE, not of the size - so the only way to know is to
        # measure this one. The seam's step against the texture's
        # largest ordinary features: the sets already on codex_fs
        # measure 0.20x to 3.50x, and the 3.50x one does show its
        # boundaries.
        try:
            seam_ratio = pbr_paths.tile_seam_ratio(Path(written.mac_path))
        except (OSError, ValueError) as error:
            seam_ratio = None
            summary["seam_measurement_error"] = str(error)
        if seam_ratio is not None:
            summary["tile_seam_ratio"] = round(seam_ratio, 3)
            summary["tile_seam_limit"] = pbr_paths.TILE_SEAM_LIMIT
            summary["tiles_cleanly"] = seam_ratio <= pbr_paths.TILE_SEAM_LIMIT
        return [
            Image(data=Path(written.mac_path).read_bytes(), format="png"),
            json.dumps(summary, indent=2),
        ]

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Preview Texture",
            readOnlyHint=True,
            destructiveHint=False,
        )
    )
    async def preview_texture(
        object_name: str,
        resolution_px: int = 512,
        contact_sheet: bool = True,
    ) -> list:
        """Render the named object in a shader-accurate engine so its texture can be seen; returns the render as an image.

        This is the EEVEE render, NOT the Workbench contact sheet: Workbench
        reads only the material's viewport colour, so a texture reviewed
        through it is reviewed blind. `contact_sheet=True` returns the
        five-view sheet; `False` returns a single view.
        """
        require_live_blender()

        params = Params(
            object_name=object_name,
            resolution_px=resolution_px,
            contact_sheet=contact_sheet,
            repository_src=str(REPOSITORY_SRC),
            venv_site_packages=VENV_SITE_PACKAGES,
            source_fingerprint=source_fingerprint(),
        )
        code = toolcode_format_call(_TOOL_CALL, params)
        response = send_code(code, strict_json=True)
        if response.get("status") != "ok":
            return [
                json.dumps(
                    {
                        "success": False,
                        "error": str(response.get("message", "Unknown error"))[:2000],
                    },
                    indent=2,
                )
            ]

        result = response.get("result") or {}
        if result.get("status") != "ok":
            return [
                json.dumps(
                    {
                        "success": False,
                        "error": str(result.get("message", "Unknown error"))[:2000],
                    },
                    indent=2,
                )
            ]

        paths = list(result.get("paths") or [])
        if not paths:
            return [
                json.dumps(
                    {"success": False, "error": "The render wrote no image."}, indent=2
                )
            ]

        images = [Image(data=Path(path).read_bytes(), format="png") for path in paths]
        summary = {
            "success": True,
            "paths": paths,
            "engine": result.get("engine", ""),
            "resolution_px": result.get("resolution_px", resolution_px),
            "object_name": result.get("object_name", object_name),
        }
        return [images[0], json.dumps(summary, indent=2), *images[1:]]

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Export Texture Set",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
        )
    )
    async def export_texture_set(
        texture_name: str,
        texture_dir: str = "",
        destination: str = "",
        extras: list[str] | None = None,
    ) -> str:
        """Copy a texture set's maps and its metadata into the export directory; returns the written paths as JSON.

        `extras` are files copied alongside the maps — the environment
        map the set was lit with, the reference photos it was authored
        from. Without them the export says how the set was MADE but not
        how to light it, so it is not reusable on its own.

        The export directory is written as a CLEAN SET: a file a
        previous export put there and this one does not include is
        removed, and the result says what was removed under "removed".
        A file no export claims is left alone.
        """
        directory = Path(texture_dir) if texture_dir else pbr_paths.texture_root()
        target = Path(destination) if destination else directory / texture_name
        report = pbr_generate.export_texture_set(
            texture_name,
            directory,
            target,
            metadata={"channel_packing": pbr_paths.ORM_CHANNEL_PACKING},
            extras=[Path(extra) for extra in (extras or ())],
        )
        return json.dumps(report, indent=2)


def _first_json_payload(result) -> dict | None:
    """The first JSON object in a tool result's text content, or None."""
    for block in result.content or []:
        text = getattr(block, "text", None)
        if not text:
            continue
        try:
            payload = json.loads(text)
        except (TypeError, ValueError):
            continue
        if isinstance(payload, dict):
            return payload
    return None


def _error_text(result, tool_name: str) -> str:
    """The text of a failed remote call."""
    texts = [
        getattr(block, "text", "")
        for block in result.content or []
        if getattr(block, "text", "")
    ]
    return json.dumps(
        {
            "success": False,
            "error": f"{tool_name} failed on the golem server.",
            "detail": "\n".join(texts)[:2000],
        },
        indent=2,
    )


def _resolve_generated_png(payload: dict) -> Path | None:
    """The generated PNG on a filesystem this process can open.

    The golem server writes the image into its own output directory and
    publishes a copy under the codex root. BOTH of those paths are
    paths as BIG sees them, so they must be translated to the Mac's
    mount before they can be opened here. Reading them as Mac paths
    silently found a STALE file: /mnt/codex_fs/... does not exist on the
    Mac, so the lookup failed and the copy took whatever was already at
    the destination — the previous map, byte for byte, while the tool
    reported success.
    """
    reference_dir = payload.get("reference_dir")
    if reference_dir:
        candidate = _mac_path_of(reference_dir)
        if candidate is not None:
            image = candidate / "reference.png"
            if image.is_file():
                return image

    remote_path = payload.get("remote_path")
    if remote_path:
        candidate = _mac_path_of(remote_path)
        if candidate is not None and candidate.is_file():
            return candidate

    # NOT `local_path`: that is big's own output directory, which the
    # Mac cannot open. Reading it as a Mac path found a STALE file at
    # the same absolute path and reported success — the same failure
    # this function's docstring describes. If nothing under the codex
    # root resolves, the caller says so.
    return None


def _mac_path_of(big_path: str) -> Path | None:
    """The Mac's path for a path big reported, or None when it is not one.

    A path big gives that is not under the codex root is on big's own
    filesystem, which this process cannot open at all.
    """
    try:
        return kitbash_paths.mac_path(big_path)
    except ValueError:
        return None
