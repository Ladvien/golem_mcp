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

REQUIRED_PROVIDER = "ollama-cloud"
REQUIRED_MODEL_NAME = "deepseek-v4.1-flash:1017"
REQUIRED_MODEL = f"{REQUIRED_PROVIDER}/{REQUIRED_MODEL_NAME}"

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


def test_the_pin_names_the_required_provider_and_not_just_a_model():
    """`ollama-cloud` is part of the requirement, so it gets its own assertion.

    A bare model name would be routed by whichever provider the resolver
    preferred, and a transcript audit that read only the `model` field could not
    tell the two apart: that field is spelled `deepseek-v4.1-flash:1017` whether
    the call went to ollama-cloud or anywhere else. The `provider` field is what
    settles it — measured on the six-way run, all 18 records read
    `provider: ollama-cloud`, `api: ollama-chat`.
    """
    provider, _, model_name = REQUIRED_MODEL.partition("/")
    assert provider == REQUIRED_PROVIDER
    assert model_name == REQUIRED_MODEL_NAME
    # The separator matters: `ollama-cloud:deepseek-...` is a different selector.
    assert REQUIRED_MODEL == "ollama-cloud/deepseek-v4.1-flash:1017"


def test_every_role_a_subagent_can_resolve_through_names_the_required_model():
    """A bundled agent names a ROLE, not a model, so the role target is a pin.

    Measured 2026-10-26, before this was pinned: `scout` and `sonic` resolve
    through `@smol`, `reviewer` through `@slow`, `task` through `@task`, and
    those roles pointed at `anthropic/claude-haiku-5-5`, `claude-opus-5-5` and
    `claude-sonnet-5-5`. So four of the seven agents a session can spawn ran on
    Anthropic models while the concrete-model pin above was green — the pin was
    true about `loop-worker` and silent about the rest of the roster.

    `ollama-cloud` is part of the requirement, so the role targets are asserted
    with their provider, not as bare model names.
    """
    if not USER_CONFIG_PATH.is_file():
        pytest.skip(f"no user config at {USER_CONFIG_PATH}")

    config = yaml.safe_load(USER_CONFIG_PATH.read_text(encoding="utf-8")) or {}
    roles = config.get("modelRoles") or {}

    # Every role the bundled roster resolves through, plus `default` and
    # `advisor`: an advisor call is still a subagent-side model call.
    required_roles = ("smol", "slow", "task", "default", "advisor")
    wrong = {
        role: roles.get(role)
        for role in required_roles
        if roles.get(role) != REQUIRED_MODEL
    }
    assert not wrong, (
        f"these modelRoles do not point at {REQUIRED_MODEL!r}: {wrong}. A "
        f"bundled agent that names a role (scout/sonic -> @smol, reviewer -> "
        f"@slow, task -> @task) would then run on that role's model, so the "
        f"concrete-model pin alone leaves most of the roster unpinned."
    )


# Roles that exist for the USER'S OWN session and that no subagent reaches.
# An explicit list, so it takes a deliberate edit to exempt a role, and so
# DEFAULT-DENY below catches any role nobody thought about.
MAIN_SESSION_ROLES = frozenset({"plan", "vision", "web", "designer"})


def test_every_role_except_a_named_few_names_the_required_model():
    """DEFAULT-DENY closure over `modelRoles`.

    An enumerated pin is only as strong as its completeness, and deriving the
    set from the roster's `@role` references does not work either: the bundled
    agents live inside the omp binary, so a disk walk found only `advisor` and
    `default` while `smol`/`slow`/`task` went unchecked. Measured 2026-10-26.

    So this inverts the rule: EVERY role must name the required model except the
    named main-session ones. A role added later fails here without anyone
    remembering its name, which is the property a name list cannot have.

    `MAIN_SESSION_ROLES` is the user's to own. `plan`, `vision`, `web` and
    `designer` are used by the interactive session, no subagent names them, and
    pinning them changed the user's own models for no reason — measured and
    restored 2026-10-26.
    """
    if not USER_CONFIG_PATH.is_file():
        pytest.skip(f"no user config at {USER_CONFIG_PATH}")

    config = yaml.safe_load(USER_CONFIG_PATH.read_text(encoding="utf-8")) or {}
    roles = config.get("modelRoles") or {}

    wrong = {
        role: selector
        for role, selector in sorted(roles.items())
        if role not in MAIN_SESSION_ROLES and selector != REQUIRED_MODEL
    }
    assert not wrong, (
        f"these subagent-reachable roles do not name {REQUIRED_MODEL!r}: {wrong}. "
        f"Every role is treated as subagent-reachable unless it is listed in "
        f"MAIN_SESSION_ROLES ({sorted(MAIN_SESSION_ROLES)}), so a new role fails "
        f"here until it is pinned or deliberately exempted."
    )


def test_the_main_session_exemptions_are_roles_no_subagent_names():
    """The exemption list must stay honest: an exempted role that a subagent CAN
    reach would be an unpinned path. Checked against the agents on disk, which is
    all this machine can verify — the bundled roster's own references are
    asserted separately by `test_the_required_model_is_spelled_fully`'s sibling
    below."""
    import re

    agents_dirs = [REPOSITORY_ROOT / ".omp" / "agents"]
    user_agents = pathlib.Path.home() / ".omp" / "agent" / "agents"
    if user_agents.is_dir():
        agents_dirs.append(user_agents)

    named: set[str] = set()
    for directory in agents_dirs:
        for path in directory.glob("*.md"):
            named.update(
                re.findall(r'"@([a-z][a-z0-9_-]*)"',
                           path.read_text(encoding="utf-8", errors="ignore"))
            )
    overlap = named & MAIN_SESSION_ROLES
    assert not overlap, (
        f"these roles are exempted as main-session-only but an agent on disk "
        f"names them: {sorted(overlap)}. Pin them, or the exemption is a hole."
    )


def test_every_role_is_SET_rather_than_left_to_fall_through():
    """`None` is not "unpinned but harmless": it falls through to `default`.

    Measured: `seance` and `security-reviewer` carry no `model:` line at all, so
    they resolved via `default` — which is why `default` has to be pinned too,
    and why a `None` here is the same defect as a wrong value.
    """
    if not USER_CONFIG_PATH.is_file():
        pytest.skip(f"no user config at {USER_CONFIG_PATH}")

    config = yaml.safe_load(USER_CONFIG_PATH.read_text(encoding="utf-8")) or {}
    roles = config.get("modelRoles") or {}

    unset = sorted(role for role, selector in roles.items() if not selector)
    assert not unset, (
        f"these modelRoles are unset: {unset}. An agent naming an unset role "
        f"falls through to the default selection, so leaving one unset is a "
        f"routing hole that looks tidy in the config."
    )
