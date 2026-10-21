"""The benchmark: recreate a real PBR set from a TEXT DESCRIPTION.

The ground truth is ambientcg's own maps - CC0, photoreal, and the
maps the lane produces: albedo, normal, roughness, AO.

The RECREATION gets ONLY the text. The description is built from
the material's own tags - "bricks", "weathered", "red" - which is
what a person would write to describe the surface. It does NOT get
the ground truth's pixels, and it does not get a reference image of
it: the point is to recreate the material from WORDS.

The measures, per map:

  - the ALBEDO. The recreation cannot match a photograph's pixels,
    so the measure is whether the two AGREE as surfaces: the same
    brightness, the same colour balance, the same contrast, the
    same feature scale. A recreation that is a pale grey blur of a
    red brick has failed, and a mean-squared-error against the
    photograph would say it passed - so the measures are the
    STATISTICS a viewer reads.
  - the NORMAL MAP. The ground truth's normal and the recreation's
    normal encode the same SURFACE, so the measure is the ANGLE
    between them: the mean angle between the encoded normals. That
    is the number that says whether the relief matches.
  - the ORM. The AO channel and the roughness channel, compared the
    same way: the mean absolute difference, and the correlation.

The correlation matters as much as the difference: two maps can
differ a lot and still agree on the surface's structure.

This module holds the measures. The runner is separate.
"""

from __future__ import annotations

from pathlib import Path


def load_normal_map(path: Path):
    """A normal map as a (height, width, 3) array of UNIT vectors.

    The normal map is TANGENT space: X and Y are the surface's
    slope and Z is up. The values are encoded 0..1 for -1..1, so
    they are decoded and then normalised, because a map's length is
    not exactly one and the angle between two vectors needs it.
    """
    import numpy

    from golem_blender.ops._image_loading import load_image

    image = load_image(path)
    width, height = image.size
    pixels = numpy.empty(width * height * 4, dtype=numpy.float32)
    image.pixels.foreach_get(pixels)
    array = pixels.reshape((height, width, 4))
    vector = array[:, :, :3] * 2.0 - 1.0
    length = numpy.sqrt((vector * vector).sum(axis=2, keepdims=True))
    length[length == 0.0] = 1.0
    return vector / length


def normal_agreement(truth: Path, recreated: Path) -> dict:
    """How well two normal maps agree, in DEGREES.

    The mean angle between the two maps' normals: 0 means the same
    surface, 90 means unrelated, 180 means opposite. The comparison
    is on a grid, because the two maps may be different sizes.
    """
    import numpy

    a = load_normal_map(truth)
    b = load_normal_map(recreated)
    rows = min(a.shape[0], b.shape[0])
    columns = min(a.shape[1], b.shape[1])
    a = a[:rows, :columns]
    b = b[:rows, :columns]
    dot = (a * b).sum(axis=2)
    dot = numpy.clip(dot, -1.0, 1.0)
    angles = numpy.degrees(numpy.arccos(dot))
    return {
        "mean_angle_deg": float(angles.mean()),
        "median_angle_deg": float(numpy.median(angles)),
        "p90_angle_deg": float(numpy.percentile(angles, 90)),
        "flat_agreement_deg": float(angles[numpy.abs(a[:, :, 2]) > 0.99].mean())
        if (numpy.abs(a[:, :, 2]) > 0.99).any()
        else float("nan"),
    }


