"""Provenance and the human-correction log, checked without Blender.

A brief's `prompt_text` carries executable specs, but nothing else in the
module answers *where each number came from* or *what a human asked to
change*. `Provenance` pins each number to the requester's own words and
the constant that holds it; `Correction` records what moved when a human
asked. `validate_briefs` is the gate that catches a renamed constant, a
stale value, or a missing citation before the brief ships.

These tests run on every `make test-pure` because a stale provenance
entry is a doc that lies — the exact failure class the repo's
pin-verified-behavior rule exists to prevent.
"""

from blended.evaluate.briefs import (
    SOURCE_ART_DIRECTION,
    SOURCE_LITERATURE,
    STOOL_LEG_COUNT,
    STOOL_SEAT_DIAMETER_M,
    THREE_LEG_STOOL_BRIEF,
    AssetBrief,
    Correction,
    Provenance,
    _validate_brief,
    validate_briefs,
)

# One brief is instrumented today (the stool, the worked example the
# next brief copies). The floor exists so that number can only go up:
# `validate_briefs` tolerates an empty provenance tuple, so without a
# floor a brief can ship with none and nothing notices.
MINIMUM_BRIEFS_WITH_PROVENANCE = 1


def test_validate_briefs_is_healthy():
    """The shipped registry must pass its own gate."""
    assert validate_briefs() == []


def test_stool_provenance_phrases_are_substrings_of_prompt_text():
    """Every provenance phrase must be the requester's own words, verbatim.

    `validate_briefs` makes the same comparison — the check lives in
    `_validate_brief`, not here. What this test adds is the FLOOR below
    it: the worked example must actually carry provenance, which the
    validator tolerates being empty.
    """
    stool = THREE_LEG_STOOL_BRIEF
    assert stool.provenance, "the stool brief must carry provenance"
    for prov in stool.provenance:
        assert prov.phrase in stool.prompt_text, (
            f"provenance phrase {prov.phrase!r} is not a substring of "
            f"the stool brief's prompt_text"
        )


def test_the_provenance_floor_does_not_slip():
    """A gate everyone can opt out of by default never grows.

    `validate_briefs` tolerates an empty provenance tuple, which is
    what lets a new brief ship with none. The two sibling doc gates in
    this patch each carry a floor for exactly this reason
    (MINIMUM_TOOL_CITATIONS_CHECKED, MINIMUM_IMPORTS_CHECKED); this is
    the briefs floor. Raise it when you instrument a brief — never
    lower it.
    """
    from blended.evaluate.briefs import BRIEFS

    instrumented = sorted(name for name, brief in BRIEFS.items() if brief.provenance)
    assert len(instrumented) >= MINIMUM_BRIEFS_WITH_PROVENANCE, (
        f"only {instrumented} carry provenance, expected at least "
        f"{MINIMUM_BRIEFS_WITH_PROVENANCE}"
    )


def test_a_registry_key_that_disagrees_with_the_brief_name_is_reported():
    """`get_brief` looks up by KEY; every message prints `brief.name`.

    A mismatch reports a brief the caller cannot fetch. This replaced a
    name-uniqueness loop over a dict's keys, which could not fire.
    """
    from blended.evaluate.briefs import BRIEFS

    stray = AssetBrief(
        name="not_the_key",
        prompt_text="Build something.",
        parts=(),
    )
    BRIEFS["some_other_key"] = stray
    try:
        problems = validate_briefs()
    finally:
        del BRIEFS["some_other_key"]
    assert any(
        "some_other_key" in problem and "not_the_key" in problem for problem in problems
    ), problems


