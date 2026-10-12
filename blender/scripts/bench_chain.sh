#!/bin/zsh
# One benchmark roll, end to end, the only order that yields a rankable
# number (OT-21): sweep -> bake -> score -> diagnose. The scorers run
# only if the bake left every instance with its render log and GLB.
#
#   WORKTREE=$(scripts/freeze_worktree.sh HEAD) \
#   MODEL_DIR=blended-deepseek-v4-pro-ops-roll1 \
#   WRITER=deepseek-v4-pro:cloud EYE=kimi-k2.7-code:cloud \
#   scripts/bench_chain.sh
#
# REFERENCE_IMAGES=<root> runs the image-to-3D track: every instance's
# four views <root>/<inst>/images/Image_0{05,15,25,35}.png ride the task
# as reference images (rendered by scripts/bench_render_references.py).
# Checked for EVERY instance before the sweep starts, because an
# instance run without its views beside instances run with them is a
# different experiment scored as the same one.
#
# WORKTREE is a FROZEN checkout (git worktree) so the main tree can move
# while a roll runs; the diagnose json lands in the main tree's
# outputs/bench/ for bench_panel.py. Make it with
# `scripts/freeze_worktree.sh <commit>`, which keeps one freeze per
# commit under one parent and reuses it — six ad-hoc worktrees
# accumulated in a single evening (2026-09-10, 839 MB) before that
# existed. `scripts/freeze_worktree.sh --prune` removes the idle ones;
# this script does NOT remove its own, because a roll set runs several
# chains from the same freeze.
# TOOLS (default WORKTREE) is the tree whose bake and diagnose scripts run:
# an incumbent worktree from before OT-21 has no bake script, and both
# scripts read bench result directories without importing either harness.
set -u
: ${WORKTREE:?frozen worktree path}
: ${MODEL_DIR:?results/text_to_3D_agent/<dir>}
: ${WRITER:?writer model id}
: ${EYE:=}
: ${BENCH_ROOT:=/Users/ladvien/3dcodebench}
: ${INSTANCES:=$WORKTREE/bench_sets/instances_holdout.txt}
: ${OUT:=/Users/ladvien/blended/outputs/bench}
: ${TIMEOUT:=1500}
: ${TOOLS:=$WORKTREE}   # the tree whose bake/diagnose scripts run (an incumbent tree predates them)
: ${FREEZE_ROOT:=$HOME/blended-worktrees}
: ${REFERENCE_IMAGES:=}   # the image-to-3D track's view root, or text-only when empty

# The roll runs from a FREEZE NAMED BY ITS COMMIT, or not at all (OT-37).
# Measured 2026-09-11: OT-27's roll 3 ran from a hand-made worktree at
# c6e4bfc and lost 7 of 20 instances to HTTP 502 with zero retries — the
# bounded retry had landed in 179ab11, after the freeze, and the plan
# that launched the roll assumed it was in the tree. A freeze under
# $FREEZE_ROOT carries its commit in its path (scripts/freeze_worktree.sh),
# so the question "which fixes did this roll carry" is answered by `ls`;
# the commit is also written as the first line of the chain log.
case "$WORKTREE" in
  "$FREEZE_ROOT"/*) ;;
  *)
    echo "bench_chain: WORKTREE=$WORKTREE is not a freeze under $FREEZE_ROOT;" \
         "make one with scripts/freeze_worktree.sh <commit> so the roll's commit is in its path" >&2
    exit 2
    ;;
esac
FROZEN_COMMIT=$(git -C "$WORKTREE" rev-parse HEAD 2>/dev/null) || {
  echo "bench_chain: $WORKTREE is not a git checkout" >&2; exit 2; }
REF_ARGS=()
if [ -n "$REFERENCE_IMAGES" ]; then
  MISSING_VIEWS=""
  for INSTANCE in $(cat "$INSTANCES"); do
    for VIEW in Image_005.png Image_015.png Image_025.png Image_035.png; do
      [ -f "$REFERENCE_IMAGES/$INSTANCE/images/$VIEW" ] || MISSING_VIEWS="$MISSING_VIEWS $INSTANCE/images/$VIEW"
    done
  done
  if [ -n "$MISSING_VIEWS" ]; then
    echo "bench_chain: REFERENCE_IMAGES=$REFERENCE_IMAGES lacks reference views:$MISSING_VIEWS;" \
         "render them with scripts/bench_render_references.py before the roll" >&2
    exit 2
  fi
  REF_ARGS=(--reference-images-root "$REFERENCE_IMAGES")
fi
L=$OUT/logs; mkdir -p $L
RESULTS=$BENCH_ROOT/results/text_to_3D_agent
say() { echo "[chain] $MODEL_DIR $1 $(date)" >> $L/chain_$MODEL_DIR.log; }

say "frozen commit $FROZEN_COMMIT at $WORKTREE"
[ -n "$REFERENCE_IMAGES" ] && say "image-to-3D track: reference views from $REFERENCE_IMAGES"
say "sweep start"
EYE_ARGS=(); [ -n "$EYE" ] && EYE_ARGS=(--vision-model "$EYE")
$WORKTREE/.venv/bin/python $WORKTREE/scripts/sweep_3dcode.py --bench-root $BENCH_ROOT \
  --instances-file $INSTANCES --model "$WRITER" "${EYE_ARGS[@]}" "${REF_ARGS[@]}" --timeout $TIMEOUT \
  --model-dir $MODEL_DIR > $L/${MODEL_DIR}_sweep.log 2>&1
say "sweep exit $?"

$TOOLS/.venv/bin/python $TOOLS/scripts/bake_3dcode.py --bench-root $BENCH_ROOT \
  --model-dir $MODEL_DIR > $L/${MODEL_DIR}_bake.log 2>&1
BAKE=$?
say "bake exit $BAKE"
if [ $BAKE -ne 0 ]; then say "NOT SCORED: bake left artifacts missing"; exit $BAKE; fi

(cd $BENCH_ROOT && .venv/bin/python metrics/executability.py --model $MODEL_DIR --results-root $RESULTS > $L/${MODEL_DIR}_exec.log 2>&1)
(cd $BENCH_ROOT && .venv/bin/python metrics/shape_chamfer.py --model $MODEL_DIR --results-root $RESULTS > $L/${MODEL_DIR}_chamfer.log 2>&1)
(cd $TOOLS && $BENCH_ROOT/.venv/bin/python scripts/diagnose_3dcode.py --bench-root $BENCH_ROOT --model-dir $MODEL_DIR \
  --instances-file $INSTANCES --out $OUT/diagnose_$MODEL_DIR.md --json $OUT/diagnose_$MODEL_DIR.json > $L/${MODEL_DIR}_diagnose.log 2>&1)
say "scored exit $?"
