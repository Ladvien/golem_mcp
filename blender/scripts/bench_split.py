#!/usr/bin/env python3
"""Split 3DCodeBench into a frozen HOLDOUT set and a DEV set.

The frozen 20 (`<bench-root>/instances_v1.txt`) is the only list this repo
has ever used, and every iteration so far was both tuned and measured on
it. That is the validation->test generalization gap MLE-bench measures at
9-13% (DOI 10.48550/arXiv.2507.02554): selecting a policy by the score of
the set you report inflates the reported score. So the frozen 20 becomes a
HOLDOUT, touched only to confirm a pre-registered prediction, and every
other instance with a baked reference GLB becomes DEV, where policies are
derived.

Emits three files (default `bench_sets/`):

    instances_holdout.txt    the frozen 20, verbatim
    instances_dev_all.txt    every other instance whose reference baked OK
    instances_dev_sweep.txt  a deterministic 12-instance stride over dev,
                             the only dev instances that cost live rolls

The bench checkout stays read-only: `--instances-file` consumers take
absolute paths, so these lists live in this repo.

    python3 scripts/bench_split.py --bench-root /Users/ladvien/3dcodebench
"""

import argparse
import json
import sys
from pathlib import Path

DEFAULT_BENCH_ROOT = "/Users/ladvien/3dcodebench"
DEFAULT_OUT_DIR = "bench_sets"

EXPECTED_HOLDOUT_COUNT = 20  # instances_v1.txt, frozen since v1
EXPECTED_DEV_COUNT = 145  # 165 baked references - 20 holdout
DEV_SWEEP_COUNT = 12  # live dev rolls: ~12 x 340 s ~= 70 min

# Pinned so a changed bake set is loud instead of silent: the Step-2
# policy measurement and its 0.0311 constant are derived over exactly the
# dev set this stride comes from.
EXPECTED_DEV_SWEEP = (
    "Auger_seed0",
    "Book_seed0",
    "CeilingClassicLamp_seed0",
    "DeskLamp_seed0",
    "FruitCoconutgreen_seed0",
    "KitchenIsland_seed0",
    "Lid_seed0",
    "Oven_seed0",
    "Pot_seed0",
    "SingleCabinet_seed0",
    "TableCoral_seed0",
    "Wineglass_seed0",
)


def parse_arguments(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bench-root",
        default=DEFAULT_BENCH_ROOT,
        help="3DCodeBench checkout (holds data/ and metrics/)",
    )
    parser.add_argument(
        "--out-dir",
        default=DEFAULT_OUT_DIR,
        help="Directory the three lists are written to",
    )
    return parser.parse_args(argv)


def reference_baked_ok(instance_dir: Path) -> bool:
    """Did the benchmark's own ground-truth factory bake a reference GLB?

    `metrics/shape_chamfer.py` needs `data/<inst>/glb/<inst>.glb`; 47 of
    the 212 ground-truth scripts fail on Blender 5.2 (node-socket index
    drift, missing scipy/shapely), so an unbaked instance is unscoreable
    through no fault of the model under test and must not enter a split.
    """
    log_path = instance_dir / "glb" / "export_log.json"
    if not log_path.exists():
        return False
    try:
        status = json.loads(log_path.read_text()).get("status")
    except (json.JSONDecodeError, OSError):
        return False
    if status != "OK":
        return False
    return (instance_dir / "glb" / f"{instance_dir.name}.glb").exists()


def dev_sweep_indices(dev_count: int, sweep_count: int) -> list[int]:
    """Even stride over the sorted dev list, endpoints included."""
    if dev_count < sweep_count:
        raise SystemExit(f"dev set of {dev_count} cannot yield {sweep_count}")
    return [
        round(index * (dev_count - 1) / (sweep_count - 1))
        for index in range(sweep_count)
    ]


def main(argv) -> int:
    arguments = parse_arguments(argv)
    bench_root = Path(arguments.bench_root).resolve()
    data_root = bench_root / "data"
    if not data_root.is_dir():
        raise SystemExit(f"No data dir under {bench_root}")

    holdout_path = bench_root / "instances_v1.txt"
    if not holdout_path.exists():
        raise SystemExit(f"No frozen instance list at {holdout_path}")
    holdout = [
        line.strip() for line in holdout_path.read_text().splitlines() if line.strip()
    ]
    if len(holdout) != EXPECTED_HOLDOUT_COUNT:
        raise SystemExit(
            f"{holdout_path} holds {len(holdout)} names, "
            f"expected {EXPECTED_HOLDOUT_COUNT}"
        )
    if len(set(holdout)) != len(holdout):
        raise SystemExit(f"{holdout_path} holds duplicate names")

    holdout_set = set(holdout)
    baked = sorted(
        directory.name
        for directory in data_root.iterdir()
        if directory.is_dir() and reference_baked_ok(directory)
    )
    missing_holdout = [name for name in holdout if name not in set(baked)]
    if missing_holdout:
        raise SystemExit(
            f"holdout instances have no baked reference: {missing_holdout}"
        )

    dev_all = [name for name in baked if name not in holdout_set]
    if len(dev_all) != EXPECTED_DEV_COUNT:
        raise SystemExit(
            f"dev set is {len(dev_all)} instances, expected "
            f"{EXPECTED_DEV_COUNT}; the bake set moved, so the pinned "
            "orientation-policy numbers must be re-derived"
        )

    indices = dev_sweep_indices(len(dev_all), DEV_SWEEP_COUNT)
    dev_sweep = [dev_all[index] for index in indices]
    if tuple(dev_sweep) != EXPECTED_DEV_SWEEP:
        raise SystemExit(
            "dev sweep stride no longer matches the pinned list:\n"
            f"  computed: {dev_sweep}\n  pinned:   {list(EXPECTED_DEV_SWEEP)}"
        )

    # Every emitted name must be fully usable: reference GLB (chamfer) and
    # brief (the runner's task text).
    for name in dev_all + holdout:
        instance_dir = data_root / name
        for required in (
            (instance_dir / "glb" / f"{name}.glb"),
            (instance_dir / "prompt_description.txt"),
        ):
            if not required.exists():
                raise SystemExit(f"missing {required}")
    if holdout_set & set(dev_all):
        raise SystemExit("holdout and dev overlap")

    out_dir = Path(arguments.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written = {
        "instances_holdout.txt": holdout,
        "instances_dev_all.txt": dev_all,
        "instances_dev_sweep.txt": dev_sweep,
    }
    for filename, names in written.items():
        (out_dir / filename).write_text("\n".join(names) + "\n")
        print(f"{out_dir / filename}: {len(names)}")
    print(f"dev sweep stride indices over {len(dev_all)}: {indices}")
    print("dev sweep: " + " ".join(dev_sweep))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
