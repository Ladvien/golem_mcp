"""The 3DCodeBench task text, in the two formats a run can answer in.

One definition, two consumers, so an experiment that compares them is
diffing real strings and not two drifted copies:

* `scripts/run_3dcode_instance.py` (and the op-format arm of the
  fine-tune decision experiment) sends `OPS_TASK_TEMPLATE` — the
  benchmark's requirements plus the load-bearing sentence that geometry
  built outside a `run_python` chunk will not exist when the emitted
  script is re-executed.
* the raw-bpy arms send `RAW_TASK_TEMPLATE`, which is the same text with
  that one bullet removed, because those arms have no `run_python` tool
  to name. Everything else is byte-identical, and the report carries the
  unified diff of the two system prompts beside it
  (`docs/research/2026-09-19-finetune-decision-experiment.md` §5.2,
  prompt parity).

The text adds only what the benchmark's scorers require and this
harness's system prompt does not already say: one mesh at the origin, no
camera/light/render, and the world-axis alignment the scorer's
yaw-quotient makes load-bearing.
"""

from __future__ import annotations

# What the object is and the rules that hold in both formats.
TASK_REQUIREMENTS = """\
Build this object as a single mesh in the current empty scene:

{description}

Rules for this task:
- Exactly ONE final mesh object may remain in the scene when you finish. Delete every
  helper, duplicate and temporary object.
- Place it at the world origin. No ground plane, no backdrop, no extra props.
- Build real parametric geometry - loops, modifiers, bmesh ops. Do not stack a few
  primitives and stop.
- Do not add cameras or lights. Do not render to disk from your Python. Do not call
  sys.exit or bpy.ops.wm.quit_blender.
"""

# Only the op/tool format has a `run_python` chunk to build inside, and
# only there does the bake collect chunks rather than the whole reply.
CHUNK_RULE = """\
- Every piece of geometry must be created inside `run_python` chunks. Those chunks are
  collected verbatim into a standalone script that is re-executed from an empty scene to
  score this run, so anything built outside a chunk will not exist when it is re-run.
"""

# The scorer quotients out rotation about glTF Z only, so which Blender
# axis lands on the depth axis is penalised in full. Same text in both
# formats.
PLACEMENT_RULE = """\
Placement: the scored mesh is compared in world space against a reference mesh,
and neither is reoriented. Align the object's principal axes with the world axes:
- Up is +Z. Legs, stems and stand-offs point straight down; tops and caps are
  horizontal. No tilt, no roll, no spin to an arbitrary angle.
"""

# ONLY the single-shot regime of the fine-tune decision experiment, and
# only for the op format. Measured 2026-09-19 before any arm was run:
# with the multi-turn harness system prompt and no such sentence, 3 of 4
# single-shot replies from `claude-code:sonnet` were a `declare_plan`
# call and nothing else (Jar, Plate, Pillar; Spoon built geometry) — the
# prompt describes a plan-then-act-then-verify loop and a compliant
# model stops after the plan. That is a prompt artifact, not a fact
# about the op format, and spec §9 says to investigate the prompt rather
# than burn the roll on it. The raw arms already carry the equivalent
# statement in the benchmark's own system prompt ("your entire response
# will be saved verbatim into a .py file"), so adding it here makes the
# two formats MORE comparable, not less. Both op arms (A1 and A2) get
# the identical text, so prompt parity inside the format holds.
SINGLE_SHOT_RULE = """\
This is a SINGLE-SHOT task. You get exactly one reply and there will be no
further turns: no tool results come back, no follow-up message, no chance to
verify or correct. Emit every tool call the object needs in THIS reply, in
order. A reply that only declares a plan, or that answers in prose, builds
nothing and scores zero.
"""

OPS_TASK_TEMPLATE = TASK_REQUIREMENTS + CHUNK_RULE + PLACEMENT_RULE
RAW_TASK_TEMPLATE = TASK_REQUIREMENTS + PLACEMENT_RULE
# What the experiment's op arms send. The production runner keeps sending
# OPS_TASK_TEMPLATE, so the archive stays comparable to itself.
SINGLE_SHOT_OPS_TASK_TEMPLATE = (
    TASK_REQUIREMENTS + CHUNK_RULE + PLACEMENT_RULE + "\n" + SINGLE_SHOT_RULE
)
