# golem_blender

golem_blender is part of golem (`Ladvien/golem_mcp`, directory `blender/`); its MCP server is registered as `golem` and also serves big's golem tools.

The agent's artifact is a **program** (`Parameters` + `Builder` Python
modules), not a mesh. The harness's job is to make the environment tell
the truth: structured tracebacks with known-API-drift fixes attached, a
mesh analyzer as the hard acceptance gate, and multi-view captures for
inspection. Rendered critique advises; the analyzer decides.

## One call

```python
from golem_blender.builders import BarrelBuilder, BarrelParameters
from golem_blender.harness import HarnessSettings, run_builder

result = run_builder(
    BarrelBuilder(BarrelParameters()),
    HarnessSettings(
        export_glb_path="out/barrel.glb",
        export_blend_path="out/barrel.blend",  # required with export_glb_path
    ),
)
print(result.summary())  # execute -> gate -> contact sheet -> verified export + .blend
```

`run_chunk(source, object_name, fix_source=...)` is the same loop for
agent-written code: tracebacks come back annotated with known API-drift
fixes, retries are capped at 2, and every attempt lands in the session
log. Failures still produce a contact sheet — a failure you cannot
review is a failure you will repeat.

## Layout

```
src/golem_blender/
  harness.py     run_chunk / run_builder - the one-call loop
  stages.py      the one stage vocabulary (execute, locate, gate, export, done)
  task.py        the 3-round agent task loop with agent-shaped failure feedback
  manifest.py    the capability manifest, generated from live code
  viewport_follow.py  frames what a scene-changing MCP call touched in the 3D viewport
  version.py     Blender series pin (5.2) + skew assertion
  reset.py       wipe to a canonical empty scene, with the wipe ASSERTED
  drift/         API drift catalog — grows with every instructive traceback
  ops/           reusable construction vocabulary: the data API, with bpy.ops only in
                 uv and rigging, each wrapped once; motion.py (skinned-motion ops)
                 over the skinclip package
  builders/      Parameters + Builder pairs (crate, barrel, pallet)
  analyze/       the mesh analyzer (the hard gate) + pair checks + metamorphic relations
  capture/       front/right/top/three-quarter renders, contact sheets, reference photos,
                 and the shader-accurate texture preview (EEVEE: Workbench cannot show a texture)
  pbr/           the PBR texture lane: a base colour computed from a material's description
                 (the pattern and the palette, fitted on ambientCG truths), layered sets (a
                 base with other materials laid over it under masks), file names, the ORM
                 channel packing, the codex path swap, and the procedure the `pbr_texture`
                 prompt serves
  run/           executor, retry loop, JSONL session log
  ingest/        GLB import + bounded cleanup (the generated-mesh lane)
  export/        glTF export with welded round-trip verification
  evaluate/      briefs, acceptance, examiner, iteration log, mistake memory,
                 reproducibility digest, the 3DCodeBench bridge
  agent/         AgentSession (model lanes, plan gate, caps), TOOL_SCHEMAS and
                 dispatch_tool, prompts and their revisions
blender_mcp/     Blender Lab's MCP server (vendored subtree) extended to serve the
                 tool surface; its add-on and unit tests
scripts/         entry points: converge, replay, calibrate, pin, 3DCodeBench sweep
tests/pure/      no Blender required, runs anywhere
tests/blender/   requires `import bpy` (pip wheel or Blender's Python)
tests/bench_scripts/  the bench scripts' tests (numpy, scipy, trimesh, Pillow),
                 run by `make test-bench-scripts`
tests/gui/       the viewport-framing check, run by `make test-viewport-gui`
docs/            specification, roadmap, plans, research
```

## Chat (Claude Code over MCP)

The agent is Claude Code driving Blender through the `golem` MCP
server: Blender Lab's `blender_mcp` (GPL-3.0-or-later, vendored as a git
subtree at `blender_mcp/`) extended to serve golem_blender's full tool surface
(`TOOL_SCHEMAS`) through `dispatch_tool`, with the plan gate and a
schema-2 `logs/mcp-*.jsonl` per session.

```sh
make install-mcp-addon         # once: symlink the `mcp` extension into Blender,
                               # enable it, allow online access (its socket needs it)
open -a Blender                # the add-on listens on localhost:9876
claude                         # in this directory; .mcp.json registers
                               # .venv/bin/blender-mcp as server `golem`
```

`.mcp.json` names this machine's absolute path
(`/Users/ladvien/golem_mcp/blender/.venv/bin/blender-mcp`); a checkout elsewhere
must edit it before the server starts. The server is named `golem` because it also
serves every tool of the golem server on big (`GOLEM_REMOTE_URL`, default
`http://192.168.1.110:9786/mcp`), which run there and skip the plan gate.

