# SPDX-FileCopyrightText: 2026 Thomas Brittain
#
# SPDX-License-Identifier: GPL-3.0-or-later

# pylint: disable=C0114  # See tool doc-string.

"""
The PROCEDURAL half of the PBR texture lane: a base colour computed
from Blender's own nodes.

The AI half (`generate_texture_base`) runs on the golem server and
needs no Blender. This one needs the open Blender, because the
pattern IS Blender's nodes: a Voronoi pattern's cell edges are the
joints, each cell is a stone, and the cell's own random value is its
colour.

Why it is worth having, measured: a generated map's seam is a
property of the SAMPLE - four generations of one prompt measured
1.38x, 1.57x, 1.10x and 1.38x the texture's largest ordinary
features - while a procedural map's is 0.025x, because the pattern is
evaluated on a wrapped lattice and the image's edge meets its own
edge exactly. The maps baked from it inherit that: the normal map's
seam measured 0.18x against a generated map's 0.39x.

What it is NOT is photoreal. The stones are polygonal rather than
rounded, and the variation within a stone is a noise texture rather
than wear. What it IS is reproducible, adjustable with a number
instead of a prompt, and exactly tileable.
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

from blmcp.tools.golem_procedural_colour_toolcode import Params
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


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        annotations=ToolAnnotations(
            title="Procedural Base Colour",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
        )
    )
    async def generate_procedural_base_color(
        texture_name: str,
        description: str = "",
        kind: str = "",
        scale_cells: float = 16.0,
        width_px: int = 2048,
        height_px: int = 2048,
        texture_dir: str = "",
        graph_json: str = "",
    ) -> list:
        """Write a PROCEDURAL base colour into the texture set; returns the image and its paths.

        The whole set can be made this way, with bpy alone: the base
        colour is computed from Blender's own nodes, the relief is
        computed from them too, and the ORM and the normal map are
        baked from that relief.

        What it is NOT is photoreal - the stones are Voronoi cells, so
        they are polygonal rather than rounded, and the variation
        within a stone is a noise texture rather than wear. What it
        IS is reproducible, adjustable with a number instead of a
        prompt, and TILEABLE: the pattern is evaluated on a wrapped
        lattice, so the image's edge meets its own edge exactly.

        Measured, the seam is 0.025x the texture's largest ordinary
        features, against a generated map's 1.38x - and the generated
        map's seam is a property of the SAMPLE, so four generations
        of one prompt measured 1.38x, 1.57x, 1.10x and 1.38x.

        `description` is the material in words - "grey cliff rock",
        "white brick wall", "dark espresso hardwood floor", "brushed
        silver steel" - and it chooses the COLOURS (brightness, hue,
        spread, mortar) and, unless `kind` names one, the PATTERN. Give
        it every time: without it the map is a default grey.

        `kind` overrides the pattern: "voronoi" (set stones), "scattered"
        (loose gravel), "brick" (courses; tiles are an aligned grid),
        "grain" (a board's growth rings), "parquet" (staggered planks),
        "herringbone", "marble" (a veined crackle), "metal" (a brushed
        or rolled sheet), "flat" (plaster, paint, concrete), "rock" (a
        rock face), "moss", "grass", "woven" (cloth), "carpet",
        "leather", "wallpaper", "roof" (shingles), "markings" (road
        lines), "asphalt" (aggregate; worn and cracked from the words),
        "banded" (onyx, travertine), "fan" (cobbles laid in arches), "bark".
        `scale_cells` is how many features cross the image.

        `graph_json` COMPOSES the texture instead of choosing one
        pattern, and it is how a description that is really a STACK
        gets built: a marble is flat stone with a network of veins
        over it, and a leather is a fine grain with a stain on it.

        A graph is JSON with a "nodes" list. Each node has a "name",
        a "type", optional "params" and optional "inputs" - and the
        inputs name other nodes:

            {"nodes": [
              {"name": "veins", "type": "field",
               "params": {"pattern": "marble", "cells": 14}},
              {"name": "base", "type": "field",
               "params": {"pattern": "flat", "cells": 8}},
              {"name": "mix", "type": "blend",
               "params": {"mode": "normal", "amount": 0.55},
               "inputs": {"a": "veins", "b": "base"}}
            ]}

        The node types are "field" (a named pattern), "blend",
        "warp", "splatter", "scratches" and "math". The blend modes
        are "normal", "multiply", "screen", "overlay", "hard_light",
        "soft_light", "burn", "dodge" and "dissolve".

        Every field is normalised before it enters a graph, so ONE is
        the feature and ZERO is the ground - and the blend modes mean
        what they say.
        """
        require_live_blender()

        directory = Path(texture_dir) if texture_dir else pbr_paths.texture_root()
        output_path = directory / pbr_paths.base_color_file_name(texture_name)

        params = Params(
            output_path=str(output_path),
            kind=kind,
            scale_cells=scale_cells,
            width_px=width_px,
            height_px=height_px,
            repository_src=str(REPOSITORY_SRC),
            venv_site_packages=VENV_SITE_PACKAGES,
            source_fingerprint=source_fingerprint(),
            graph_json=graph_json,
            description=description,
        )
        code = toolcode_format_call(_TOOL_CALL, params)
        response = send_code(code, strict_json=True)
        result = response.get("result") or {}
        if response.get("status") != "ok" or result.get("status") != "ok":
            message = str(
                result.get("message") or response.get("message") or "Unknown error"
            )
            return [json.dumps({"success": False, "error": message[:2000]}, indent=2)]

        written = Path(result["output_path"])
        try:
            seam_ratio = pbr_paths.tile_seam_ratio(written)
        except (OSError, ValueError) as error:
            return [json.dumps({"success": False, "error": str(error)}, indent=2)]

        summary = {
            "success": True,
            "texture_name": texture_name,
            "mac_path": str(written),
            "kind": result.get("kind") or kind,
            "description": description,
            "composed": bool(graph_json),
            "scale_cells": scale_cells,
            "width_px": width_px,
            "height_px": height_px,
            "tile_seam_ratio": round(seam_ratio, 3),
            "tile_seam_limit": pbr_paths.TILE_SEAM_LIMIT,
            "tiles_cleanly": seam_ratio <= pbr_paths.TILE_SEAM_LIMIT,
        }
        return [
            Image(data=written.read_bytes(), format="png"),
            json.dumps(summary, indent=2),
        ]
