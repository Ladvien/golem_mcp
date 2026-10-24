"""The build-loop's worker agents stay pinned to the required model.

Why this is a test and not a note in a doc: the fan-out runs six agents whose
work is judged by evidence each one reports about itself, and a child that
quietly ran on another model would still produce a confident-looking report.
The pin therefore has to be checked by something that fails, not by a reader
who remembers.

Two layers carry the pin, and the test asserts both:

1. ``task.agentModelOverrides`` in the user config — the layer that takes
   precedence OVER agent frontmatter, so it survives a stale agent file or an
   agent that declares no model at all.
2. the tracked agent definition's ``model:`` line, the per-agent default.

Measured 2026-10-26 on the six-way run: every child resolved exactly one model,
``resolvedModelIsFallback: false``, so no retry had silently switched it.
"""

from __future__ import annotations

import pathlib

import pytest
import yaml

REQUIRED_MODEL = "ollama-cloud/deepseek-v4.1-flash:1017"

REPOSITORY_ROOT = pathlib.Path(__file__).resolve().parents[1]
TRACKED_AGENT_PATH = REPOSITORY_ROOT / ".omp" / "agents" / "loop-worker.md"

# Every agent the loop spawns. `task` and `sonic` are the bundled general
# workers a task item falls back to when an agent is named loosely.
PINNED_AGENT_NAMES = ("loop-worker", "task", "sonic")

USER_CONFIG_PATH = pathlib.Path.home() / ".omp" / "agent" / "config.yml"


def _frontmatter(path: pathlib.Path) -> dict:
    text = path.read_text(encoding="utf-8")
    _, _, remainder = text.partition("---")
    block, _, _ = remainder.partition("---")
    return yaml.safe_load(block) or {}


def test_the_tracked_agent_declares_the_required_model():
    """The repo's own agent file carries the pin, so it travels with the code."""
    assert TRACKED_AGENT_PATH.is_file(), (
        f"{TRACKED_AGENT_PATH} is missing: the loop-worker definition is what "
        f"pins each child's model, and task cannot discover an agent that is "
        f"not on disk"
    )
    assert _frontmatter(TRACKED_AGENT_PATH).get("model") == REQUIRED_MODEL


def test_the_override_layer_pins_every_loop_worker():
    """The config override OUTRANKS frontmatter, so it is the layer that holds
    when an agent file drifts. Its absence is a silent routing gap."""
    if not USER_CONFIG_PATH.is_file():
        pytest.skip(f"no user config at {USER_CONFIG_PATH}")

    config = yaml.safe_load(USER_CONFIG_PATH.read_text(encoding="utf-8")) or {}
    overrides = (config.get("task") or {}).get("agentModelOverrides") or {}

    wrong = {
        name: overrides.get(name)
        for name in PINNED_AGENT_NAMES
        if overrides.get(name) != REQUIRED_MODEL
    }
    assert not wrong, (
        "these agents are not pinned to the required model by "
        f"task.agentModelOverrides: {wrong}. Expected each to be "
        f"{REQUIRED_MODEL!r}. Without the override, an agent file's own "
        "`model:` line is the only pin, and that is the layer a stale or "
        "hand-edited file defeats."
    )


def test_the_required_model_is_spelled_fully():
    """A truncated selector would still route (the resolver completes it), but
    the pin would then be ambiguous in a log or a transcript audit."""
    provider, _, name = REQUIRED_MODEL.partition("/")
    assert provider and name and ":" in name, REQUIRED_MODEL
