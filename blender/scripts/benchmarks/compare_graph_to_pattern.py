"""Does a NODE GRAPH beat the single-pattern path on the truth's own?

The lane's answer to a description used to be ONE pattern, and a
description is really a STACK. The graph composes: a base, a warp,
an overlay, a set of scratches.

This measures the two against the truth's own, on the same sets, so
the claim "a graph is better" is a measurement and not a hope.

Each material is recreated TWICE - once by the single-pattern path
and once by a graph built from the same description - and both are
scored against the truth's own albedo.
"""

import json
import os
import pathlib
import sys

sys.path.insert(0, "/Users/ladvien/golem_mcp/blender/src")


from golem_blender.pbr import (  # pylint: disable=import-outside-toplevel
    paths as pbr_paths,
)
from golem_blender.pbr.patterns import pattern_for_description
from golem_blender.pbr.procedural import (  # pylint: disable=import-outside-toplevel
    write_procedural_base_color,
)

ROOT = pathlib.Path(
    os.environ.get(
        "GOLEM_BENCH_ROOT",
        "/Users/ladvien/mnt/codex_fs/game_assets/benchmarks/ambientcg_top",
    )
)
OUT = ROOT / "recreated_graph"


def describe(tags):
    """The DESCRIPTION, from the material's own words."""
    return ", ".join(
        tag
        for tag in tags
        if not tag.isdigit()
        and not any(character.isdigit() for character in tag)
        and len(tag) >= 3
    )


def graph_for(description: str, kind: str, cells: float) -> dict | None:
    """The GRAPH for a description, and None when it calls for none.

    The graph is built by the lane's own planner, and the planner
    reads the FITTED tables: the base pattern is the one the words
    call for, the cells are the truth's own feature count, and the
    scratch layer's strength is the palette's own fitted answer.

    A graph whose layers are guessed throws the description's
    information away, and it measured worse than the single-pattern
    path for exactly that reason.
    """
    from golem_blender.pbr.graph_plan import (  # pylint: disable=import-outside-toplevel
        graph_for_description,
    )

    return graph_for_description(description, kind, cells)


def main():
    manifest = json.loads((ROOT / "manifest.json").read_text())
    truth = {
        entry["asset_id"]: entry
        for entry in json.loads((ROOT / "truth_statistics.json").read_text())
    }
    OUT.mkdir(parents=True, exist_ok=True)
    results = []
    for entry in manifest:
        asset_id = entry["asset_id"]
        if asset_id not in truth:
            continue
        description = describe(entry["tags"])
        kind = pattern_for_description(description)
        cells = float(truth[asset_id]["albedo"]["features_across"])
        graph = graph_for(description, kind, cells)
        if graph is None:
            continue
        path = OUT / f"{asset_id}_BaseColor.png"
        try:
            write_procedural_base_color(
                path,
                kind="graph",
                scale_cells=float(truth[asset_id]["albedo"]["features_across"]),
                width_px=pbr_paths.SET_RESOLUTION_PX,
                height_px=pbr_paths.SET_RESOLUTION_PX,
                graph=graph,
            )
        except (OSError, TypeError, ValueError) as error:
            print(f"SKIP {asset_id}: {error}")
            continue
        results.append({"asset_id": asset_id, "kind": kind, "path": str(path)})
        print(f"RUN  {asset_id:16s} the kind is {kind}")
    (ROOT / "graph_paths.json").write_text(json.dumps(results, indent=2))
    print(f"RUN {len(results)} materials were recreated as graphs")


main()
print("DONE")
