"""Benchmark analysis thresholds shared by the 3DCodeBench scripts.

Stdlib-only on purpose: `scripts/compare_3dcode_rolls.py` runs under a bare
`python3` (no numpy, no trimesh), while `scripts/diagnose_3dcode.py` and
`scripts/shape_error_decompose.py` run under the benchmark's own venv. A
threshold quoted by both must therefore live in a module neither venv can
break, and be defined exactly once.
"""

ORIENT_ARTIFACT_THRESHOLD = 0.02  # Δ_orient at/above which an instance's
# score is an orientation artifact rather
# than shape error; also the per-instance
# across-roll range above which a roll
# delta is indistinguishable from noise

# --- The pre-registered ranking rule -------------------------------------
#
# Ranking is on F-SCORE at a fixed distance threshold, pose-normalised the
# same way cd_pca is (best alignment over the 24-rotation PCA frame).
#
# Why not Chamfer. Tatarchenko, Richter, Ranftl, Li, Koltun & Brox, "What
# Do Single-View 3D Reconstruction Networks Learn?", CVPR 2019
# (DOI 10.1109/cvpr.2019.00352): under CD and IoU, retrieval and
# classification baselines are statistically indistinguishable from
# reconstruction — the metrics rank category priors, not surface
# agreement — and F-score at a threshold is the discriminative axis.
# Measured here (OT-33, 2026-09-10, disclosed rolls 1 and 2, 18 instances
# each): cd_pca ranked roll 1 better (0.0270 vs 0.0289) while F@0.05
# ranked roll 2 better (0.4060 vs 0.4454); the mean absolute rank shift
# between the two metrics across roll 1's instances was 2.78 places of 18.
# The proportion oracle moved cd_pca by only 0.0043, and the orientation
# term sat at the holdout's documented floor. So CD could not see what
# the writer changed.
#
# Registered BEFORE any roll was ranked on it (the OT-33 pre-registration
# in docs/2026-09-06-bench-panel-preregistration.md), for the next roll
# set onward; rolls 1-3 of the disclosed surface stay on cd_pca as their
# own pre-registration said, and none of them reached 20/20 anyway.
# Thresholds were fixed a priori; re-choosing the one that flatters a
# result after reading it is selection on the test set.
FSCORE_THRESHOLDS = (0.01, 0.02, 0.05, 0.10)
PRIMARY_FSCORE_THRESHOLD = 0.05


def metric_column(name: str, threshold: float) -> str:
    """The column a thresholded metric is written under, e.g. `fscore_005`.

    The threshold is in the name so a later re-choice is visible in every
    table that carries it, not hidden behind a constant.
    """
    return f"{name}_{round(threshold * 100):03d}"


RANKING_METRIC = metric_column("fscore", PRIMARY_FSCORE_THRESHOLD)
# Reported on every panel, never ranked on. Precision and recall say
# "invented surface" versus "missed surface", which F folds into one
# number; cd_pca stays so the earlier hypotheses (H2') remain readable;
# cd_yawmin is the scorer's own number; delta_orient is the pose axis and
# is owned by the orientation work, not by a shape candidate.
REPORTED_METRICS = (
    metric_column("precision", PRIMARY_FSCORE_THRESHOLD),
    metric_column("recall", PRIMARY_FSCORE_THRESHOLD),
    "cd_pca",
    "cd_yawmin",
    "delta_orient",
)
# Which way is better, per metric family. F-score, precision and recall
# are fractions of surface in agreement (1 is perfect); every Chamfer
# axis is a distance (0 is perfect). Every consumer that sorts, signs a
# delta or names a target reads THIS, so two files cannot disagree about
# what "better" means.
HIGHER_IS_BETTER_PREFIXES = ("fscore_", "precision_", "recall_")


def higher_is_better(metric: str) -> bool:
    return metric.startswith(HIGHER_IS_BETTER_PREFIXES)


def worsening_sign(metric: str) -> int:
    """Multiply `candidate - baseline` by this and a positive number is a
    regression whichever way the metric points."""
    return -1 if higher_is_better(metric) else 1


# A candidate is a MEAN over at least this many paired rolls of the same
# instance set: 3 rolls take the SE of the 20-mean from 0.0018 to 0.0010.
MINIMUM_PAIRED_ROLLS = 3
# A roll with fewer instances is reported but cannot be ranked: the frozen
# set is 20 and an unpaired subset is not comparable.
MINIMUM_INSTANCES_FOR_RANKING = 20
# The target is RELATIVE, so it moves with the incumbent instead of being
# a literal below the instrument's resolution. 15% of a 0.0252 incumbent
# is 0.0038 = 2.1 sigma at one roll, 3.7 at three.
TARGET_RELATIVE_IMPROVEMENT = 0.15
# One-sided, on the ranking metric's paired standard error.
REGRESSION_SIGMA = 2.0

# --- Proportion headroom under F@0.05 (2026-09-11) -------------------------
#
# How much of the ranking metric a PERFECT proportion stage could buy: the
# generated cloud is rescaled per axis, in the PCA-aligned frame cd_pca
# and F@0.05 are measured in, onto the reference's extents, then
# re-normalised and re-aligned and F@0.05 read again. An upper bound (it
# knows the reference), not a claim about any writer. Measured over 160
# instance rolls of the frozen holdout (six incumbent rolls plus
# disclosed2 rolls 1 and 3): 0.4531 -> 0.7017, +0.2486, against a
# proportion headroom of 0.0099 under cd_pca. The two instruments
# disagree because F@0.05 counts surface within 0.05 of the unit sphere
# and a 2x-wide jar puts none of its wall there, while Chamfer averages
# the miss. The per-instance error is a BIAS — the same instance is
# wrong the same way in all eight rolls — on the middle and thin axes;
# the largest axis is right everywhere.
# Extents are read at these percentiles, not the min/max: one stray
# vertex on a 8192-point sample would otherwise set an axis.
PROPORTION_EXTENT_PERCENTILES = (1.0, 99.0)
# Two components touch when their bounding boxes overlap within this
# fraction of the object's largest extent; a component touching nothing
# is floating. Measured the same day: 0 of 160 generated assets had one,
# so 3DCodeBench's floating-parts bottleneck (DOI 10.48550/arXiv.2606.01057,
# Finding 1) is not this harness's — the per-object component budget and
# the pair gate absorb it upstream.
COMPONENT_TOUCH_TOLERANCE_FRACTION = 1e-3
# References are Infinigen exports with up to ~40k components; above this
# count the pairwise touch test is skipped and the count alone reported.
PAIRWISE_COMPONENT_LIMIT = 3000
