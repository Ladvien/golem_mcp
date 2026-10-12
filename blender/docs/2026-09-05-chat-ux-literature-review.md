# Chat UX overhaul — literature review and decision surface (2026-09-05)

> **SUPERSEDED 2026-09-26 (MCP cutover).** The in-Blender chat UI this review informed (`blender_addon/`, `blended.ui`) was deleted in `184095f`; the literature below remains a record of the evidence, not a live design input. See `docs/harness_design.md` rows 10 and 16–24 for what was retired or relocated.

**Method.** 34 semantic queries against the home-still corpus (`http://192.168.1.110:7434/search`,
bge-m3, collection `academic_papers`, 9,481 docs), then per-paper digs to pull the measured
findings rather than the abstracts. Every DOI below was answered out of the local corpus this
session. Capability claims about Blender come from `outputs/ui_capability_probe.py` run against
Blender 5.2.0, not from documentation.

This document is the evidence base. It does not choose the design; §5 lists the decisions that
need a human answer, and each option there is traceable to a row in §2.

---

## 1. What the corpus actually says about this exact problem

Two findings frame everything else.

**Creation tasks are the case where human+AI wins.** The preregistered meta-analysis of 106
experimental studies / 370 effect sizes (`10.1038/s41562-024-02024-1`) finds task type
moderates synergy: *decision* tasks were associated with performance **losses**, *creation*
tasks with **gains**, and the creation-task effect is significantly greater than the
decision-task effect. Direction depends on relative competence: when the human alone
outperformed the AI alone, the combined system beat both (synergy g = 0.46, 95% CI
[0.28, 0.66]); when the AI alone was better, human augmentation was large (g = 0.74,
[0.63, 0.85]) but synergy went negative. 3D modelling is a creation task where the user
owns intent and taste and the agent owns routine fleshing-out — the favourable cell. The UI's
job is to keep that division legible, not to maximise automation.

**Review cost is the thing that eats the gain.** In the METR study
(`10.48550/arXiv.2507.09089`), experienced open-source developers working on repositories they
knew well (~10 years old, >1.1M LOC) were measurably **slowed down** by 2025-era AI tooling
while both they and experts *forecast a speed-up*. Perceived usefulness is not evidence.
Consequence for us: every design choice should be scored by how cheaply the user can tell
whether the result is right, not by how much the agent does per turn.

---

## 2. Evidence table

