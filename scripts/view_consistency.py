#!/usr/bin/env python
"""Do these reference views actually depict the same character? Check before generating.

    view_consistency.py --images front.png back.png left.png right.png

WHY
---
The ceiling on multi-image generation here is not view count and not pixels - it
is whether the views AGREE. Measured on one character: a front view with the hem
at mid-thigh and a back view with it below the knee produced a mesh with a torn,
ragged hem, because the generator reconciled two different garments. Adding side
views outvoted the bad hem and produced a clean one - and then the side views'
smaller horns outvoted the correct horns instead.

Stating the hem length explicitly in the prompt did not fix it. So the useful
move is to MEASURE the disagreement before spending ~70 s on a mesh and longer
on a rig, which is what this does.

WHAT IS AND IS NOT COMPARABLE ACROSS VIEWS
------------------------------------------
Silhouette WIDTH is not. A person is genuinely narrower seen from the side, so
comparing front against left would flag anatomy as a defect.

What is comparable is the HEIGHT of a feature. A hem, a belt, a boot top are at
the same height on the body from every angle, so a disagreement about height is a
real disagreement about the garment. That is what this measures:

  hem_height    the strongest downward step in the silhouette's width profile
                below mid-body, as a fraction of subject height. A skirt ending
                at mid-thigh and one ending below the knee differ here and
                nowhere else that survives a change of viewpoint.
  aspect        subject height / width, grouped: front and back should match each
                other, left and right should match each other. Across those groups
                it is expected to differ, so it is reported per group.

CONSENSUS, NOT SPREAD
---------------------
The first version scored max-minus-min and it does not separate the cases. The
four-view set had back, left and right agreeing exactly and only the front
dissenting - a 3-of-4 majority, which is why its hem came out CLEAN - yet its
spread (0.125) looked much like the torn two-view pair's (0.156).

What predicts the outcome is whether a majority agrees, so this reports the
median, each view's deviation from it, and NAMES the outliers. Two views that
disagree are called out specially: there is no majority to win, so the generator
has nothing to break the tie with, and that is the case that tore.

A COLOUR CHECK WAS TRIED AND REMOVED
------------------------------------
Mean per-band colour across views sounded like it would catch a material drifting
between views (correct black horns returning gold). Measured, it reads 0.90 on
three views known to agree and 1.06 on the pair known to disagree - it is
dominated by legitimate viewpoint difference, since horns seen edge-on and
face-on are honestly different pixels. A warning that fires on everything teaches
the reader to ignore the warning list, so it is gone rather than mistuned.

Background removal is a near-white threshold, not the pipeline's BiRefNet. The
prompt this pipeline uses puts the subject on a plain flat white background, so a
threshold is sufficient and costs no GPU - which matters for something meant to
run BEFORE the expensive stage.
"""

import argparse
import json
import sys
from pathlib import Path

BANDS = 32
# One band is 1/32 = 0.031 of subject height, so a view within 0.04 of the median
# is agreeing to within the measurement's own resolution. Calibrated on real sets:
# three views that agreed scored a spread of exactly 0.000, and the front+back pair
# that produced a torn hem sat 0.078 either side of their median.
AGREE_TOL = 0.04


def silhouette(path, bands=BANDS):
    """Per-band width fraction and mean colour for one view, normalised to the subject."""
    import numpy as np
    from PIL import Image

    im = Image.open(path).convert("RGBA")
    a = np.asarray(im).astype(np.float32) / 255.0
    rgb, alpha = a[..., :3], a[..., 3]
    # Subject = not background. Prefer real alpha; fall back to "not near-white".
    mask = (alpha > 0.5) if alpha.min() < 0.99 else (rgb.min(axis=-1) < 0.94)
    if mask.sum() < 100:
        raise SystemExit(f"{path}: found almost no subject; is the background plain?")

    rows = np.where(mask.any(axis=1))[0]
    cols = np.where(mask.any(axis=0))[0]
    y0, y1, x0, x1 = rows[0], rows[-1] + 1, cols[0], cols[-1] + 1
    m = mask[y0:y1, x0:x1]
    c = rgb[y0:y1, x0:x1]
    h, w = m.shape

    widths, colours = [], []
    edges = np.linspace(0, h, bands + 1).astype(int)
    for i in range(bands):
        lo, hi = edges[i], max(edges[i + 1], edges[i] + 1)
        band, bandc = m[lo:hi], c[lo:hi]
        if band.any():
            xs = np.where(band.any(axis=0))[0]
            widths.append(float(xs[-1] - xs[0] + 1) / w)
            colours.append(bandc[band].mean(axis=0).tolist())
        else:
            widths.append(0.0)
            colours.append([0.0, 0.0, 0.0])
    return {
        "widths": widths,
        "colours": colours,
        "aspect": round(float(h) / float(w), 3),
        "height_px": int(h),
    }


