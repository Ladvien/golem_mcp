#!/bin/zsh
# One frozen checkout per COMMIT, in one place, cleaned up when idle.
#
# Why this exists. A benchmark roll takes ~3 h and starts a fresh Blender
# per instance that imports the source tree AT THAT MOMENT, so editing
# src/ mid-roll changes what later instances run. The fix is to run each
# roll from a frozen git worktree. The fix's own failure mode is sprawl:
# on 2026-09-10 six worktrees accumulated in one evening — blended-bench,
# -v2, -v4, -old, -incumbent, -iter — 839 MB, of which ~700 MB was dead,
# because each was made ad hoc, named after its purpose rather than its
# commit, scattered across $HOME, and never removed.
#
# Three rules, each aimed at one of those causes:
#   * ONE PARENT.   Everything lives under $FREEZE_ROOT.
#   * NAMED BY COMMIT.  Two freezes of the same commit are the same
#     directory, so asking twice costs nothing and cannot fork.
#   * PRUNED.  `--prune` removes every freeze no live process is inside.
#
#   scripts/freeze_worktree.sh HEAD          # path on stdout, reused if it exists
#   scripts/freeze_worktree.sh --list        # every freeze, with in-use marked
#   scripts/freeze_worktree.sh --prune       # remove the idle ones
#
# The path is the only thing printed on stdout, so a caller can do:
#   WORKTREE=$(scripts/freeze_worktree.sh HEAD) scripts/bench_chain.sh
set -u

: ${FREEZE_ROOT:=$HOME/blended-worktrees}
REPOSITORY=${REPOSITORY:-$(cd "$(dirname "$0")/.." && pwd)}

# A freeze is "in use" when any process has a file open under it, or its
# cwd there. Checked with lsof rather than pgrep: a Blender started from
# the freeze may not carry the path in its command line, and deleting a
# tree out from under a running roll would void the roll silently.
#
# Test the OUTPUT, never the exit status: lsof exits non-zero whenever it
# hits any unreadable path, even while printing real results. Measured
# 2026-09-10 — the first draft read `lsof ... > /dev/null 2>&1` as the
# condition, so a tree with 12 open files under it reported idle and was
# deleted. A probe has to be shown to fire before it is trusted.
in_use() {
  [ -n "$(lsof +D "$1" 2>/dev/null)" ]
}

note() { echo "$@" >&2; }

case "${1:-}" in
  --list)
    [ -d "$FREEZE_ROOT" ] || { note "no freezes under $FREEZE_ROOT"; exit 0; }
    for tree in "$FREEZE_ROOT"/*(/N); do
      if in_use "$tree"; then state="IN USE"; else state="idle"; fi
      note "$(du -sh "$tree" 2>/dev/null | cut -f1)\t$state\t$tree"
    done
    exit 0
    ;;
  --prune)
    [ -d "$FREEZE_ROOT" ] || { note "no freezes under $FREEZE_ROOT"; exit 0; }
    removed=0
    for tree in "$FREEZE_ROOT"/*(/N); do
      if in_use "$tree"; then
        note "keeping  $tree (in use)"
        continue
      fi
      git -C "$REPOSITORY" worktree remove --force "$tree" && { note "removed  $tree"; removed=$((removed+1)) }
    done
    git -C "$REPOSITORY" worktree prune
    note "pruned $removed freeze(s)"
    exit 0
    ;;
  "")
    note "usage: $0 <commit-ish> | --list | --prune"
    exit 2
    ;;
esac

COMMIT=$(git -C "$REPOSITORY" rev-parse --short "$1") || exit 2
TREE=$FREEZE_ROOT/$COMMIT

if [ -d "$TREE" ]; then
  # Same commit, same directory: reuse rather than fork. This is the rule
  # that stops the sprawl, because a second roll at the same commit is a
  # second roll, not a second tree.
  note "reusing $TREE (already frozen at $COMMIT)"
  echo "$TREE"
  exit 0
fi

mkdir -p "$FREEZE_ROOT"
git -C "$REPOSITORY" worktree add -q --detach "$TREE" "$COMMIT" || exit 2
note "froze $COMMIT at $TREE; installing its venv"
# Its own venv: the tree's scripts import from its own src/, and a shared
# venv would defeat the freeze the first time a dependency moved.
# A failed sync must not leave $TREE behind: the reuse branch above trusts
# any directory it finds, so a venv-less tree would be handed out as frozen.
(cd "$TREE" && uv sync -q) || {
  git -C "$REPOSITORY" worktree remove --force "$TREE"
  note "uv sync FAILED in $TREE; the half-built freeze was removed"
  exit 2
}
note "ready"
echo "$TREE"
