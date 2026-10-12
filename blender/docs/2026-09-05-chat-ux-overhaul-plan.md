# Chat UX overhaul — plan (2026-09-05)

> **SUPERSEDED 2026-09-26 (MCP cutover).** D2–D6 and the module interfaces below (`blender_addon/`, `blended.ui`, `src/blended/agent/scene_context.py`) were deleted in `184095f`; D1's plan gate survives as the `declare_plan` tool and the plan requirement (spec AGT-5), shown by the MCP client rather than by a Blender progress bar. See README.md "Chat (Claude Code over MCP)".

Evidence base: `docs/2026-09-05-chat-ux-literature-review.md`. Decisions were chosen by the
user from that review; each is recorded here with the paper that argues for it.

## Decisions (locked)

| # | Decision | Evidence |
|---|---|---|
| D1 | **Plan shown, runs immediately, interruptible.** The agent declares a numbered plan before it touches the scene; a native progress bar advances through it; no approval click. | `10.48550/arXiv.2507.22358` (shared editable plan, progress over steps); `10.48550/arxiv.2604.14228` (≈93 % of permission prompts are approved anyway) |
| D2 | **Rebuilt sidebar + shipped `blended` workspace.** Sidebar stays the home; a workspace arranges viewport + Image Editor + a wide chat sidebar. | `10.1080/10447318.2026.2632170` H-LAN (match the host's design language via its own UI APIs) |
| D3 | **Always send active object + selection summary** as structured context with every prompt. | `10.48550/arXiv.2410.22370` (selection is the second-largest interaction-technique family) |
| D4 | **Paired render thumbnails** — this turn's render beside the previous one, inline, click to enlarge. | `10.48550/arXiv.2604.11082` (reference pairing: +0.32 F1, recall 0.28→0.76) |
| D5 | **One undo step per turn + explicit Revert turn.** | `10.1080/10447318.2026.2632170` H-LAN (undo/redo parity) |
| D6 | **Per-event native collapsible panels** (`layout.panel`); plan, answer and gate verdict always visible. | `10.1109/21.156574` EID (do not force knowledge-level processing) |
| D7 | **Proof = executable heuristic audit + user sign-off.** | repo rule "validation = assertions" |

Non-goals: variant galleries, voice, proactive suggestions, any Rust/PyO3 work.

## Verified Blender 5.2 substrate (`outputs/ui_capability_probe.py`)

- `layout.panel(idname, default_closed) -> (header, body)`; `body is None` when collapsed.
- `layout.progress(text=…, factor=…, type='BAR')`.
- `layout.template_icon(icon_value=…, scale=…)`; `bpy.utils.previews` for arbitrary PNGs.
- `bpy.ops.ed.undo_push(message=…)` exists; `preferences.edit.use_global_undo` gates whether
  script-driven operators push their own steps.
- 19 fixed space types: Python cannot register a new editor, so the sidebar stays the home.

## Module interfaces (locked before implementation)

```python
# src/blended/agent/scene_context.py            — D3, no bpy in the pure half
MAXIMUM_SELECTED_OBJECTS_LISTED = 8

@dataclass(frozen=True)
class ObjectSnapshot:
    name: str; object_type: str
    dimensions_m: tuple[float, float, float]
    location_m: tuple[float, float, float]

@dataclass(frozen=True)
class SceneContext:
    active_object_name: str            # "" when there is no active object
    selected: tuple[ObjectSnapshot, ...]
    mode: str                          # "OBJECT", "EDIT_MESH", …
    total_object_count: int
    frame_current: int

def collect_scene_context(context) -> SceneContext      # bpy; syncs the view layer first
def render_scene_context(context: SceneContext) -> str  # pure; "" when nothing to say
def summarize_scene_context(context: SceneContext, limit: int) -> str  # pure; one panel line
```

```python
# src/blended/agent/plan.py                     — D1, pure
PLAN_TOOL_NAME = "declare_plan"
PLAN_STEP_ARGUMENT = "plan_step"
MAXIMUM_PLAN_STEPS = 8
PLAN_REQUIRED_TOOLS = ("run_python",)
MISSING_PLAN_REFUSAL: str        # what a tool call gets when no plan was declared

@dataclass(frozen=True)
class TurnPlan:
    steps: tuple[str, ...]
    current_step: int = 0        # 1-based; 0 = declared but not started
    def progress_fraction(self) -> float
    def with_step(self, index: int) -> TurnPlan     # clamps into 0..len(steps)
    def status_text(self) -> str                    # "step 2/3"

def parse_plan_arguments(arguments: dict) -> TurnPlan   # raises ValueError, never guesses
def plan_step_of(arguments: dict) -> int | None
def plan_required_for(tool_name: str) -> bool
def encode_plan_event(plan: TurnPlan) -> str            # JSON for the (kind, text) channel
def decode_plan_event(text: str) -> TurnPlan
```

```python
# src/blended/ui/previews.py                    — D4, bpy
class RenderPreviews:
    def load(self) -> None                  # bpy.utils.previews.new()
    def unload(self) -> None
    def icon_for(self, path: Path) -> int    # 0 when unavailable (headless, missing file)

def paired_render_paths(events: Sequence[tuple[str, str]]) -> tuple[Path | None, Path | None]
    # pure: (previous, latest) from the transcript's "render" events
```

```python
# src/blended/ui/turn_undo.py                   — D5, bpy
@dataclass
class TurnUndoGuard:
    """One undo step per turn: push a named restore point, suppress
    per-operator pushes for the duration, restore the preference after."""
    message: str
    def open(self) -> None
    def close(self) -> None
    @property
    def is_open(self) -> bool

def revert_turn() -> bool     # bpy.ops.ed.undo(); False when nothing to undo
```

```python
# src/blended/ui/workspace.py                   — D2, bpy
BLENDED_WORKSPACE_NAME = "blended"
CHAT_SIDEBAR_WIDTH_PX = 420
def ensure_workspace() -> str          # idempotent; returns the workspace name
def workspace_exists() -> bool
```

New transcript event kinds on the existing `(kind, text)` channel: **`plan`** (JSON steps),
**`step`** (1-based index), **`render`** (contact-sheet path). `transcript.EVENT_HEADINGS`
gains a heading for each.

## Phases

1. **Substrate** — the four modules above, each with its own tests, no panel changes.
2. **Loop wiring** — `declare_plan` tool + `plan_step` on the action tools, plan enforcement
   and `plan`/`step`/`render` emission in `AgentSession.send`.
3. **Panel rewrite** — plan card, progress, per-event `layout.panel`, paired thumbnails,
   grounding line, Revert turn; kill the idle redraw.
4. **Workspace + keymap** — `blended` workspace operator, hotkeys printed on the controls
   (`10.1145/2470654.2470735`).
5. **Proof** — heuristic audit assertions in `tests/blender/`, full `make test`, GUI sign-off.
6. **Cleanup** — docs, mistake memory, addon re-install.

## Acceptance

- `make test` exits 0.
- Heuristic audit tests assert: a turn is exactly one undo step; the answer is never pushed
  off-screen by traffic; every event body is collapsible; the plan and progress are drawn
  whenever a plan exists; renders appear as thumbnails; the grounding line names the active
  object; every control is one click or one printed hotkey away.
- `make chat-e2e` passes on the CLI lane (Ollama cloud is currently 502-ing).
- User confirms the panel visually in GUI Blender.

## Outcome (2026-09-05)

All seven decisions shipped. Verified: `make test` **331 pure / 250 Blender, exit 0**;
`make chat-e2e ARGS="--model claude-code:sonnet --vision-model ''"` **6/6** with
`require_plan=True` and **zero** plan refusals across seven turns; a live GUI session drove
three full turns and one revert.

What the GUI found that no headless assertion could:

1. **The `plan` event drew as raw JSON** — it is a message kind, and its text is the plan's wire
   form. Now collapsed like other traffic, with the body decoding into numbered steps.
2. **`icon_for` returned the `ImagePreview` struct, not `icon_id`** — `template_icon` raised,
   `draw()` swallowed it, no thumbnail ever appeared. Headless every icon id is 0, so a
   cache-only test could not see it. Now `int(preview.icon_id)`; measured 1128 live.
3. **The sidebar is 27 rows, not a page** (561 × 1104 px at ui_scale 2.0; `UI_UNIT_Y` is 20 px
   *before* scale). Three successive caps still pushed the prompt box off the bottom — no cap,
   then a cap on source LINES (one paragraph wraps to ten ROWS), then reserves that forgot the
   panel headers. Fixed structurally: the record is its own `DEFAULT_CLOSED` panel, the answer
   is capped by `_answer_row_budget(region.height, …)`, and a finished plan collapses to its
   progress bar.
4. **A dev-mode hot reload dropped the plan and the revert right** — `_hot_reload`'s transplant
   list did not know about the new state.

All four are in `src/blended/evaluate/mistake_memory.py` (52 records, `validate_memory() == []`)
with the assertion that guards each.

Deliberate contract note: `plan_step` is now an optional argument on the five action tools, so
the tool-schema text every lane sees grew by ~40 tokens. A future 3DCodeBench roll is therefore
not byte-comparable with the rolls recorded before this change; `require_plan` stays `False` for
the batch driver so the bench's behaviour is otherwise untouched.