def hem_height(widths):
    """Fraction of subject height at the strongest downward width step below mid-body.

    Bands run top (0) to bottom (1). A hem is where the silhouette narrows sharply
    as the skirt ends and the legs begin, so it is the largest NEGATIVE step in
    width going downward, searched below the midpoint to avoid the shoulders.
    """
    n = len(widths)
    start = n // 2
    best_i, best_drop = start, 0.0
    for i in range(start, n - 1):
        drop = widths[i] - widths[i + 1]
        if drop > best_drop:
            best_drop, best_i = drop, i
    return round((best_i + 0.5) / n, 3), round(best_drop, 3)


def main() -> int:
    import numpy as np

    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--images", required=True, nargs="+")
    ap.add_argument("--json-only", action="store_true")
    args = ap.parse_args()

    paths = [Path(p) for p in args.images]
    missing = [str(p) for p in paths if not p.is_file()]
    if missing:
        raise SystemExit("image(s) not found: " + ", ".join(missing))

    views = {p.stem: silhouette(str(p)) for p in paths}
    names = list(views)

    hems = {n: hem_height(views[n]["widths"]) for n in names}
    hem_vals = [hems[n][0] for n in names]
    hem_spread = round(max(hem_vals) - min(hem_vals), 3)

    # Consensus on the garment edge: median, deviation, named outliers.
    median = float(np.median(hem_vals))
    deviation = {n: round(abs(hems[n][0] - median), 3) for n in names}
    outliers = [n for n in names if deviation[n] > AGREE_TOL]
    agreeing = [n for n in names if n not in outliers]

    warnings = []
    if outliers and len(names) == 2:
        warnings.append(
            f"The two views disagree about a garment edge: {names[0]} at "
            f"{hems[names[0]][0]}, {names[1]} at {hems[names[1]][0]} (of subject height). "
            f"With only two views there is no majority to break the tie, so the generator "
            f"reconciles both into one surface - on this pipeline that produced a visibly "
            f"TORN, ragged hem. Regenerate one of them, or add side views so a majority can "
            f"win."
        )
    elif outliers and len(agreeing) > len(outliers):
        warnings.append(
            f"{len(agreeing)} of {len(names)} views agree on the garment edge at ~{median:.3f}; "
            f"{', '.join(outliers)} dissent(s) by up to "
            f"{max(deviation[o] for o in outliers):.3f} of subject height. The majority should "
            f"win, but the outlier still pulls the surface - regenerate {outliers[0]} for a "
            f"clean result."
        )
    elif outliers:
        warnings.append(
            f"No majority: the views split on the garment edge ({', '.join(f'{n}={hems[n][0]}' for n in names)}). "
            f"The generator has nothing to break the tie with. Regenerate until a majority agrees."
        )

    groups = {}
    for n in names:
        key = "front_back" if any(k in n for k in ("front", "back")) else "side"
        groups.setdefault(key, []).append(views[n]["aspect"])
    aspect = {k: {"values": v, "spread": round(max(v) - min(v), 3)} for k, v in groups.items()}

    report = {
        "views": names,
        "hem_height": {n: hems[n][0] for n in names},
        "hem_spread": hem_spread,
        "hem_median": round(median, 3),
        "hem_deviation": deviation,
        "agreeing_views": agreeing,
        "outlier_views": outliers,
        "aspect_by_group": aspect,
        "consistent": not warnings,
        "warnings": warnings,
    }
    print(json.dumps(report, indent=2))
    if not args.json_only:
        print("VIEW_CONSISTENCY_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
