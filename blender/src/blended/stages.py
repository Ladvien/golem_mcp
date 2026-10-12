"""The stage vocabulary a run reports (EXE-6).

One definition, read by `harness.run_chunk` (a Python chunk) and by
`agent.op_call` (a facade op called as a tool), so the model sees the
same words whichever path it took and a result can never claim success
past the stage that failed. Pure: no Blender.
"""

from __future__ import annotations

STAGE_EXECUTE = "execute"  # the code (chunk or op) ran, or failed to
STAGE_LOCATE = "locate"  # the named object was looked up in the scene
STAGE_GATE = "gate"  # the analyzer and scene-state gate judged it
STAGE_EXPORT = "export"  # the optional .glb round trip
STAGE_DONE = "done"  # every stage requested passed

STAGES = (STAGE_EXECUTE, STAGE_LOCATE, STAGE_GATE, STAGE_EXPORT, STAGE_DONE)
