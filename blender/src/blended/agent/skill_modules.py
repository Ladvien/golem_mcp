"""Capability modules — the SKILLS half of the prompt, and its selector.

`prompt_versions.py` owns the working agreement: how the agent and the
user work together, tuned as one monolith by the convergence loop. This
module owns something different — the procedural knowledge a particular
LANE needs, which is useless weight on every turn that is not in that
lane.

The split exists because loading everything is measurably worse than
loading a little. SkillsBench (84 tasks, 11 domains, 7,308 trajectories,
`10.48550/arXiv.2602.12670`) measured curated skills at +16.2 pp overall,
but the effect depends on how many load at once:

    2-3 focused modules   +18.6 pp
    4+ modules             +5.9 pp
    written "comprehensive" -2.9 pp
    written compact        +18.8 pp

The same shape shows up in SWE-agent's window ablations — a 100-line
file view scored 18.0% where the whole file scored 12.7%
(`10.48550/arXiv.2405.15793`) — and in "lost in the middle", where 20-30
retrieved documents drove accuracy BELOW the closed-book baseline
(`10.48550/arxiv.2307.03172`). More context is not more capability.

So `MAXIMUM_MODULES_LOADED = 3` is enforced by assertion, the way
`MAXIMUM_CHANGED_HUNKS_PER_REVISION = 1` already is. A fourth module in
a lane is a design error that should surface as a red test, not as a
quietly worse agent.

TWO HONEST CAVEATS, both measured in the same study:

1. 16 of the 84 tasks got WORSE with skills, worst case -39.3 pp. A
   module is a change with a sign. Each carries `hypothesis` stated
   before its convergence run and `outcome` filled from measurement, and
   a module that measures negative is REMOVED, not tuned.
2. Self-generated skills measured -1.3 pp against +16.2 pp for curated
   ones: "models cannot reliably author the procedural knowledge they
   benefit from consuming." These bodies were drafted by an agent. Until
   a human has reviewed each one and a convergence run has scored it,
   the +16.2 pp result does not apply to them.

Which is why no lane is selected by default. `build_system_prompt()`
with no arguments still renders exactly the pinned, converged text and
nothing else — see `system_prompt.py`. Skills are opt-in per turn until
they are measured, because the alternative is silently changing the
prompt that every previous score was attributed to.

The bodies live in `prompts/skills/*.md.j2` for the same reason the
working agreement does: prose belongs in a file a person can read and
diff. This module is the registry.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass


@dataclass(frozen=True)
class SkillModule:
    """One capability module, with the subsystem and evidence it serves."""

    name: str
    subsystem: str  # the src/blended package this module speaks for
    purpose: str  # one line: what a turn gains by loading it
    hypothesis: str  # stated BEFORE the run: "expect X because Y"
    outcome: str  # filled from measurement AFTER the run; "" while pending
    evidence: tuple[str, ...]  # DOIs / corpus stems, for re-lookup

    @property
    def body(self) -> str:
        from blended.agent.prompt_templates import render_skill

        return render_skill(self.name)

    @property
    def identity(self) -> str:
        """Content hash: proves which text actually ran."""
        digest = hashlib.sha256(self.body.encode("utf-8")).hexdigest()
        return f"{self.name}:{digest[:12]}"


SKILL_MODULES: tuple[SkillModule, ...] = (
    SkillModule(
        name="builder_authoring",
        subsystem="builders, ops",
        purpose=(
            "Program-as-artifact discipline: one class per part, config "
            "separate from construction, explicit preconditions, measure "
            "after the last mutation."
        ),
        hypothesis=(
            "Expect fewer undebuggable failures and fewer measurements "
            "taken before a boolean moves the thing measured, because the "
            "conventions list covers which ops to call but never the shape "
            "the code should take or when a measurement is valid."
        ),
        outcome="",
        evidence=(
            "10.48550_arXiv.2606.01057",  # program-as-artifact, 3DCodeBench
            "10.48550_arxiv.2105.09492",  # DeepCAD: sequences edit, B-reps do not
        ),
    ),
    SkillModule(
        name="api_drift",
        subsystem="drift, version",
        purpose=(
            "The version contract: read the pinned surface rather than "
            "recall it, and treat an attribute or keyword traceback as a "
            "drift report rather than a logic error."
        ),
        hypothesis=(
            "Expect executability to rise and the same traceback to repeat "
            "less often, because ~85% of failures in the weakest measured "
            "models were version drift and the agent cannot detect its own "
            "knowledge cutoff from the inside."
        ),
        outcome="",
        evidence=(
            "10.48550_arXiv.2606.01057",  # 85% of failures were 4.x->5.0 drift
            "10.48550/arXiv.2508.08228",  # LL3M BlenderRAG, -26% error rate
            "10.18653/v1/2020.acl-main.538",  # API-doc retrieval, 31.5->36.8
        ),
    ),
    SkillModule(
        name="mesh_validity",
        subsystem="analyze",
        purpose=(
            "The designed-mesh defect vocabulary, and why automatic repair "
            "is not a solution that can be trusted without its threshold."
        ),
        hypothesis=(
            "Expect fewer blind repairs and more printed thresholds, "
            "because repair is ill-posed and known to introduce new defects "
            "while fixing the ones it was aimed at."
        ),
        outcome="",
        evidence=(
            "10.1145_2431211.2431214",  # Attene: designed vs digitized taxonomy
            "10.1007_s00371-010-0416-3",  # not guaranteed to terminate with success
        ),
    ),
    SkillModule(
        name="visual_critique",
        subsystem="capture, evaluate",
        purpose=(
            "Renders are advisory and biased toward acceptance; assert the "
            "camera, and check that a fix actually landed."
        ),
        hypothesis=(
            "Expect fewer premature done-calls, because visual verifiers "
            "show high recall and low precision, and their agreement with "
            "human judgment falls from ~0.77 to ~0.46 as output improves."
        ),
        outcome="",
        evidence=(
            "10.48550_arxiv.2606.15693",  # verifier false-positive bias
            "10.48550/arXiv.2508.08228",  # LL3M critic/verifier split
            "10.48550/arXiv.2403.18771",  # CheckEval: closed vocabulary
        ),
    ),
    SkillModule(
        name="generated_mesh_ingest",
        subsystem="ingest",
        purpose=(
            "A generated mesh is a blockout: measure before routing it, and "
            "name which of the three lanes it entered."
        ),
        hypothesis=(
            "Expect fewer generated meshes decimated to a budget and "
            "presented as built, because native-mesh generators top out in "
            "the hundreds to low thousands of faces and decimation on "
            "non-manifold input tears holes that the rendered angle hides."
        ),
        outcome="",
        evidence=(
            "10.48550_arxiv.2406.10163",  # MeshAnything: avg 318 faces
            "10.48550_arxiv.2409.18114",  # EdgeRunner: ~4000 face ceiling
            "10.1109/visual.1998.745312",  # QEM needs a boundary penalty
            "10.1145/1061347.1061350",  # boundary error terms are not optional
            "10.48550/arxiv.2409.15458",  # Simplifying Textured Meshes in the Wild
        ),
    ),
    SkillModule(
        name="game_ready_export",
        subsystem="export",
        purpose=(
            "Budgets are project inputs, not recalled facts; conventions "
            "are per-format; an export is not a result until it round-trips."
        ),
        hypothesis=(
            "Expect invented budget numbers and single remembered axis "
            "rules to stop appearing, because no per-platform budget table "
            "survives contact with the sources and the correct axes differ "
            "between formats for the same engine."
        ),
        outcome="",
        evidence=(
            "book_real_time_rendering_4th_akenine",  # 'your mileage may vary'
            "book_digital_modeling_vaughan",  # 'well, it depends' (p.172)
            "10.1145/383259.383307",  # stretch/deviation trade-off
        ),
    ),
    SkillModule(
        name="iteration_and_memory",
        subsystem="run, evaluate",
        purpose=(
            "Iterate only behind the gate, spend the budget where the gain "
            "is, and record the check that would have caught the failure."
        ),
        hypothesis=(
            "Expect fewer rounds spent on unanchored polish, because most "
            "of the available gain lands in the first correction and "
            "self-correction without an external signal degrades round over "
            "round."
        ),
        outcome="",
        evidence=(
            "10.48550/arxiv.2303.17651",  # Self-Refine: gains front-loaded
            "10.48550/arXiv.2310.01798",  # degrades without an oracle
            "10.48550/arXiv.2305.16291",  # Voyager: 4 rounds, behind a verifier
        ),
    ),
    SkillModule(
        name="mesh_construction",
        subsystem="builders, ops",
        purpose=(
            "The transferable technique rules for authored mesh "
            "construction: overlap order, centred-section clearance, "
            "and the three independent appearance metrics."
        ),
        hypothesis=(
            "Expect fewer non-manifold junctions and fewer wrongly-sized "
            "shells, because the rules are measured counter-examples to the "
            "obvious move — butting shells, capping open boundaries — "
            "and each names the number that measured it."
        ),
        outcome="",
        evidence=(
            "[measured] scp_characters .claude/skills/modeling/SKILL.md",
            "[measured] scp_characters .claude/skills/game-ready/SKILL.md",
            "10.1145/1061347.1061350",  # boundary error terms are not optional
            "10.1109/visual.1999.809869",  # Hoppe: appearance-attribute quadric
            "10.48550/arxiv.2409.15458",  # Simplifying Textured Triangle Meshes in the Wild
        ),
    ),
)


# 2-3 focused modules measured +18.6 pp; 4+ collapsed to +5.9 pp
# (10.48550/arXiv.2602.12670). A lane wanting a fourth module is a lane
# that has not decided what it is doing.
MAXIMUM_MODULES_LOADED = 3

# Skill documents written to be "comprehensive" measured -2.9 pp in the
# same study; compact ones measured +18.8 pp. A module that has grown
# past this is a module that has started documenting its subsystem
# instead of instructing a turn, and the cap is where that gets noticed.
MAXIMUM_MODULE_LINES = 60

# Lane modules DISPLACE rather than add. Every tuple is a full selection,
# not an addition to a base, so the cap is visible at the point of choice.
LANE_MODULES: dict[str, tuple[str, ...]] = {
    "build": ("builder_authoring", "api_drift", "mesh_validity"),
    "ingest": ("generated_mesh_ingest", "api_drift", "mesh_validity"),
    "export": ("game_ready_export", "mesh_validity", "api_drift"),
    "inspect": ("visual_critique", "mesh_validity", "iteration_and_memory"),
    "refine": ("iteration_and_memory", "visual_critique", "mesh_validity"),
    # Awaits measurement: nothing selects lanes at runtime yet, so this is
    # a registry addition, not a prompt change — the opt-in-until-measured
    # design the module docstring argues for.
    "construct": ("mesh_construction", "api_drift", "mesh_validity"),
}


class UnknownSkillModule(KeyError):
    """Named module has no entry. There is no default module."""


class UnknownLane(KeyError):
    """Named lane has no selection. There is no default lane."""


def get_module(name: str) -> SkillModule:
    for entry in SKILL_MODULES:
        if entry.name == name:
            return entry
    available = ", ".join(entry.name for entry in SKILL_MODULES)
    raise UnknownSkillModule(f"No skill module {name!r}. Available: {available}.")


def select_modules(lane: str) -> tuple[SkillModule, ...]:
    """The modules one lane loads. Unknown lanes raise rather than default.

    A lane that silently fell back to an empty selection would score a
    turn against text that never ran, which is the same failure
    `get_revision` refuses for prompt revisions.
    """
    if lane not in LANE_MODULES:
        available = ", ".join(sorted(LANE_MODULES))
        raise UnknownLane(f"No lane {lane!r}. Available: {available}.")
    return tuple(get_module(name) for name in LANE_MODULES[lane])


def render_modules(lane: str) -> str:
    """The selected modules as one block, in the lane's declared order."""
    return "\n".join(module.body.rstrip("\n") for module in select_modules(lane))


