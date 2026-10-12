"""Build the same thing twice in two fresh Blenders; require one digest.

    make test-repro ARGS="--builder barrel"
    make test-repro ARGS="--iteration 10"

`tests/blender/test_rebuild_in_session.py` already rebuilds after a
scene wipe, which is fast and catches residue. It cannot catch
process-global state that survives a wipe — a seeded RNG, a cached
module, an operator preference, a hash-ordered set iterated into
geometry — because none of that lives in `bpy.data`. So the in-session
test is the tripwire and this is the pin: one child Blender per build,
each with a DIFFERENT `PYTHONHASHSEED`, which is the Reproducible
Builds practice of varying the environment between builds rather than
repeating it.

The comparison is exact string equality on quantized semantic
components (`blended.evaluate.digest`), reported per component so a
failure names the drifted datablock.

Two measured details about driving Blender this way:

* macOS installs no `blender` on PATH, and the binary must be exec'd by
  its real in-bundle path — a symlink breaks bundle-relative resource
  lookup — so the default is the full `Blender.app` path and `BLENDER`
  overrides it.
* Blender writes its version banner AND a `Blender quit` line to STDOUT
  after the script's own output, so the child's digest cannot be read
  as "the last stdout line". It is announced with a marker prefix and
  the parent reads the last marked line.
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent


def venv_site_packages() -> Path:
    candidates = sorted(
        (REPOSITORY_ROOT / ".venv" / "lib").glob("python3.*/site-packages")
    )
    if not candidates:
        raise SystemExit(f"No .venv under {REPOSITORY_ROOT}.")
    return candidates[-1]


sys.path.insert(0, str(venv_site_packages()))
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))
os.chdir(REPOSITORY_ROOT)

BLENDER_BINARY = os.environ.get(
    "BLENDER", "/Applications/Blender.app/Contents/MacOS/Blender"
)

# One build per child; a barrel with two boolean unions takes seconds,
# and a replayed agent iteration is the slow case. A child that has not
# printed its digest by then is a failure, not a longer wait.
CHILD_TIMEOUT_S = 600

# Two builds, two hash seeds. Identical environments would let a build
# that iterates a hash-ordered set into geometry pass.
HASH_SEEDS = ("0", "1")

DIGEST_MARKER = "REBUILD_TWICE_DIGEST "

BUILDER_NAMES = ("barrel", "crate", "pallet")

DEFAULT_LOG = "_evaluate/iterations.jsonl"


def parse_arguments(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--builder",
        choices=BUILDER_NAMES,
        help="build this builder with default parameters",
    )
    parser.add_argument(
        "--iteration",
        type=int,
        help="replay this agent-authored iteration from the log instead",
    )
    parser.add_argument("--log", default=DEFAULT_LOG)
    parser.add_argument(
        "--print-digest",
        action="store_true",
        help="child mode: build once in THIS process and print the digest",
    )
    arguments = parser.parse_args(argv)
    if bool(arguments.builder) == bool(arguments.iteration):
        parser.error("pass exactly one of --builder or --iteration")
    return arguments


def child_arguments(arguments) -> list[str]:
    """The argv the child gets: the parent's own selection, plus the
    mode flag that makes it print instead of spawn."""
    if arguments.builder:
        return ["--builder", arguments.builder, "--print-digest"]
    return [
        "--iteration",
        str(arguments.iteration),
        "--log",
        arguments.log,
        "--print-digest",
    ]


def build_builder(builder_name: str):
    """One build of the named builder with DEFAULT parameters."""
    from blended.builders import (
        BarrelBuilder,
        BarrelParameters,
        CrateBuilder,
        CrateParameters,
        PalletBuilder,
        PalletParameters,
    )

    pairs = {
        "barrel": (BarrelBuilder, BarrelParameters),
        "crate": (CrateBuilder, CrateParameters),
        "pallet": (PalletBuilder, PalletParameters),
    }
    builder_class, parameters_class = pairs[builder_name]
    return builder_class(parameters_class()).build()


def digest_in_this_process(arguments) -> dict:
    """Build once into a reset scene and digest the result.

    The builder path digests the built object; the replay path digests
    the whole scene, because an agent-authored build decides for itself
    how many objects it leaves behind.
    """
    from blended.evaluate.digest import object_digest, scene_digest
    from blended.reset import reset_scene

    reset_scene()

    if arguments.builder:
        return object_digest(build_builder(arguments.builder))

    from blended.evaluate.replay import load_record, sources_from
    from blended.run.executor import run_source_in_process

    record = load_record(Path(arguments.log), arguments.iteration)
    sources = sources_from(record)
    if not sources:
        raise SystemExit(
            f"iteration {arguments.iteration} in {arguments.log} recorded no "
            f"run_python source: there is nothing to rebuild"
        )
    for index, source in enumerate(sources, 1):
        result = run_source_in_process(source)
        # stderr, so stdout stays parseable by the parent.
        print(
            f"[child] chunk {index}/{len(sources)}: {'ok' if result.ok else 'FAILED'}",
            file=sys.stderr,
            flush=True,
        )
        if not result.ok:
            # A failed replay chunk must fail loudly, carrying the
            # traceback: a child that crashes identically twice would
            # otherwise print "reproducible … 0 components" and exit 0.
            raise SystemExit(
                f"chunk {index}/{len(sources)} failed during replay:\n"
                f"{result.traceback_text or result.summary()}"
            )
    return scene_digest()


def run_child(arguments, hash_seed: str) -> dict:
    """One fresh Blender, one build, one digest."""
    command = [
        BLENDER_BINARY,
        "--background",
        "--factory-startup",
        # Blender initialises CPython with an ISOLATED config by default
        # (bpy_interface.cc: py_use_system_env = false), which sets
        # use_environment = 0 and use_hash_seed = 0, so PYTHONHASHSEED is
        # never read and each child gets a random seed.  --python-use-system-env
        # switches to the system config, honouring PYTHONHASHSEED (and
        # PYTHONPATH); the child env below scrubs PYTHONPATH so the venv
        # site-packages inserted at module level are the only path source.
        "--python-use-system-env",
        "--python",
        str(Path(__file__).resolve()),
        "--",
        *child_arguments(arguments),
    ]
    environment = dict(os.environ)
    environment["PYTHONHASHSEED"] = hash_seed
    # --python-use-system-env honours PYTHONPATH; scrub it so the parent's
    # environment cannot shadow the venv site-packages this script inserts.
    environment.pop("PYTHONPATH", None)
    print(f"[repro] PYTHONHASHSEED={hash_seed}: {BLENDER_BINARY}", flush=True)
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=CHILD_TIMEOUT_S,
            env=environment,
            cwd=REPOSITORY_ROOT,
            check=False,  # a non-zero child is reported with its output
        )
    except subprocess.TimeoutExpired as expired:
        raise SystemExit(
            f"child with PYTHONHASHSEED={hash_seed} did not finish in "
            f"{CHILD_TIMEOUT_S} s.\n"
            f"--- stdout ---\n{expired.stdout or ''}\n"
            f"--- stderr ---\n{expired.stderr or ''}"
        ) from expired

    marked = [
        line for line in completed.stdout.splitlines() if line.startswith(DIGEST_MARKER)
    ]
    if completed.returncode != 0 or not marked:
        raise SystemExit(
            f"child with PYTHONHASHSEED={hash_seed} exited "
            f"{completed.returncode} without a digest.\n"
            f"--- stdout ---\n{completed.stdout}\n"
            f"--- stderr ---\n{completed.stderr}"
        )
    digest = json.loads(marked[-1][len(DIGEST_MARKER) :])
    if not digest.get("components"):
        # An empty scene has 0 components and compare_digests({}, {})
        # returns [] — so two children that both crashed identically
        # would print "is reproducible … 0 components" and exit 0.
        raise SystemExit(
            f"child with PYTHONHASHSEED={hash_seed} produced an empty "
            f"digest (0 components) — the build left nothing behind:\n"
            f"--- stdout ---\n{completed.stdout}\n"
            f"--- stderr ---\n{completed.stderr}"
        )
    return digest


def main(argv) -> int:
    arguments = parse_arguments(argv)

    if arguments.print_digest:
        digest = digest_in_this_process(arguments)
        print(DIGEST_MARKER + json.dumps(digest, sort_keys=True), flush=True)
        return 0

    from blended.evaluate.digest import compare_digests

    digests = [run_child(arguments, hash_seed) for hash_seed in HASH_SEEDS]
    problems = compare_digests(digests[0], digests[1])
    if problems:
        print(
            f"[repro] NOT reproducible: {len(problems)} component difference(s)",
            flush=True,
        )
        for problem in problems:
            print(f"   - {problem}", flush=True)
        return 1

    subject = arguments.builder or f"iteration {arguments.iteration}"
    print(
        f"[repro] {subject} is reproducible across "
        f"PYTHONHASHSEED {HASH_SEEDS[0]} and {HASH_SEEDS[1]}: "
        f"{len(digests[0]['components'])} components, overall "
        f"{digests[0]['overall']} == {digests[1]['overall']}",
        flush=True,
    )
    return 0


extra_arguments = (
    sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else sys.argv[1:]
)
raise SystemExit(main(extra_arguments))
