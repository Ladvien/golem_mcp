"""The prompt is an artifact people read, so its file layer is tested.

Moving the bodies out of Python and into `prompts/*.md.j2` bought
reviewability and gave up a guard: the old chained-`.replace()` build
raised when an anchor moved, which made a silent rewrite impossible by
construction. These tests are what replaces it.
"""

import hashlib
from pathlib import Path

import pytest

from blended import manifest
from blended.agent import prompt_templates, prompt_versions, system_prompt
from blended.drift import catalog

# The identity of the revision the convergence loop signed off, read from
# the artifact the pin itself writes (`scripts/pin_revision.py`) rather
# than hardcoded here. The guarantee is unchanged — any later edit to a
# pinned `.j2` changes the identity while this file does not, so the test
# goes red — but pinning no longer requires hand-editing a test.
PINNED_IDENTITY_PATH = (
    Path(__file__).resolve().parents[2] / "_evaluate" / "golden" / "pinned_identity.txt"
)

# The fingerprint of the prompt the model ACTUALLY reads. Its sibling
# above covers the working agreement alone; this covers the whole assembly.
PINNED_ASSEMBLED_FINGERPRINT_PATH = (
    Path(__file__).resolve().parents[2]
    / "_evaluate"
    / "golden"
    / "pinned_assembled_fingerprint.txt"
)

# Jinja's delimiters. The bodies are prose and markdown, and the day one
# of these appears in a body is the day a prompt silently loses a
# section — so it is a red test, not a surprise in production.
JINJA_DELIMITERS = ("{{", "}}", "{%", "%}", "{#", "#}")
# A lane qualification is NOT a convergence cycle, and it must not live
# in the protocol's log: `converged_suite_cycles` reads TRAILING cycles,
# so five qualification runs appended to iterations.jsonl displaced the
# v10 cycle and made the rule stop seeing the evidence for its own pin
# (measured 2026-09-05). The sweep therefore has its own artifact.
WRITER_QUALIFICATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "_evaluate"
    / "writer_qualification_iterations.jsonl"
)


def _briefs_swept_clean_by(writer_model: str) -> set[str]:
    """Briefs this writer passed with every deterministic gate green.

    Reads the append-only iteration log, which is the harness's own
    evidence: a run is clean when the structural, form and refinement
    gates all passed. The visual gate is deliberately NOT part of this,
    because it compares against golden renders minted from one specific
    writer's runs — a different writer's legitimate solution moves the
    render, and that is drift from a reference, not a defect.
    """
    import json

    if not WRITER_QUALIFICATION_PATH.exists():
        return set()
    swept: set[str] = set()
    for line in WRITER_QUALIFICATION_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if record.get("writer_model") != writer_model:
            continue
        if (
            record.get("structural_gate_passed")
            and record.get("form_gate_passed")
            and record.get("refinement_gate_passed")
        ):
            swept.add(record.get("brief_name", ""))
    return swept


def test_every_registered_revision_has_a_template():
    on_disk = set(prompt_templates.available_revisions())
    registered = {entry.revision for entry in prompt_versions.PROMPT_REVISIONS}
    assert registered == on_disk, (
        f"registry and prompts/ disagree: registered={sorted(registered)}, "
        f"on disk={sorted(on_disk)}"
    )


def test_the_revision_history_is_disciplined():
    """One hypothesis, one hunk, one outcome per revision."""
    assert prompt_versions.validate_revisions() == []


# The baseline (revision 1) has no predecessor to differ from.
@pytest.mark.parametrize(
    "revision",
    [
        entry.revision
        for entry in prompt_versions.PROMPT_REVISIONS
        if entry.revision > 1
    ],
)
def test_each_revision_changes_exactly_one_place(revision):
    hunks = prompt_versions.changed_hunks(
        prompt_versions.get_revision(revision - 1).body,
        prompt_versions.get_revision(revision).body,
    )
    assert len(hunks) == prompt_versions.MAXIMUM_CHANGED_HUNKS_PER_REVISION, hunks


def test_the_pinned_revision_text_has_not_drifted():
    assert PINNED_IDENTITY_PATH.exists(), (
        f"no {PINNED_IDENTITY_PATH}: the pinned identity is written by "
        f"`make pin`, and without it nothing proves the pinned text is the "
        f"text that converged"
    )
    pinned = prompt_versions.get_revision(prompt_versions.PINNED_PROMPT_REVISION)
    assert pinned.identity == PINNED_IDENTITY_PATH.read_text(encoding="utf-8").strip()


def test_the_assembled_prompt_has_not_drifted():
    """The pinned identity cannot see this, which is why it exists."""
    assert PINNED_ASSEMBLED_FINGERPRINT_PATH.exists(), (
        f"no {PINNED_ASSEMBLED_FINGERPRINT_PATH}: write it from "
        f"`assembled_prompt_fingerprint()`'s own output, never by hand"
    )
    recorded = PINNED_ASSEMBLED_FINGERPRINT_PATH.read_text(encoding="utf-8").strip()
    current = system_prompt.assembled_prompt_fingerprint()
    assert current == recorded, (
        f"the prompt the model reads changed: {recorded} -> {current}. The "
        f"working-agreement identity does not cover the conventions, the "
        f"operations manifest, the drift catalog or the skill modules, so "
        f"this is the only test that sees such an edit. If the change was "
        f"intended, update {PINNED_ASSEMBLED_FINGERPRINT_PATH.name} in the "
        f"same commit."
    )