def channel_agreement(truth: Path, recreated: Path, channel: int) -> dict:
    """How well two maps' CHANNELS agree."""
    import numpy

    from golem_blender.ops._image_loading import load_image

    def read(path):
        image = load_image(path)
        width, height = image.size
        pixels = numpy.empty(width * height * 4, dtype=numpy.float32)
        image.pixels.foreach_get(pixels)
        return pixels.reshape((height, width, 4))[:, :, channel]

    a = read(truth)
    b = read(recreated)
    rows = min(a.shape[0], b.shape[0])
    columns = min(a.shape[1], b.shape[1])
    a = a[:rows, :columns].ravel()
    b = b[:rows, :columns].ravel()
    difference = numpy.abs(a - b)
    # The correlation says whether the two agree on the STRUCTURE,
    # which the difference alone does not: two maps can differ a lot
    # and still be the same surface.
    a_centred = a - a.mean()
    b_centred = b - b.mean()
    denominator = numpy.sqrt(
        (a_centred * a_centred).sum() * (b_centred * b_centred).sum()
    )
    correlation = (
        float((a_centred * b_centred).sum() / denominator) if denominator else 0.0
    )
    return {
        "mean_abs_difference": float(difference.mean()),
        "correlation": correlation,
        "truth_mean": float(a.mean()),
        "recreated_mean": float(b.mean()),
    }


def albedo_statistics(path: Path) -> dict:
    """The statistics a VIEWER reads from a colour map.

    The mean is the surface's brightness, the spread is its
    contrast, and the feature scale is how big its details are. A
    recreation that is a blur of the truth has the right brightness
    and the wrong contrast, and one that is a different material has
    the wrong colour balance.
    """
    import numpy

    from golem_blender.ops._image_loading import load_image

    image = load_image(path)
    width, height = image.size
    pixels = numpy.empty(width * height * 4, dtype=numpy.float32)
    image.pixels.foreach_get(pixels)
    array = pixels.reshape((height, width, 4))
    luma = 0.2126 * array[:, :, 0] + 0.7152 * array[:, :, 1] + 0.0722 * array[:, :, 2]
    # The feature scale: the autocorrelation's first zero crossing.
    #
    # It is computed over the WHOLE IMAGE, not one row. A single row
    # crosses the features at whatever angle they happen to run, and
    # the crossing depends on the CONTRAST: measured, the same wood
    # pattern read 93.09 features with a wide ramp and 341.33 with a
    # narrow one, because the autocorrelation's noise floor moved and
    # the first crossing moved with it. Averaging the rows'
    # autocorrelations is the average of the pattern's structure, and
    # it does not depend on how much contrast there is.
    rows = luma - luma.mean(axis=1, keepdims=True)
    correlation = numpy.zeros(width)
    for row in rows[:: max(1, height // 64)]:
        correlation += numpy.correlate(row, row, mode="full")[width - 1 :]
    if correlation[0]:
        correlation = correlation / correlation[0]
    below = numpy.where(correlation < 0.0)[0]
    period = int(below[0]) if len(below) else width
    return {
        "luma_mean": float(luma.mean()),
        "luma_std": float(luma.std()),
        "luma_p10": float(numpy.percentile(luma, 10)),
        "luma_p90": float(numpy.percentile(luma, 90)),
        "red_mean": float(array[:, :, 0].mean()),
        "green_mean": float(array[:, :, 1].mean()),
        "blue_mean": float(array[:, :, 2].mean()),
        "feature_period_px": period,
        "features_across": width / period if period else 0.0,
    }


def compare_albedo(truth: Path, recreated: Path) -> dict:
    """How well the recreation AGREES with the truth as a surface."""
    a = albedo_statistics(truth)
    b = albedo_statistics(recreated)
    return {
        "truth": a,
        "recreated": b,
        "brightness_ratio": b["luma_mean"] / a["luma_mean"] if a["luma_mean"] else 0.0,
        "contrast_ratio": b["luma_std"] / a["luma_std"] if a["luma_std"] else 0.0,
        "scale_ratio": (
            b["features_across"] / a["features_across"] if a["features_across"] else 0.0
        ),
        "colour_balance_error": (
            (b["red_mean"] - a["red_mean"]) ** 2
            + (b["green_mean"] - a["green_mean"]) ** 2
            + (b["blue_mean"] - a["blue_mean"]) ** 2
        )
        ** 0.5,
    }


__all__ = (
    "albedo_statistics",
    "channel_agreement",
    "compare_albedo",
    "load_normal_map",
    "normal_agreement",
)