The add-on executes any code sent to localhost:9876.

**What the agent is told.** Claude Code delivers only the first 2,048
characters of an MCP server's instructions (measured 2026-10-07: golem_blender
sends 24,721). So the instructions open with a must-read head
(`MCP_INSTRUCTIONS_HEAD`, 2,046 characters of the 2,048 allowed; it was
1,981 before OT-50 added the rule that every export ships its .blend, and 2,041
before the grid-layout and interaction-side rules, which replaced the viewport
paragraph's longer wording to stay inside the limit) that condenses
working-agreement revision 10; the full text follows it. A test fails
when the active revision moves, so the head gets reviewed along with it.

**The user's view.** After every scene-changing golem_blender call, the server
frames the objects that call touched in every 3D viewport. Their result
ends with a `viewport:` line saying what was framed, or why nothing was:
background Blender, no 3D viewport, or nothing in the scene yet. An
object made by `add_box` is framed once `link_into_scene` puts it in the
scene. Framing moves the view's pivot and distance; a viewport in camera
view is switched to perspective first. Selection, the active object, the
mode and the view rotation stay as they were.
`make test-viewport-gui` checks the result against Blender's own
projection in a GUI Blender; a window opens for a few seconds.

**Source edits.** Edits under `src/golem_blender` take effect on the next call
without restarting Blender: Blender purges and re-imports `golem_blender` when
the call's source fingerprint changes. What the server loaded at start
stays until the server restarts: tools, descriptions, parameters,
defaults, plan gating (`reads_only`), the outcome wire format, any
`blmcp` edit, and the instructions. Until then the server lists tools,
gates calls and parses outcomes with that start-time code while Blender
runs the edited code.

Restarting on a source edit is opt-in: `--exit-on-source-change`, stdio
only. It is right only for a client that restarts a server that exits.
omp does, and `.omp/mcp.json` gives it its own `golem_blender` entry with the
flag. Measured: omp spawned that entry, not the one in `.mcp.json`. The
server exits once the sources have held still for 2 s, no call is in
flight, and the last response has had 2 s to drain. Before exiting, it
leaves the declared plan and the session-log name in
`logs/mcp-handoff-<client pid>.json`. The client's next server consumes
that file, keeps the plan, and appends to the same log. A handoff older
than 60 s, or a malformed one, is refused on stderr.

Claude Code (`.mcp.json`) and Claude Desktop
(`~/Library/Application Support/Claude/claude_desktop_config.json`, entry
`golem_blender`) run without the watcher, because neither restarts a stdio
server that exits. After an edit to anything loaded at start, run `/mcp`
in Claude Code, or quit and reopen Desktop (⌘Q). Add-on edits
(`blender_mcp/addon`) still need a Blender restart. `.omp/mcp.json` also
disables any same-named `blender` server that omp would import from
another tool's config (e.g. `uvx blender-mcp` in `~/.claude.json`),
since it would talk to the same port.

## Skinned motion (skinclip)

`golem_blender.ops.motion` checks and repairs skinned animation: whether a clip passes its
character through itself (`clip_self_intersection_report`), the body capsules of a humanoid
rig (`body_capsules_report`), a limb repair (`repair_limb_penetration`) and a baked ring of
skirt bone chains (`bake_cloth_chains`). The numerics are the numpy-only package
[skinclip](https://github.com/Ladvien/skinclip), pinned by tag in `pyproject.toml`
(`[tool.uv.sources]`) and installed by `uv sync` into `.venv`. skinclip declares no numpy on
purpose: Blender's bundled numpy serves it, and a numpy wheel in `.venv` would shadow
Blender's (the venv's site-packages come first on Blender's `sys.path`), so keep numpy out of
`.venv`. The op modules import skinclip inside op bodies, so the facade, the MCP server and
`tests/pure` import with no numpy. The ops read the armature's active action and need a UE5 or
Mixamo humanoid for capsules and repair; `docs/2026-09-10-specification-and-requirements.md`
OPS-26 and OPS-27 state what they refuse.

## Dressing a rigged character

A garment on a character is checked the way the engine will draw and animate it:

- `import_rigged_glb` brings in a rigged `.glb` as ONE armature with its bound meshes
  (`<armature>_<mesh>`) and its clips, idempotent by name. `play_clip` poses it with one
  action at one frame, binding the action's OBJECT slot (an unbound slot evaluates nothing
  in Blender 4.4+) and muting NLA, and reports how many bones moved.
- `audit_winding` says which way each face points by the generalized winding number
  (Jacobson et al. 2013), on open shells too. The gate prints a `facing:` line when any
  area faces inward but never fails on it, because a room's walls face inward by design.
- `transfer_weights` copies a body's weights onto a garment where the match is confident
  and inpaints the rest (RSWT, Abdrashitov et al. 2023, thresholds 0.05 x diagonal and
  35 degrees); bind afterwards with `bind_mesh_to_armature(automatic_weights=False)`.
- `clearance_report` measures signed garment-to-body clearance at rest and over every
  frame of the named clips, both ways (garment inside body, body through garment), with
  the worst frame, point and bone. This is where a garment fails on facing.
- `fit_garment` ports `scripts/garment_fit.py`: turn, scale on height, pleat, drape out
  with SHRINKWRAP, orient per component, SOLIDIFY, transfer weights, bind, then run the
  clearance report. A refused fit leaves the garment as it was handed over.
- `silhouette_test` compares two objects' coverage at the game's 55 px character height
  by one ray per pixel centre, culling back faces by each triangle's own winding.
- `render_views` culls back faces by default (`cull=false` shows both sides): Workbench
  culls on the shading flag and EEVEE on the material flag, so the capture sets both.

## Op plugins

An installed distribution can add ops to the facade without a change here:
declare an entry point in the `golem_blender.ops` group naming a module whose
`__all__` lists its op functions (`golem_blender.plugins`).

```toml
[project.entry-points."golem_blender.ops"]
my_ops = "my_package.ops"
```

Plugin ops follow the core ops, satisfy the same contract
(`golem_blender.ops._contract`), and reach the tool schemas, the plan gate and
`search_ops` through `facade_ops()`. A name that collides with an existing
op is refused at import. A plugin must be a package installed into the
`golem_blender` venv, so its entry point is discoverable from Blender
(`uv pip install --python .venv/bin/python -e path/to/plugin`): the MCP
server hands Blender the package's source directory, and a source change
re-imports the plugin together with `golem_blender`. `uv sync` removes a plugin
installed this way; run the install again after it. The test suite sets
`GOLEM_BLENDER_DISABLE_PLUGINS=1`, because the pinned tool-schema fingerprint
describes the core set.

## Run

```sh
make test-pure                 # any machine
make test-blender-app          # build → analyze → render, inside the
                               # installed Blender 5.2 (its own Python
                               # 3.13, bundled numpy, no pip)
make test-mcp                  # the MCP server's unit layer (no Blender)
make test-mcp-blender          # MCP client -> server -> real background
                               # Blender -> golem_blender's dispatch_tool
make test-viewport-gui         # viewport framing in a GUI Blender (opens
                               # a window for a few seconds)
make test-bench-scripts        # tests/bench_scripts in a throwaway env with
                               # numpy, scipy, trimesh and Pillow (numpy, scipy
                               # and trimesh never in .venv; downloads wheels
                               # on first run)
make test                      # pure + Blender app + bench scripts + MCP unit; the gate
make test-repro ARGS="--builder barrel"
                               # build twice in two fresh Blenders under
                               # different PYTHONHASHSEED; identical
                               # semantic digests or exit 1
```

`make test-blender` runs the same Blender-tier suite against a
pip-installed `bpy` wheel instead. It needs a venv whose Python matches
the wheel's (Blender 5.2 is cp313; this repo's `.venv` is 3.11, so
`pip install bpy` there cannot produce 5.2), and a bare run with no
wheel collects nothing and exits 5 — which is not a pass.

The remaining targets (`converge`, `converge-local`, `converge-auto`, `replay`,
`calibrate-eye`, `calibrate-visual-gate`, `pin-golden-views`, `pin`,
`mine-ops`, `bench-3dcode`, `chat-e2e`, `photo-to-model`, `provider-smoke`)
are listed with what each proves in
`docs/2026-09-10-specification-and-requirements.md` §2.4.

## Read

- `docs/2026-08-21-harness-roadmap.md` — the staged plan and design commitments.
- `docs/research/2026-08-20-agentic-blender-game-asset-harness-research.md` — the evidence.
- `docs/2026-09-10-specification-and-requirements.md` — what the system is and must do, with evidence per requirement.
- `BACKLOG.md` / `BACKLOG_DONE.md` — open and closed work on the agent's tool surface.
- `docs/2026-10-02-mcp-viewport-head-restart-plan.md` — why the MCP server frames, leads with a head, restarts only on request, and hands off its plan.