def validate_modules() -> list[str]:
    """Schema and discipline problems (empty list = a healthy registry).

    Checks what a reader would otherwise take on trust: every registered
    module renders, every template on disk is registered, no lane exceeds
    the cap, no module is unreachable, and every module carries the
    hypothesis and the evidence that justify its existence.
    """
    from blended.agent.prompt_templates import available_skills

    problems: list[str] = []
    registered = {entry.name for entry in SKILL_MODULES}
    for name, count in sorted(Counter(entry.name for entry in SKILL_MODULES).items()):
        if count > 1:
            problems.append(
                f"{name!r} is registered {count} times: get_module returns the first"
            )

    on_disk = set(available_skills())
    for orphan in sorted(on_disk - registered):
        problems.append(
            f"{orphan!r} has a template but no registry entry: text that "
            f"cannot be selected, and whose effect nothing records"
        )
    for missing in sorted(registered - on_disk):
        problems.append(f"{missing!r} is registered but has no template")

    for entry in SKILL_MODULES:
        try:
            body = entry.body
        except Exception as error:  # noqa: BLE001 — reported, not raised
            problems.append(f"{entry.name}: template did not render: {error}")
            continue
        if not body.strip():
            problems.append(f"{entry.name}: template rendered empty")
        if not entry.hypothesis.strip():
            problems.append(f"{entry.name}: no hypothesis recorded")
        if not entry.evidence:
            problems.append(
                f"{entry.name}: no evidence recorded — a module nobody can "
                f"re-look-up is a module nobody can challenge"
            )
        line_count = len(body.splitlines())
        if line_count > MAXIMUM_MODULE_LINES:
            problems.append(
                f"{entry.name}: {line_count} lines, over "
                f"{MAXIMUM_MODULE_LINES}. Compact modules measured +18.8 pp "
                f"where comprehensive ones measured -2.9 pp "
                f"(10.48550/arXiv.2602.12670); split it or cut it"
            )

    for lane, names in sorted(LANE_MODULES.items()):
        if len(names) > MAXIMUM_MODULES_LOADED:
            problems.append(
                f"lane {lane!r} loads {len(names)} modules, not "
                f"{MAXIMUM_MODULES_LOADED}: 2-3 focused modules measured "
                f"+18.6 pp where 4+ measured +5.9 pp "
                f"(10.48550/arXiv.2602.12670)"
            )
        if len(set(names)) != len(names):
            problems.append(f"lane {lane!r} loads the same module twice: {names}")
        for name in names:
            if name not in registered:
                problems.append(f"lane {lane!r} references unknown module {name!r}")

    selected = {name for names in LANE_MODULES.values() for name in names}
    for unreachable in sorted(registered - selected):
        problems.append(
            f"{unreachable!r} is in no lane: it can never load, so it is "
            f"documentation filed in the wrong place"
        )

    return problems
