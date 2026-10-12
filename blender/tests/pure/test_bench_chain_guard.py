"""A benchmark roll runs from a freeze named by its commit, or not at all.

OT-37. Measured 2026-09-11: OT-27's cloud roll 3 ran from a hand-made
worktree at `c6e4bfc` and lost 7 of 20 instances to HTTP 502 with zero
retries, because the bounded retry had landed in `179ab11` — after the
freeze — and the plan that launched the roll assumed the fix was in the
tree. `scripts/freeze_worktree.sh` names every freeze by its commit under
one parent, so a roll that runs from there carries its commit in its
path. `scripts/bench_chain.sh` refuses anything else before it touches
the bench, and writes the frozen commit as the first line of its log.

The script is zsh, run as a subprocess; nothing here needs Blender or the
bench checkout, because the refusal happens before either is reached.
"""

import os
import subprocess
from pathlib import Path

import pytest

CHAIN_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "bench_chain.sh"
REQUIRED_ENVIRONMENT = {
    "MODEL_DIR": "guard-test-roll",
    "WRITER": "no-such-writer",
}
REFUSED_EXIT_CODE = 2
# Every variable bench_chain.sh reads: a developer shell that exports one
# (REFERENCE_IMAGES, FREEZE_ROOT, ...) must not change what a test measures.
SCRIPT_VARIABLES = (
    "WORKTREE",
    "MODEL_DIR",
    "WRITER",
    "EYE",
    "BENCH_ROOT",
    "INSTANCES",
    "OUT",
    "TIMEOUT",
    "TOOLS",
    "FREEZE_ROOT",
    "REFERENCE_IMAGES",
)


def _inherited_environment() -> dict:
    return {
        name: value
        for name, value in os.environ.items()
        if name not in SCRIPT_VARIABLES
    }


def run_chain(
    worktree: Path, freeze_root: Path, out: Path
) -> subprocess.CompletedProcess:
    environment = {
        **_inherited_environment(),
        **REQUIRED_ENVIRONMENT,
        "WORKTREE": str(worktree),
        "FREEZE_ROOT": str(freeze_root),
        "OUT": str(out),
        # A bench root that does not exist: if the guard let the roll
        # through, the sweep would fail on it instead of doing anything.
        "BENCH_ROOT": str(out / "no-bench-here"),
    }
    return subprocess.run(
        ["zsh", str(CHAIN_SCRIPT)],
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_a_worktree_outside_the_freeze_root_is_refused_before_anything_runs(tmp_path):
    freeze_root = tmp_path / "freezes"
    freeze_root.mkdir()
    elsewhere = tmp_path / "blended-bench-v4"
    elsewhere.mkdir()
    out = tmp_path / "out"

    completed = run_chain(elsewhere, freeze_root, out)

    assert completed.returncode == REFUSED_EXIT_CODE, completed.stderr
    assert "is not a freeze under" in completed.stderr
    assert "freeze_worktree.sh" in completed.stderr
    # Refused BEFORE the log directory exists: no side effect at all.
    assert not out.exists()


def test_a_freeze_that_is_not_a_git_checkout_is_refused(tmp_path):
    freeze_root = tmp_path / "freezes"
    fake_freeze = freeze_root / "deadbeef"
    fake_freeze.mkdir(parents=True)
    out = tmp_path / "out"

    completed = run_chain(fake_freeze, freeze_root, out)

    assert completed.returncode == REFUSED_EXIT_CODE, completed.stderr
    assert "is not a git checkout" in completed.stderr
    assert not out.exists()


def test_a_real_freeze_logs_its_commit_first(tmp_path):
    """Past the guard, the first line of the chain log names the commit,
    so a roll's tree is on record even after the freeze is pruned."""
    freeze_root = tmp_path / "freezes"
    freeze = freeze_root / "abc1234"
    freeze.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(freeze)], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(freeze),
            "-c",
            "user.email=t@t",
            "-c",
            "user.name=t",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "frozen",
        ],
        check=True,
    )
    commit = subprocess.run(
        ["git", "-C", str(freeze), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    out = tmp_path / "out"

    completed = run_chain(freeze, freeze_root, out)

    # The sweep then fails (no venv, no bench) — that is fine; the guard
    # is what is under test, and it let a real freeze through.
    assert "is not a freeze under" not in completed.stderr
    assert "is not a git checkout" not in completed.stderr
    chain_log = out / "logs" / f"chain_{REQUIRED_ENVIRONMENT['MODEL_DIR']}.log"
    assert chain_log.exists()
    first_line = chain_log.read_text().splitlines()[0]
    assert f"frozen commit {commit} at {freeze}" in first_line


def test_a_reference_root_missing_a_view_is_refused_before_the_sweep(tmp_path):
    """The image-to-3D track needs every instance's four views. Measured
    2026-09-11: an eye given them reads proportions at 0.224/0.488 log2
    error against 0.455/0.675 built from text, so a roll where one
    instance silently ran text-only would mix two experiments in one
    number. Refused before the sweep, and the missing file is named."""
    freeze_root = tmp_path / "freezes"
    freeze = freeze_root / "abc1234"
    freeze.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(freeze)], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(freeze),
            "-c",
            "user.email=t@t",
            "-c",
            "user.name=t",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "frozen",
        ],
        check=True,
    )
    instances = tmp_path / "instances.txt"
    instances.write_text("Jar_seed0\n")
    views = tmp_path / "categories" / "Jar_seed0" / "images"
    views.mkdir(parents=True)
    for name in ("Image_005.png", "Image_015.png", "Image_025.png"):
        (views / name).write_bytes(b"png")  # Image_035.png is absent
    out = tmp_path / "out"
    environment = {
        **_inherited_environment(),
        **REQUIRED_ENVIRONMENT,
        "WORKTREE": str(freeze),
        "FREEZE_ROOT": str(freeze_root),
        "OUT": str(out),
        "BENCH_ROOT": str(out / "no-bench-here"),
        "INSTANCES": str(instances),
        "REFERENCE_IMAGES": str(tmp_path / "categories"),
    }
    completed = subprocess.run(
        ["zsh", str(CHAIN_SCRIPT)],
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode == REFUSED_EXIT_CODE, completed.stderr
    assert "Jar_seed0/images/Image_035.png" in completed.stderr
    assert "bench_render_references" in completed.stderr
    assert not out.exists()  # before the log directory, before the sweep


@pytest.mark.parametrize("missing", ["WORKTREE", "MODEL_DIR", "WRITER"])
def test_a_missing_required_variable_is_refused(tmp_path, missing):
    environment = {
        **_inherited_environment(),
        **REQUIRED_ENVIRONMENT,
        "WORKTREE": str(tmp_path),
        "OUT": str(tmp_path / "out"),
    }
    environment.pop(missing)
    completed = subprocess.run(
        ["zsh", str(CHAIN_SCRIPT)],
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode != 0
    assert missing in completed.stderr
