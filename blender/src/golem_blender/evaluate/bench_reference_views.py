"""The four reference views a 3DCodeBench instance is grounded on.

3DCodeBench's image-to-3D track (DOI 10.48550/arXiv.2606.01057) hands the
model the reference rendered from four turntable azimuths — 45, 135, 225
and 315 degrees, frames 5/15/25/35 of a 40-frame turn — and its README
puts them at `benchmark/categories/<inst>/images/Image_0{05,15,25,35}.png`.
`scripts/bench_render_references.py` renders them with the bench's own
`core/render.py`; `scripts/run_3dcode_instance.py` hands them to the
agent as reference images. ONE definition of which files those are, so
the renderer, the runner and the chain's pre-flight cannot disagree.

Measured 2026-09-11 (dev sweep, three runs): an eye given these four
views states the object's middle and thin extents with 0.224 and 0.488
log2 error against 0.455 and 0.675 for the assets the writer builds from
text — the reason the views are worth carrying. A missing view is an
error, never a silent fall-back to text: RESP (DOI 10.48550/arXiv.2604.11082)
measures an irrelevant reference as worse than none, and an instance run
without its views would be scored beside instances run with them.
"""

from __future__ import annotations

from pathlib import Path

# In render order; frame index times 9 degrees is the azimuth.
REFERENCE_VIEW_FILENAMES = (
    "Image_005.png",
    "Image_015.png",
    "Image_025.png",
    "Image_035.png",
)
# Where the bench README keeps them, relative to the bench root.
REFERENCE_IMAGES_SUBDIR = Path("benchmark") / "categories"


def reference_view_paths(images_root: Path, instance: str) -> tuple[Path, ...]:
    """The instance's four views under `images_root/<instance>/images/`,
    in render order. Raises `FileNotFoundError` naming every absent one."""
    directory = Path(images_root) / instance / "images"
    paths = tuple(directory / name for name in REFERENCE_VIEW_FILENAMES)
    missing = [str(path) for path in paths if not path.exists()]
    if missing:
        raise FileNotFoundError(
            f"{instance}: reference views missing: {missing}; render them with "
            f"scripts/bench_render_references.py"
        )
    return paths
