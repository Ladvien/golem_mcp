"""Capability modules are text that can only make things worse or better.

SkillsBench measured curated skills at +16.2 pp overall — and 16 of its
84 tasks at a NEGATIVE delta, worst case -39.3 pp
(10.48550/arXiv.2602.12670). So a module is a change with a sign, and
these tests guard the two properties that decide which sign it gets:
how many load at once, and how long each one is.

They also pin the property that makes every earlier convergence score
still valid — that a session built with no lane renders exactly the text
that was scored, with no skill in it.
"""

import hashlib

import pytest

from blended.agent import prompt_templates, skill_modules

JINJA_DELIMITERS = ("{{", "}}", "{%", "%}", "{#", "#}")


def test_the_registry_is_disciplined():
    """One template, one hypothesis, one lane and evidence per module."""
    assert skill_modules.validate_modules() == []


def test_registry_and_disk_agree():
    on_disk = set(prompt_templates.available_skills())
    registered = {entry.name for entry in skill_modules.SKILL_MODULES}
    assert registered == on_disk, (
        f"registry and prompts/skills/ disagree: registered="
        f"{sorted(registered)}, on disk={sorted(on_disk)}"
    )


def test_no_body_contains_a_jinja_delimiter():
    for entry in skill_modules.SKILL_MODULES:
        for delimiter in JINJA_DELIMITERS:
            assert delimiter not in entry.body, (
                f"{entry.name} contains {delimiter!r}: Jinja would try to "
                f"interpret it and the module would lose text"
            )


@pytest.mark.parametrize("lane", sorted(skill_modules.LANE_MODULES))
def test_no_lane_loads_more_than_the_cap(lane):
    """2-3 focused modules measured +18.6 pp; 4+ collapsed to +5.9 pp."""
    selected = skill_modules.select_modules(lane)
    assert len(selected) <= skill_modules.MAXIMUM_MODULES_LOADED, (
        f"lane {lane!r} loads {len(selected)}"
    )


@pytest.mark.parametrize("name", [entry.name for entry in skill_modules.SKILL_MODULES])
def test_each_module_stays_compact(name):
    """Comprehensive skill documents measured -2.9 pp; compact ones +18.8."""
    body = skill_modules.get_module(name).body
    assert len(body.splitlines()) <= skill_modules.MAXIMUM_MODULE_LINES


def test_the_template_file_is_the_body_byte_for_byte():
    """No preamble, no front matter, no normalization on the way in."""
    for entry in skill_modules.SKILL_MODULES:
        path = prompt_templates.template_path(
            f"{prompt_templates.SKILL_SUBDIRECTORY}/{entry.name}"
        )
        raw = path.read_text(encoding="utf-8")
        assert raw == entry.body, path.name
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
        assert entry.identity.endswith(digest)


def test_an_unknown_lane_raises_instead_of_loading_nothing():
    """A silent empty selection would score a turn against text that
    never ran — the failure `get_revision` already refuses."""
    with pytest.raises(skill_modules.UnknownLane):
        skill_modules.select_modules("no_such_lane")


def test_an_unknown_module_raises():
    with pytest.raises(skill_modules.UnknownSkillModule):
        skill_modules.get_module("no_such_module")


def test_the_default_session_carries_no_skill():
    """The pinned prompt is the pinned prompt.

    Self-authored skills measured -1.3 pp where curated ones measured
    +16.2. Until a human has reviewed a module and a run has scored it,
    a session built with no lane must render the converged text and
    nothing else, or every earlier measurement silently changes meaning.
    """
    from blended.agent.system_prompt import build_system_prompt

    default = build_system_prompt()
    for entry in skill_modules.SKILL_MODULES:
        assert entry.body not in default, (
            f"{entry.name} leaked into the default prompt: the pinned "
            f"revision is no longer the text a plain session runs"
        )


@pytest.mark.parametrize("lane", sorted(skill_modules.LANE_MODULES))
def test_a_lane_loads_exactly_its_modules(lane):
    from blended.agent.system_prompt import build_system_prompt

    prompt = build_system_prompt(lane=lane)
    selected = {entry.name for entry in skill_modules.select_modules(lane)}
    for entry in skill_modules.SKILL_MODULES:
        present = entry.body.rstrip("\n") in prompt
        assert present is (entry.name in selected), (
            f"lane {lane!r}: {entry.name} present={present} "
            f"selected={entry.name in selected}"
        )