def test_an_empty_phrase_is_reported():
    """A number with no words is not provenance.

    The phrase check used to be skipped when the phrase was empty,
    which made the only check tying a number to what was asked for
    opt-out — while the correction check twelve lines below rejected an
    empty `said` outright.
    """
    problems = _validate_brief(
        AssetBrief(
            name="empty_phrase",
            prompt_text="Build a stool.",
            parts=(),
            provenance=(
                Provenance(
                    phrase="",
                    symbol="STOOL_LEG_COUNT",
                    value=STOOL_LEG_COUNT,
                    source=SOURCE_ART_DIRECTION,
                ),
            ),
        )
    )
    assert len(problems) == 1, problems
    assert "empty phrase" in problems[0]
    assert "STOOL_LEG_COUNT" in problems[0]


def test_a_symbol_naming_a_non_number_is_reported_not_raised():
    """The validator returns problems; it does not raise.

    `float(current)` on a symbol that resolves to a string or a tuple
    used to raise out of the validator, aborting every remaining brief
    and naming neither the brief nor the symbol — the least usable
    failure for the one typo the gate exists to catch.
    """
    problems = _validate_brief(
        AssetBrief(
            name="wrong_symbol",
            prompt_text="measured",
            parts=(),
            provenance=(
                Provenance(
                    phrase="measured",
                    symbol="SOURCES",
                    value=1.0,
                    source=SOURCE_ART_DIRECTION,
                ),
            ),
        )
    )
    assert len(problems) == 1, problems
    assert "SOURCES" in problems[0]
    assert "tuple" in problems[0]


def test_wrong_value_is_reported():
    """A provenance entry whose value disagrees with the constant is caught.

    This is the negative control: a validator that cannot fail is not a
    gate. The wrong value is 0.99 — far enough from 0.32 that no float
    tolerance could absorb it.
    """
    bad = Provenance(
        phrase="The round seat is 0.32 m across",
        symbol="STOOL_SEAT_DIAMETER_M",
        value=0.99,
        source=SOURCE_ART_DIRECTION,
    )
    brief = AssetBrief(
        name="synthetic_wrong_value",
        prompt_text="The round seat is 0.32 m across",
        parts=(),
        provenance=(bad,),
    )
    problems = _validate_brief(brief)
    assert len(problems) == 1
    assert "STOOL_SEAT_DIAMETER_M" in problems[0]
    assert "0.99" in problems[0]


def test_unknown_source_is_reported():
    """A provenance entry with a source not in SOURCES is caught."""
    bad = Provenance(
        phrase="The round seat is 0.32 m across",
        symbol="STOOL_SEAT_DIAMETER_M",
        value=STOOL_SEAT_DIAMETER_M,
        source="guess",
    )
    brief = AssetBrief(
        name="synthetic_unknown_source",
        prompt_text="The round seat is 0.32 m across",
        parts=(),
        provenance=(bad,),
    )
    problems = _validate_brief(brief)
    assert any("guess" in p for p in problems), (
        f"unknown source 'guess' was not reported: {problems}"
    )


def test_literature_without_citation_is_reported():
    """A literature source with an empty `cites` is caught."""
    bad = Provenance(
        phrase="The round seat is 0.32 m across",
        symbol="STOOL_SEAT_DIAMETER_M",
        value=STOOL_SEAT_DIAMETER_M,
        source=SOURCE_LITERATURE,
        cites="",
    )
    brief = AssetBrief(
        name="synthetic_no_citation",
        prompt_text="The round seat is 0.32 m across",
        parts=(),
        provenance=(bad,),
    )
    problems = _validate_brief(brief)
    assert any("no citation" in p for p in problems), (
        f"literature without cites was not reported: {problems}"
    )


def test_correction_with_empty_said_is_reported():
    """A correction nobody asked for is not a correction."""
    brief = AssetBrief(
        name="synthetic_empty_correction",
        prompt_text="irrelevant",
        parts=(),
        corrections=(Correction(said="", changed="STOOL_LEG_COUNT", on="2026-09-06"),),
    )
    problems = _validate_brief(brief)
    assert any("empty" in p.lower() and "said" in p for p in problems), (
        f"correction with empty said was not reported: {problems}"
    )
