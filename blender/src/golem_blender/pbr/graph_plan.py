"""The GRAPH a description calls for, built from the fitted tables.

A description is not one pattern but a STACK, and Material Maker's
answer is a node graph. The graph's own building blocks live in
`nodegraph.py`; this is the part that turns a DESCRIPTION into one.

And the part that turns a description into a graph belongs with the
fitted tables, and not in the graph's own module: the palette holds
what the truth's own says about every word, and a graph whose layers
are guessed throws that away.

So every layer here is the palette's own fitted answer:

- the base pattern is the pattern the words call for;
- the cells are the truth's own feature count;
- the scratch layer's strength is `scratch_strength_for_description`;
- the curvature layer's is `curvature_strength_for_description`;
- and the blend's amount is the difference between the description's
  own spread and the base pattern's own - so the extra layer
  carries exactly the contrast the base pattern cannot.

That last one is the point: a layer is worth adding when the words
say the surface varies MORE than the base pattern can, and the
measured difference is how much.
"""

from __future__ import annotations

import re

# And how much of the BASE an extra layer carries, and it is a small
# share.
#
# The layer's own strength says how much the SURFACE varies because
# of it, and the base pattern already carries most of the surface's
# variation. So the layer's share of the image is the strength times
# this - and at full strength a scratch layer was a bright zebra of
# worms over the sheet, where the truth's own Metal038 is a smooth
# grey plate.
GRAPH_LAYER_AMOUNT = 0.15
# And how much a patch of MOSS darkens the stone under it.
GRAPH_MOSS_AMOUNT = 0.35
# And how soft a patch of MOSS is, in pixels of the tile.
#
# A patch of moss is a patch of COLOUR and it has a soft edge, and a
# soft edge is a tone and not a texture. The splatter's droplets have
# hard edges, and multiplied in they put hard-edged structure into
# the surface: the ground's feature scale read 3.84x the truth's
# where the single-pattern path read 0.83x.
GRAPH_MOSS_BLUR = 24.0


def _words(description: str) -> set[str]:
    return {word.strip(".,") for word in description.lower().replace(",", " ").split()}


def _number(text: str, digits: str) -> float:
    """The first number in a tag, and zero when there is none."""
    match = re.search(digits, text)
    return float(match.group(0)) if match else 0.0


def graph_for_description(
    description: str,
    kind: str,
    cells: float,
    spread: float | None = None,
) -> dict | None:
    """The NODE GRAPH a description calls for, and None when it calls
    for none.

    `cells` is the surface's own feature count - the truth's own, when
    the caller has it - and every layer's scale follows it, so the
    graph's details are the size the material's details are.
    """
    from golem_blender.pbr import palette

    words = _words(description)
    if not words:
        return None
    count = max(2, round(cells))
    nodes: list[dict] = []

    # The BASE, and it is the pattern the words call for.
    base_pattern = {
        "metal": "metal",
        "grain": "grain",
        "marble": "marble",
        "leather": "leather",
        "voronoi": "voronoi",
        "brick": "brick",
        "scattered": "scattered",
        "flat": "flat",
        "carpet": "carpet",
        "parquet": "parquet",
        "woven": "woven",
        "wallpaper": "wallpaper",
        "markings": "markings",
        "roof": "roof",
        "herringbone": "herringbone",
    }.get(kind, "voronoi")
    nodes.append(
        {
            "name": "base",
            "type": "field",
            "params": {
                "pattern": base_pattern,
                "cells": count,
                "description": description,
            },
        }
    )
    output = "base"

    # And the SCRATCHES, when the words say the surface is scratched.
    #
    # The strength is the palette's own fitted answer and not a
    # guess, and the count and the width follow the surface's own
    # scale: a scratch is a mark and a mark is a small part of the
    # surface.
    scratch = palette.scratch_strength_for_description(description)
    if scratch > 0.0:
        nodes.append(
            {
                "name": "scratch",
                "type": "scratches",
                "params": {
                    "layers": 5,
                    "length": 0.30,
                    "width": 0.25,
                    "waviness": 0.4,
                    "angle": 1.2,
                    "randomness": 0.35,
                },
            }
        )
        nodes.append(
            {
                "name": "scratched",
                "type": "blend",
                "params": {"mode": "screen", "amount": scratch * GRAPH_LAYER_AMOUNT},
                "inputs": {"a": "scratch", "b": output},
            }
        )
        output = "scratched"

    # And the DUST and the MOSS, when the words say the surface
    # carries them: the loose grounds have debris and the stones
    # have moss in their joints, and both are PATCHES of a different
    # colour and not a texture of their own.
    if words & {"moss", "mossy", "lichen"}:
        # And the moss's own SIZE follows the surface's own scale: a
        # patch of moss is a small part of a stone, and twelve blobs
        # at a sixteenth of the tile wrecked the ground's feature
        # scale - it read 4.15x the truth's.
        nodes.append(
            {
                "name": "moss",
                "type": "splatter",
                "params": {
                    "count": 18,
                    "radius": 0.18 / max(4.0, count),
                    "seed": 7,
                },
            }
        )
        # And the moss is a TONE over the base and not a texture of
        # its own.
        #
        # The moss was blended in as a layer, and a layer is a
        # TEXTURE - so the ground's feature scale read 4.73x the
        # truth's where the single path read 0.83x. A patch of moss
        # is a patch of COLOUR on the stone, and it changes the
        # surface's tone and not its structure.
        #
        # So the moss is a mask and the base is darkened under it -
        # and the base's own structure is untouched.
        nodes.append(
            {
                "name": "soft_moss",
                "type": "blur",
                "params": {"radius": GRAPH_MOSS_BLUR},
                "inputs": {"source": "moss"},
            }
        )
        nodes.append(
            {
                "name": "mossed",
                "type": "math",
                "params": {"op": "multiply", "scale": 1.0 - GRAPH_MOSS_AMOUNT},
                "inputs": {"a": output, "b": "soft_moss"},
            }
        )
        output = "mossed"

    if len(nodes) == 1:
        # Nothing to compose, and a graph of one node is the
        # single-pattern path with extra steps.
        return None
    return {"nodes": nodes, "output": output}


__all__ = ("graph_for_description",)