| DOI | What was measured | Consequence for this harness |
|---|---|---|
| `10.48550/arXiv.2410.22370` | Survey of user-guided ("controllability") interaction techniques in generative-AI applications. Taxonomy: **selection** (single, multi, lasso/brush), **system & parameter manipulation** (menus, sliders, explicit feedback), **object manipulation** (drag-drop, connecting, resizing). For conversational UIs the *primary* interaction space is the prompt box and the *secondary* is the chat history / output gallery; the turn-based cadence is the defining constraint. | A chat-only panel uses one technique out of ~14. Blender already ships world-class selection and object manipulation — the overhaul should *wire the existing native techniques into the conversation* rather than add widgets. |
| `10.1080/10447318.2026.2632170` | Heuristics for AI-driven graphical asset generation tools (game-dev practitioners). **H-LAN: match the design language of the host environment** — explicitly including "the ability to undo and redo changes", achieved "through appropriate use of front-end UI APIs within the host software". **H-DAT**: common data formats. Users showed **no preference for interface form** but demanded integration into their existing environment; **generation times up to 10 min were acceptable**; configurability was required. | Direct mandate for bpy-native widgets and for native undo. Also: latency is *not* the problem to solve (10 min is tolerable) — reviewability is. |
| `10.48550/arXiv.2507.22358` | Magentic-UI. Co-planning: the plan is a **sequence of natural-language steps, shared between user and agent, editable in place or by message**, with an explicit *Accept* before execution and a **progress bar over plan steps** during it. Three co-tasking modes: user interrupts agent, agent interrupts user, user verifies and follows up. **Action guards** for irreversible/high-risk actions only — participants judged a guard on "add to cart" unnecessary (P1,P3,P5,P8,P9,P12) and endorsed guards on payment/email (P1,P2,P6,P7). Plans can be *learned* from a completed run and re-used from a gallery. | A plan surface is the single largest missing piece (we have none). Guard scope must be narrow: irreversible scene mutation, not every tool call. |
| `10.48550/arxiv.2604.14228` | Design-space analysis of Claude Code: deny-first permission evaluation, five external permission modes (`default`, `acceptEdits`, `plan`, `dontAsk`, `bypassPermissions`), and the measurement that **users approve ≈93 % of permission prompts**. | Confirmation prompts are rubber-stamped. Gate only what cannot be undone; make everything else undoable instead of confirmable. |
| `10.1145/3742413.3789148` | Five-day in-IDE field study of proactive AI, 18 developers, **5,732 interaction points**. Suggestions triggered at **natural workflow boundaries (especially after commits) were significantly more likely to be accepted**. SUS = **72.8** [64.1, 81.5]. Proactive suggestions were interpreted significantly **faster** than reactive ones (reactive µ = 101.4 s, N = 50; p = 0.0016, Wilcoxon signed-rank). Utility fell when the AI lacked low-level context of the code. Participants demanded control over triggering ("I prefer to use hotkeys where possible or a command"). | If the harness ever volunteers anything, fire only at boundaries (turn end, gate failure, save) and keep the trigger user-controllable. SUS 72.8 is a concrete bar to beat. |
| `10.48550/arxiv.2405.00623` | Preregistered N = 404 experiment on uncertainty expression in LLM-infused search. **First-person** hedging ("I'm not sure") lowers trust intention (2.91) versus control (3.25), while **general-perspective** uncertainty does not (3.36); both reduce overreliance, and accuracy on items the system got wrong still trails the no-AI condition. | The agent should state uncertainty impersonally and attached to a measurement ("silhouette unverified; bbox within 2 mm") — not "I think" / "I'm not sure". |
| `10.1109/21.156574` | Ecological Interface Design (Vicente & Rasmussen). Built on the skills / rules / knowledge taxonomy: the goal is (a) **not to force processing to a higher cognitive level than the task demands** and (b) to support all three levels simultaneously; the level required is a joint function of operator skill and task complexity. | Expert actions (accept, revert, re-run, focus the object) must stay skill-based: one click or one hotkey, no prose reading. Prose is knowledge-level work and must be opt-in. |
| `10.1145/2470654.2470735` | ExposeHK: displaying hotkeys in place "substantially improve[s] the user's transition from a 'beginner mode' of interaction to a higher level of expertise". | Print `⌘⏎`, `⌃↑`, and any new bindings on the controls themselves. |
| `10.48550/arxiv.2601.05016` | Planner-Actor-Critic for agent-augmented 3D content creation, Blender backend, **human as supervisor/advisor** throughout; measured improvements in geometric accuracy, aesthetic quality and task-completion rate over single-prompt agents. | The plan/critic split we already have internally should be *visible*, because that is the structure the user supervises. |
| `10.48550/arxiv.2508.08228` | LL3M (Large Language 3D Modelers). Because the artifact is Blender code, the result exposes **interpretable parameters the user tunes by hand** (geometry/shader nodes); a critic proposes visual fixes and a verification agent checks the fixes actually landed. | Hand edits between turns are a first-class input, not a conflict. The panel must show what the critic looked at and whether its fix landed. |
| `10.48550/arxiv.2506.07982` | τ²-bench, dual-control (user and agent both act on shared state). **No-User mode scores ~0.3–0.4 higher than Default** at low action counts, and performance falls toward zero beyond ~7 required actions. | Ask the user for *decisions*, never for manual sequences mid-turn. Every "please go do X in the viewport" costs measured success. |
| `10.48550/arXiv.2604.11082` | RESP (already cited in `docs/harness_design.md` row 5): supplying a reference frame beside the candidate is worth **+0.32 F1 / +0.12 accuracy** for visual defect detection, mostly by fixing recall collapse (0.28 → 0.76). | Applies to the *human* eye too: showing this turn's render beside the previous accepted render is the measured way to make drift visible. |

---

## 3. Gap list — what the current UI does, and what the evidence asks for

Current state mapped exhaustively (agent `UiMap`, all claims `path:line`). The UI is one file,
`blender_addon/__init__.py` (1,841 lines): 12 bpy classes — 1 Panel, 1 AddonPreferences,
1 PropertyGroup, 9 Operators, **no UIList, no Menu, no sub-panels**.