def test_the_assembled_fingerprint_covers_the_drift_catalog(monkeypatch):
    """One edited drift row must move the fingerprint.

    The whole point of the assembled hash: a drift row reaches the model
    through `build_manifest()` on every turn and is outside
    `PromptRevision.identity` entirely. Patching the catalog module
    reaches the manifest because `build_manifest` imports
    `DRIFT_ENTRIES` inside the function, not at module scope.
    """
    extra = catalog.DriftEntry(
        symbol="bpy.types.Synthetic.only_in_this_test",
        changed_in="9.9",
        error_signature="this row exists only inside this test",
        fix="Nothing: the row is here to prove the fingerprint sees it.",
        source="[measured] test_the_assembled_fingerprint_covers_the_drift_catalog",
    )
    before_assembled = system_prompt.assembled_prompt_fingerprint()
    before_identity = prompt_versions.get_revision(
        prompt_versions.PINNED_PROMPT_REVISION
    ).identity

    monkeypatch.setattr(catalog, "DRIFT_ENTRIES", catalog.DRIFT_ENTRIES + (extra,))

    # The probe must be VISIBLE before its effect can be interpreted. A
    # patch that silently missed would otherwise read as "the drift
    # catalog does not reach the prompt", which is the opposite lesson.
    assert extra.fix in manifest.build_manifest(), (
        "the synthetic row never reached build_manifest, so this test measured nothing"
    )

    after_assembled = system_prompt.assembled_prompt_fingerprint()
    after_identity = prompt_versions.get_revision(
        prompt_versions.PINNED_PROMPT_REVISION
    ).identity
    assert after_assembled != before_assembled, (
        "a new drift row did not move the assembled fingerprint, so the "
        "fingerprint does not cover the manifest it claims to cover"
    )
    assert after_identity == before_identity, (
        "the working-agreement identity moved, which it must not: it hashes "
        "the body only, and this test's premise is that the two hashes "
        "cover different text"
    )


def test_the_template_file_is_the_body_byte_for_byte():
    """No preamble, no front matter, no normalization on the way in."""
    for entry in prompt_versions.PROMPT_REVISIONS:
        path = prompt_templates.template_path(
            f"{prompt_templates.WORKING_AGREEMENT_STEM}{entry.revision}"
        )
        raw = path.read_text(encoding="utf-8")
        assert raw == entry.body, path.name
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
        assert entry.identity.endswith(digest)


def test_no_body_contains_a_jinja_delimiter():
    for entry in prompt_versions.PROMPT_REVISIONS:
        for delimiter in JINJA_DELIMITERS:
            assert delimiter not in entry.body, (
                f"v{entry.revision} contains {delimiter!r}: Jinja would try "
                f"to interpret it and the prompt would lose text"
            )


def test_an_unknown_template_raises_instead_of_rendering_nothing():
    with pytest.raises(prompt_templates.TemplateNotFound):
        prompt_templates.render("working_agreement_v999")


def test_a_missing_variable_is_an_error_not_a_blank():
    """A prompt with a silently empty section still runs, and the agent
    simply never learns the thing that section existed to tell it."""
    from jinja2 import UndefinedError

    with pytest.raises(UndefinedError):
        prompt_templates.render("system_prompt")


def test_the_shipped_configuration_is_the_converged_configuration():
    """The addon ships what the loop converged on, or it ships a lie.

    Guarded here so the axes cannot drift silently: the tool budget, the
    shipped writer, and — the failure that started this whole
    convergence — that the system prompt an AgentSession builds with no
    arguments is the PINNED revision, not some earlier text nobody
    scored.

    The writer is checked against the RUN LOG rather than against
    `CONVERGENCE_WRITER_MODEL`, because those two constants answer
    different questions. `CONVERGENCE_WRITER_MODEL` is provenance: the
    writer whose runs MINTED the golden references, which is why the
    visual gate reports drift for any other writer by construction. The
    shipped default only has to be a writer that demonstrably passed
    this suite — and the append-only log is the evidence, where a
    constant equal to another constant is not.
    """
    from blended.agent.loop import AgentSession, ModelConfig

    assert AgentSession().maximum_tool_calls_per_turn == (
        prompt_versions.CONVERGENCE_TOOL_CALL_BUDGET
    ), "the library default budget drifted from the converged budget"
    assert ModelConfig().vision_model == prompt_versions.CONVERGENCE_VISION_MODEL, (
        "the default eye drifted from the licensed examiner"
    )
    swept = _briefs_swept_clean_by(ModelConfig().model)
    from blended.evaluate.briefs import BRIEFS

    missing = sorted(set(BRIEFS) - swept)
    assert not missing, (
        f"the shipped writer {ModelConfig().model!r} has no clean recorded "
        f"run for {missing} in {WRITER_QUALIFICATION_PATH.name} — a writer nobody "
        f"ran this suite with may not be the default"
    )
    from blended.agent.system_prompt import build_system_prompt

    assert (
        prompt_versions.get_revision(prompt_versions.PINNED_PROMPT_REVISION).body
        in build_system_prompt()
    ), (
        "the default session prompt is not the pinned revision — a user "
        "would talk to text nobody scored"
    )


def test_the_prompt_describes_no_op_twice():
    """OT-24: the generated tool schemas are the one description of each
    op; the manifest's operations section no longer rides in the prompt,
    while conventions, the gate's fields and the drift catalog still do."""
    from blended.agent.system_prompt import (
        GATE_HEADING,
        OUTPUT_CONTRACT_HEADING,
        build_system_prompt,
    )
    from blended.ops._contract import facade_ops

    prompt = build_system_prompt(revision=14)
    for name, _ in facade_ops():
        assert f"{name}(" not in prompt, name
    assert (
        "## Conventions" in prompt
        and GATE_HEADING in prompt
        and "## Known API traps" in prompt
    )
    assert (
        OUTPUT_CONTRACT_HEADING not in prompt
    )  # the chat never wanted 'return only Python'
