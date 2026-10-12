# MCP: auto-framing, a must-read head, opt-in restarts, a plan that survives them

Decided 2026-10-02 after `/code-review max --fix` and a measurement: Claude
Code delivers only the first 2,048 characters of an MCP server's
instructions (blended sends 22,896). The decisions:

1. **Auto-frame in the bridge.** After every scene-changing blended call,
   the server frames the objects that call touched, if they are in the
   scene. The agent makes no extra call. Edits through `run_python`
   still rely on the agent.
2. **Condensed must-read head.** The first 2,048 characters become a short
   list of the rules that must reach every agent. The full text follows
   it. MCP only: the bench's system prompt is untouched.
3. **Restart on source change is opt-in.** It is off by default. omp gets
   its own entry in `.omp/mcp.json` that passes `--exit-on-source-change`.
4. **The declared plan survives a watcher restart.** So does the session
   log.

Position matters because models use the start of a long context better
than the middle (Lost in the Middle, DOI 10.48550/arXiv.2307.03172). Here
the cut is harder still: text past the head is never delivered at all.

## A. Auto-frame (MCP only)

Components:
- `src/blended/viewport_follow.py`. This module has the two parts below and
  a `ViewportFollowConfig` dataclass (margin factor; minimum distance per
  `clip_start`). It has no literals.
  - `frame_target_names(outcome) -> tuple[str, ...]` is pure. It returns
    the gate `object_name`s and `intermediates_resolved`, de-duplicated,
    in order.
  - `frame_in_viewports(names, config) -> str` needs bpy. It keeps only
    the names that are objects in the view layer and takes the world
    bounding sphere of their evaluated bounding boxes. Then, for every
    `VIEW_3D` area in every window, it:
    - leaves camera view;
    - calls `RegionView3D.update()`;
    - reads the field of view, or the ortho extent per unit of distance,
      from `window_matrix` (Blender's own projection, not lens or sensor
      constants);
    - sets `view_location` to the sphere's centre and `view_distance`
      to fit its radius;
    - tags the area for redraw.

    It returns one `viewport:` line: what it framed and in how many
    viewports, or why nothing was framed (background Blender, no 3D
    viewport, nothing in the scene). It changes no selection, no active
    object and no mode, and never rotates the view.
- `blended_bridge_toolcode.py`: after `dispatch_tool`, when
  `plan_required_for(tool_name)` is true, it frames whatever
  `frame_target_names` returns, whether or not the call succeeded, and
  appends the `viewport:` line to `outcome.text`.
- `jump_to_view3d_object_by_name` docstring: blended's scene-changing tools
  frame automatically, so call this after `run_python` edits or to switch
  parts. Update the `test_tool_listing.py` snapshot to match.

Verification:
- Pure: `tests/pure/test_viewport_follow.py`. A gated op, a boolean
  (consumed cutter plus target), `run_python` (gate only) and a failed
  call each give the expected names.
- GUI ground truth: `make test-viewport-gui`, a factory-startup GUI Blender
  with isolated user resources, run from a timer after the first draw. In
  perspective and in ortho, for a 0.05 m box and an 8 m box placed off
  centre, all 8 bounding-box corners must project inside the region
  (`view3d_utils.location_3d_to_region_2d`). The two boxes must produce
  different `view_distance`s, which shows the probe varies. Selection,
  active object and mode must be unchanged. The gate is the exit code.
- `make test-mcp-blender` (background): a scene-changing call's text
  carries `viewport: background Blender`.
- Live: you watch your own Blender while one `add_box` and one
  `link_into_scene` run, and confirm the result before I pin it.

## B. Must-read head (MCP only)

- `blended_bridge.MCP_INSTRUCTIONS_HEAD`, at most
  `CLAUDE_CODE_INSTRUCTIONS_LIMIT_CHARACTERS`, replaces
  `VIEWPORT_FOLLOW_INSTRUCTIONS`. It condenses working-agreement revision
  10 and states the framing behaviour.
- `MCP_INSTRUCTIONS_HEAD_CONDENSES_REVISION = 10`. A test asserts it
  equals the active revision, so moving the agreement fails until someone
  reviews the head.
- Verification:
  - `test_mcp_server.py`: the instructions a real stdio client receives
    start with the head, and the head fits the limit.
  - `test_blended_bridge.py`: the tool the head names is in the registry.

## C. Restart is opt-in

- `blmcp/__init__.py`: `--exit-on-source-change` defaults to False. Passing
  it with http stays an error.
- `.omp/mcp.json`: a `blended` entry like the one in `.mcp.json`, plus
  `["--exit-on-source-change"]`.
- Verification:
  - Unit: the parsed default is False.
  - Measured: starting omp with this project's config spawns
    `blender-mcp --exit-on-source-change` (checked with `ps`), and Claude
    Code's spawn has no watcher.
  - README updated to match.

## D. Plan and log carried across a watcher restart

- On a watcher exit, under the in-flight lock just before `os._exit`, the
  server writes `logs/mcp-handoff-<parent pid>.json` containing
  `plan_declared`, `session_name` and `written_at_s`.
- On start, `BlendedSession` consumes the handoff for `os.getppid()` only
  when it is younger than `HANDOFF_MAX_AGE_S`. It restores the plan,
  continues the same session's `jsonl` and output directory, and records
  a `session` event saying so. An expired handoff is deleted and reported
  on stderr.
- `ChatTranscript` continues an existing jsonl's event numbering instead
  of restarting it at 1.
- Verification (unit):
  - A watcher exit with a plan declared writes the handoff.
  - A session with the same parent pid gate-passes a scene-changing call
    and appends to the same jsonl.
  - A different parent pid and an expired handoff start fresh, and the
    expired file is removed.
  - Event indices stay strictly increasing across the resume.

## Records

- Amend the mistake record `mcp-instructions-past-2048-characters-never-arrive`
  in place. The first rule told agents to frame after every create, but
  `add_box`, `add_cylinder` and `add_lathe` return unlinked objects, and
  framing one raises "not in View Layer". That made the rule halt agents
  before `link_into_scene`.
- Add records for the auto-framing gate and for the handoff.

## Status, 2026-10-02 (measured)

- **A, auto-frame:**
  - `make test-viewport-gui` passes with 0 failures. The fitted
    `view_distance` was 0.130 m (tiny box) and 20.79 m (8 m box) in
    perspective, and 0.120 m and 19.20 m in ortho.
  - With the margin set to 0.3 instead of 1.15, the check failed 6 of 6:
    corners projected outside the 2096x1208 region.
  - `make test-mcp-blender` asserts the `viewport:` line through the real
    MCP path, background mode only. The foreground class needs Weston,
    which is Linux only.
  - Still open: your live sign-off in your own Blender.
- **B, head:** `MCP_INSTRUCTIONS_HEAD` is 1,823 characters (limit 2,048).
  The served-instructions test passes.
- **C, opt-in:**
  - The parsed default is False.
  - omp (pid 90092) spawned exactly one `blender-mcp --exit-on-source-change`
    (pid 90096, parent 90092). So `.omp/mcp.json` overrides the same-named
    entry in `.mcp.json`.
- **D, handoff:**
  - Unit tests pass.
  - The live two-process test passes, and failed with the resume disabled.
    The replacement server then answered `add_box` with "No plan declared".
  - A side fix: `ChatTranscript` now continues a reopened log's event
    numbering. It used to restart at 1, so indices repeated.