| Gap | Current | Evidence demanding better |
|---|---|---|
| **No plan surface** | Nothing in the UI shows what the agent intends; `UiMap` §5: "Visible plan: none". | `10.48550/arXiv.2507.22358`, `10.48550/arxiv.2601.05016` |
| **No progress** | One text line, `_status_text()` (:1020) — "Running run_python…". `layout.progress()` exists in 5.2 and is unused. | `10.48550/arXiv.2507.22358` (progress bar over plan steps) |
| **Renders invisible** | `render_views` sends a contact sheet to the model; the panel shows only the eye's *text*. The image is reachable only by opening the Markdown transcript in a Text Editor (:805). | `10.48550/arXiv.2604.11082`, `10.48550/arXiv.2410.22370` (output gallery) |
| **No undo integration** | `ed.undo_push` exists and is never called; a turn leaves whatever `bpy.ops` happened to push. | `10.1080/10447318.2026.2632170` H-LAN (native undo/redo) |
| **Global disclosure only** | One `show_details` bool flips *every* message between one line and full text (:1655, `_COMPACT_KINDS` :965). `layout.panel()` (native collapsible sub-panels) exists in 5.2 and is unused. | `10.1109/21.156574` (don't force knowledge-level processing) |
| **Scene not grounded** | The prompt is text only; the active object and selection are never sent. The user must name objects. | `10.48550/arXiv.2410.22370` (selection is the second-largest technique family) |
| **Flat, capped history** | `transcript` is a list of `(kind, text)` capped at 400 entries (:53), drawn oldest-first with a `visible_messages` slice defaulting to 24 (:1646). No list widget, no per-message state, no search. | `10.48550/arXiv.2410.22370` (history is the secondary interaction space) |
| **No cost/time signal** | No token, cost, or duration counters anywhere (`UiMap` §5). | `10.1145/3742413.3789148` (interpretation time as the metric that moved) |
| **Idle redraw** | `_drain_tool_requests` (:565) tags **every** VIEW_3D area for redraw every 0.15 s forever, busy or not. | engineering defect, not literature |
| **Session dies with Blender** | Transcript lives in a module global + disk log; not in the .blend, no session list (`UiMap` §3). | `10.48550/arXiv.2507.22358` (session navigator, status indicators) |

---

## 4. What Blender 5.2 actually gives us (probed, not assumed)

`outputs/ui_capability_probe.py`, `bpy.types.UILayout.bl_rna.functions`:

- **Available and unused today:** `panel`, `panel_prop` (native collapsible sub-panels inside
  `draw()`), `progress`, `template_icon`, `template_image`, `template_preview`,
  `template_list` (+ `UIList`), `popover`, `separator_spacer`, `prop_tabs_enum`.
- **Already used:** `textbox` (with `initial_visible_lines`, `placeholder`), `box`, `column`,
  `row`, `label`, `operator`, `prop`.
- `bpy.ops.ed.undo_push` exists → a turn can be made exactly one Ctrl+Z.
- `bpy.utils.previews` exists → arbitrary PNGs (our contact sheets) can be shown as panel
  thumbnails. (Headless probe reports `icon_id = 0`: previews need a GUI, so this must be
  verified in the GUI, not in `-b`.)
- **19 space types, fixed.** Python cannot register a new editor, so the chat cannot become its
  own editor type; its home must be a region of an existing space (`VIEW_3D`/`PROPERTIES`/
  `IMAGE_EDITOR`/…) or a GPU overlay drawn into the viewport.
- Region types available to panels include `UI`, `TOOLS`, `HEADER`, `HUD`, `ASSET_SHELF`,
  `EXECUTE`, `FOOTER`.

---

## 5. Decisions that need a human answer

Asked as multiple choice in-session; recorded here once answered.

1. **Turn contract** — plan-then-accept, plan-as-progress with interruption, per-prompt mode, or keep single-shot act-then-review.
2. **Home** — rebuilt sidebar only; sidebar plus a shipped workspace; an alternative full-height home; or a viewport HUD for the live turn.
3. **Scene grounding** — send active object + selection always, behind a toggle, only on deictic prompts, or never.
4. **Evidence display** — inline thumbnails, auto-opened Image Editor, text only, or paired before/after thumbnails.
5. **Reversibility** — one undo step per turn, per tool call, both plus an explicit Revert Turn, or unchanged.
6. **Density / disclosure** — native per-event collapsible panels, the current global toggle, a two-pane list + detail, or always-full.
7. **How "best UX" is proven** — heuristic audit as executable assertions, SUS instrument, timed task benchmark, or all three.

## 6. Non-goals for this overhaul (unless raised)

- Multi-candidate variant galleries (`10.48550/arXiv.2410.22370` §3.2.1 single-selection
  among outputs). Powerful, but it multiplies generation cost per turn and there is no measured
  need for it in this harness yet.
- Voice / full-duplex interaction (`10.48550/arxiv.2409.15594`).
- Any Rust/PyO3 work: no measured UI bottleneck exists.
- Proactive suggestions are **not** proposed as a default. If they are ever added,
  `10.1145/3742413.3789148` fixes the shape: fire only at natural boundaries (turn end, gate
  failure, file save), with a user-controllable trigger.
