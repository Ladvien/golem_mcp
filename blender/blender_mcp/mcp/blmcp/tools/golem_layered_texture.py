# SPDX-FileCopyrightText: 2026 Thomas Brittain
#
# SPDX-License-Identifier: GPL-3.0-or-later

# pylint: disable=C0114  # See tool doc-string.

"""
A LAYERED texture set: a base material with others laid over it.

A real surface is rarely one material. A wall has moss in its joints, a
steel plate has rust in its dents, a floor has dust on its tops - and
each of those is a material of its own, laid over the one beneath where
a mask says. This tool writes such a stack as one PBR set, every
material made from its own description through the procedural lane.
"""

__all__ = ("register",)

import json
from pathlib import Path

from golem_blender.pbr import paths as pbr_paths
from mcp.server.fastmcp import (  # pylint: disable=import-error,no-name-in-module
    FastMCP,
    Image,
)
from mcp.types import ToolAnnotations  # pylint: disable=import-error,no-name-in-module

from blmcp.tools.golem_layered_texture_toolcode import Params
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
from blmcp.tools_helpers.live_blender import require_live_blender

_TOOL_CALL = toolcode_wrap_with_calling_convention(
    toolcode_load_from_filepath(__file__)
)


def _failure(message: str) -> list:
    return [json.dumps({"success": False, "error": message[:2000]}, indent=2)]


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        annotations=ToolAnnotations(
            title="Layered Texture Set",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
        )
    )
    async def generate_layered_texture_set(
        texture_name: str,
        base_description: str,
        layers_json: str,
        base_kind: str = "",
        scale_cells: float = 16.0,
        resolution_px: int = 2048,
        texture_dir: str = "",
    ) -> list:
        """Write a base material with others laid over it as one PBR set.

        Writes T_<Name>_BaseColor.png, T_<Name>_ORM.png (AO, roughness,
        metallic), T_<Name>_Normal.png and T_<Name>_Height.png, and
        returns the base colour. The Height is a DISPLACEMENT map, and
        its range follows the base's KIND: a metal's spans a tenth of
        the surface, a rubble's two thirds, as the truths' own
        displacement maps do. "height_range" in the result is the pair
        of values it was written in - set a displacement shader's
        scale from it. A kind with too few truths to fit falls back to
        0 lowest and 1 highest, and "height_range_is_measured" is false.
        Every material - the base and each layer - is made from its own
        description through the procedural lane, so each chooses its own
        pattern, colours, roughness and metal. The set tiles.

        Use it when a surface is a STACK: "a red brick wall with moss in
        its joints", "a grey steel sheet with rust in its dents and
        patches", "a concrete floor with dust on it". A single material
        is generate_procedural_base_color.

        `layers_json` is a JSON list, bottom to top; an EMPTY list composes
        the layers from the base's own words (a "mossy rock" is a rock with
        moss in its hollows, a "rusted iron" a metal with rust patches).
        Each layer:

            {"description": "dark green moss", "amount": 1.0,
             "thickness": 0.15,
             "mask": {"height": {"level": 0.4, "below": true,
                                 "softness": 0.3},
                      "noise": {"cells": 6, "coverage": 0.5,
                                "softness": 0.3, "seed": 3},
                      "combine": "multiply"}}

        "description" is required. Optional: "kind" overrides the
        layer's pattern, "scale_cells" its own scale, "amount" (0..1)
        how opaque it is, "thickness" how much it raises the surface.

        The mask needs at least one source:
        - "height": where the surface built so far is LOW (below=true:
          moss and dirt in joints) or HIGH (below=false: dust and wear
          on tops). level is 0..1 of the surface's height range.
        - "noise": soft patches covering `coverage` of the surface,
          `cells` across.
        - "cavity": where the surface is lower than its neighbourhood
          (rust in dents and scratches, grime in pits).
        "combine" joins the sources: "multiply" (where ALL say yes - moss
        in the joints, but only in patches) or "max" (where ANY says yes
        - rust in the dents and in patches).

        Name the colour in a layer's description: "orange brown rust",
        "dark green moss", "pale grey dust". A layer of rust on its own
        is an orange crust; a "rusty steel" base is the steel.
        """
        require_live_blender()

        try:
            layers = json.loads(layers_json)
        except ValueError as error:
            return _failure(f"layers_json is not valid JSON: {error}")
        if not isinstance(layers, list) or not all(
            isinstance(layer, dict) for layer in layers
        ):
            return _failure("layers_json must be a JSON list of layer objects.")

        directory = Path(texture_dir) if texture_dir else pbr_paths.texture_root()
        params = Params(
            texture_dir=str(directory),
            texture_name=texture_name,
            base_json=json.dumps({"description": base_description, "kind": base_kind}),
            layers_json=json.dumps(layers),
            scale_cells=scale_cells,
            resolution_px=resolution_px,
            repository_src=str(REPOSITORY_SRC),
            venv_site_packages=VENV_SITE_PACKAGES,
            source_fingerprint=source_fingerprint(),
        )
        response = send_code(toolcode_format_call(_TOOL_CALL, params), strict_json=True)
        result = response.get("result") or {}
        if response.get("status") != "ok" or result.get("status") != "ok":
            return _failure(
                str(result.get("message") or response.get("message") or "Unknown error")
            )

        written = json.loads(result["paths_json"])
        base_color = Path(written["base_color"])
        try:
            seam_ratio = pbr_paths.tile_seam_ratio(base_color)
        except (OSError, ValueError) as error:
            return _failure(str(error))

        summary = {
            "success": True,
            "texture_name": texture_name,
            "mac_paths": written,
            "kinds": list(result.get("kinds") or ()),
            "height_range": json.loads(result.get("height_range_json") or "null"),
            "height_range_is_measured": bool(result.get("height_range_is_measured")),
            "layer_count": len(layers),
            "resolution_px": resolution_px,
            "tile_seam_ratio": round(seam_ratio, 3),
            "tile_seam_limit": pbr_paths.TILE_SEAM_LIMIT,
            "tiles_cleanly": seam_ratio <= pbr_paths.TILE_SEAM_LIMIT,
        }
        return [
            Image(data=base_color.read_bytes(), format="png"),
            json.dumps(summary, indent=2),
        ]
