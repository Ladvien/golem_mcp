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
        nodes.append(
            {
                "name": "moss",
                "type": "splatter",
                "params": {"count": 12, "radius": 0.16, "seed": 7},
            }
        )
        nodes.append(
            {
                "name": "mossed",
                "type": "blend",
                "params": {"mode": "multiply", "amount": GRAPH_LAYER_AMOUNT},
                "inputs": {"a": "moss", "b": output},
            }
        )
        output = "mossed"

    if len(nodes) == 1:
        # Nothing to compose, and a graph of one node is the
        # single-pattern path with extra steps.
        return None
    return {"nodes": nodes, "output": output}


__all__ = ("graph_for_description",)
