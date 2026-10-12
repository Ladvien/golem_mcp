# GPU transcript overlay — shipped (2026-09-06)

> **SUPERSEDED 2026-09-26 (MCP cutover).** The overlay this doc ships (`src/blended/ui/transcript_overlay.py` and the rest of `blended.ui`, with `blender_addon/`) was deleted in `184095f`; the client now shows its own traffic (`docs/harness_design.md` row 24). This doc stays as the record of what was built and measured.

Replaces the `UILayout`-drawn reply stack in the chat sidebar with a GPU-drawn transcript
(`gpu` + `blf` + `SpaceView3D.draw_handler_add`) painted in the 3D viewport. Built,
verified end to end, and SHIPPED ON on 2026-09-06. There is no runtime switch: the
`TRANSCRIPT_OVERLAY_ENABLED` flag that briefly shelved it was deleted on the flip, along
with the off-state hint row and the tests that pinned the off state — see
[The flag, and why it is gone](#the-flag-and-why-it-is-gone).

Supersedes row 24 of `docs/harness_design.md` (which this doc is the long form of) and the
row-budget half of the mistake-memory record `the-sidebar-is-twenty-seven-rows-not-a-page`.

## Why

`UILayout` has no pixel vocabulary. A reply drawn with `label()` is a stack of fixed-height
rows: no padding, no corner radius, no way to ask how wide a string will be, and no way to
scroll — a Blender region cannot be scrolled from Python at all (View2D is read-only through
RNA and 5.2 exposes no scroll operator). So anything unbounded drawn in the sidebar
eventually pushes its own prompt box off the bottom, which is the defect three successive
row budgets each failed to fix (measured 2026-09-05, 2026-09-06).

Painting the replies in the viewport removes the variable-height widget from the region
that holds the composer, rather than budgeting around it. Everything the sidebar still
draws is fixed height.

Evidence for the layout decisions is unchanged from `docs/2026-09-05-chat-ux-overhaul-plan.md`:
the prompt box is the conversational UI's primary interaction space
(`10.48550/arXiv.2410.22370`); pointing time grows with distance and a MOVING target must be
re-acquired before it can be pointed at (`10.48550/arXiv.2308.12515`,
`10.48550/arXiv.1906.00905`); layouts are adapted by interaction cost
(`10.48550/arXiv.2204.09162`); review cost decides whether the agent helped, so the newest
reply is not behind a scroll (`10.48550/arXiv.2507.09089`); match the host environment's
design language, theme included (`10.1080/10447318.2026.2632170`); traffic gets per-event
disclosure rather than one global switch (`10.1109/21.156574`).

Scope was deliberately **read-only rich text**. The composer stays native `UILayout` —
`layout.textbox` supplies IME, clipboard, undo and Ctrl+↑ recall, none of which a GPU
overlay can reproduce.

## Module boundaries

Three modules, split so the arithmetic is testable without a GL context.

| Module | Imports | Owns |
|---|---|---|
| `src/blended/ui/transcript_style.py` | `dataclasses` only | `TranscriptStyle` (frozen), every dimension as a named constant, `scaled(ui_scale)`, `shifted_for_contrast()` |
| `src/blended/ui/transcript_layout.py` | `dataclasses`, `math`, `transcript_style` | wrapping, code bands, line caps, stacking, culling, scroll bounds, `column_rect`, `rounded_rect_vertices` |
| `src/blended/ui/transcript_overlay.py` | `bpy`, `blf`, `gpu`, `gpu_extras` | handler lifetime, theme→style translation, rasterising, the wheel hit test |

The first two are **pure by contract** and are the only two modules in `src/blended/ui/`
that `tests/pure` may import; the package `__init__.py` stays code-free so a pure import
cannot pull in `bpy`. `layout_transcript` takes `measure(text, size_px) -> width_px` as an
injected callable: `tests/pure` passes a monospace-like stub, the runtime and
`tests/blender` pass a real `blf` closure. That seam is why wrapping is measured rather
than estimated — the replaced native path guessed `(width - 34) / (7 * ui_scale)`
characters, which over-wraps short glyph runs and under-wraps capitals with no way to do
better.

Addon side (`blender_addon/__init__.py`):

```python
_OVERLAY_KINDS = ("user", "answer", "error")   # conversation, not traffic
def _transcript_messages()   # _STATE.transcript -> TranscriptMessage, live text last
def _overlay_status()        # (message, too_narrow) for the panel's feedback rows
def _install_overlay()       # register(), and after every library reload
def _remove_overlay()        # unregister(), and before every sys.modules purge
class BLENDED_OT_scroll_transcript   # bl_idname "blended.scroll_transcript"
```

Traffic kinds (`thinking`, `tool`, `result`, `vision`, `reload`, `status`, `context`,
`plan`) enter the overlay only when `show_details` is on; `step` events never do — they
move the plan card. `BLENDED_PT_history` still renders every event through the unchanged
native path.

## Behaviour

- **Column.** Right-aligned against the sidebar, `min(560, max(320, 34 % of available))` px
  wide before UI scaling, margin 16. `column_rect` returns `None` when the viewport is too
  narrow for readable prose, and the panel says so rather than drawing a sliver.
- **Order.** Newest at the top, older receding downward, capped at 12 messages.
- **Caps.** 40 rows for the newest message, 6 for the rest, then
  `… N more lines — open Conversation` — the literal is shared with `_draw_body` so the
  overlay and the record cannot disagree about where the rest went. The note sits on the
  side the hidden rows are on: below a head-kept message, above a tail-kept one.
- **Streaming.** The live reply is appended last with `prefer_tail=True` and is capped by
  what the COLUMN can show, so the block cursor is always the last visible row.
- **Code.** A ` ``` `-fenced run keeps its own line breaks, draws at the code size over a
  darker band inset from the bubble edge, and drops the fences.
- **Scrolling.** Wheel over the column moves the stack (`SCROLL_STEP_PX = 60`, clamped to
  `[0, max_scroll]`); anywhere else the operator returns `PASS_THROUGH` and the wheel keeps
  zooming the viewport. A new message returns the stack to the top.
- **Scoping.** The overlay paints only where `region.active_panel_category == "blended"` on
  the area's `UI` region — i.e. the viewport the user put the chat in. No preference toggle
  was needed for scoping.
- **Theme.** Bubbles, body text, label text and scrim come from `themes[0]`; the code band
  is derived from the agent bubble; only the error bubble is an absolute constant (the theme
  exposes no error-widget colour).
- **Failure.** `_draw` wraps everything after the area check in `try/except`, stores the
  formatted error in `LAST_DRAW_ERROR` and returns — a draw handler that raises spams the
  console every frame and can wedge the viewport. The panel draws that error as an alert
  row, so nothing is actually swallowed.

## Verified Blender 5.2 substrate

Blender 5.2.0 LTS, hash `fbe6228777e7`. Probed 2026-09-06.

- `blf` works in `--background`: `blf.size(0, 12)` then `blf.dimensions(0, "Hello world")`
  → `(64.0, 9.0)`. Real proportional-font metrics with no window, so the layout engine is
  testable headless.
- `gpu.shader.from_builtin(...)` raises `SystemError` in `--background`. It is the ONLY
  piece needing a GL context — built on first draw, never at import.
- `SpaceView3D.draw_handler_add(cb, (), "WINDOW", "POST_PIXEL")` and
  `draw_handler_remove(h, "WINDOW")` both succeed in `--background`.
- `preferences.system.use_region_overlap` is `True` by default, and the `WINDOW` region's
  width INCLUDES the pixels the sidebar covers. Measured live: window 1466 px, sidebar
  561 px at x 909, column right edge 873 — beside the sidebar, not under it. The inset must
  be `sidebar.width`.
- `preferences.system.ui_scale` reads **0.0** in `--background` (`pixel_size` reads 1.0),
  and 2.0 in the live GUI on this display.
- Theme reads that exist: `themes[0].user_interface.wcol_box.inner` (RGBA), `.text`
  (**RGB, 3 components**), `wcol_regular.inner` (RGBA),
  `themes[0].view_3d.space.gradients.high_gradient` (RGB).
  `themes[0].view_3d.space.back` does **not** exist.
- `bpy.ops.screen.screenshot` returns a frame that LAGS the state which produced it; one
  `bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP")` pass is not enough.

## Verification (2026-09-06)

| Check | Result |
|---|---|
| `make test` | 369 pure (was 340) + 272 Blender (was 255), 0 failed |
| Composer immobility: whole 561 × 1104 px sidebar, one-line vs sixty-line reply | **0 differing pixels** |
| Same diff over the 640 × 1144 px overlay column (sensitivity control) | **577,780 differing pixels** |
| Real turn via `bpy.ops.blended.send_message` (writer `claude-code:opus`) | reply in the overlay; sidebar shows composer, Send, Ready, Settings, Conversation and no reply text |
| Wheel keymap, live | `WHEELUPMOUSE → −60`, `WHEELDOWNMOUSE → +60`; `scroll_by` clamped to `[0, 730]`; at `max_scroll` the oldest bubble lands exactly on the bottom margin |
| Cursor hit test, live region | inside True; left of, right of, and above the column False; False when the sidebar shows another tab |
| Wrapped width vs measured `blf` width | every run fits the inner column at `ui_scale` 1.0 and 2.0 |

Pixel-diff recipe, for reuse: `image.pixels.foreach_get` into numpy, compare
`rows[sidebar.y : sidebar.y + sidebar.height] × [sidebar.x : sidebar.x + sidebar.width]`.
Region coordinates are already device pixels — applying a `ui_scale` factor indexes past
the array and silently compares empty slices. Always pair the diff with a band that MUST
differ, or a diff of zero proves nothing.

## Defects the verification caught

All five are recorded with guards in `src/blended/evaluate/mistake_memory.py`.

1. `ui-scale-is-zero-when-preferences-are-not-ready` — `max(ui_scale, 0.1)` read 0.0 as a
   tiny scale, so a 320 px minimum column became 32 px. Non-positive now means 1.0.
2. `a-purged-module-cannot-remove-its-own-draw-handler` — `purge_library_modules()` drops
   the module whose globals hold the `RNA_HANDLE`, so every reload would have stacked
   another handler painting the pre-reload state from pre-reload code. The addon now owns
   the lifetime across both purge sites.
3. `_reload_library`'s import-failure path returned before re-installing, leaving the
   viewport blank with no explanation. It now re-installs on both outcomes.
4. `an-absolute-colour-cannot-contrast-with-a-themed-one` — the default dark theme put
   `wcol_box.inner` at 0.1137, within 0.004 of a code band pinned at 0.11, so the band was
   invisible. It is now derived from the bubble by `CODE_BAND_CONTRAST = 0.10`.
5. `a-stream-capped-by-lines-loses-its-own-cursor` — `prefer_tail` as a truncation rule did
   nothing below the 40-row budget, so a 31-row stream in a 28-row column put its own
   cursor below the fold. Tail-kept messages are now capped by the column.

Plus one process record, `a-screenshot-lags-the-state-that-produced-it`: double-capture and
cross-check every GUI read against an in-session numeric dump. A vision read of a stale
frame reported a missing code band that `layout_transcript(...).texts` proved was present.

## The flag, and why it is gone

The overlay shipped ON on 2026-09-06 and `TRANSCRIPT_OVERLAY_ENABLED` was DELETED in the
same change — flag, off-state hint, both guards, and the two tests that pinned the off
state. A clean cutover on purpose: a switch left in place is a second execution path that
nobody runs and every later change has to keep working.

While it existed the flag was a module constant in `blender_addon/__init__.py`, set to
`False`, read by `_install_overlay()` and `_register_keymaps()`. Three consequences
followed from it being off, and all three are worth keeping on the record:

- **No handler was installed.** `_install_overlay()` removed any existing handler first
  and then returned, so flipping off and reloading really did stop the painting. That
  remove-first order survives the flag's deletion, because it is also what stops a hot
  reload from stacking a second handler.
- **The wheel items were not bound** — and this was the real reason to shelve rather than
  ship. `cursor_is_over_transcript` answered `True` for the column's GEOMETRY whether or
  not anything was drawn there, so a bound wheel item would have swallowed viewport zoom
  over a measured 353 x 868 px strip of empty viewport on every fresh session, before the
  user had sent a single message. **That is fixed rather than avoided:** the hit test now
  shares the emptiness condition `_draw` already used (`_MESSAGES_PROVIDER is None or not
  _MESSAGES_PROVIDER()`), so it answers `False` over an empty column and the keymap binds
  unconditionally. The broad `except Exception: return False` stays — an operator must
  never raise on a wheel event.
- **The pinned surface said where the replies went**, in one fixed-height row. That row is
  deleted with the flag; with the overlay on there is nothing to point at, and the surface
  still draws no reply text at all.

Guards after the flip:
`tests/blender/test_transcript_overlay.py::test_the_wheel_is_not_captured_before_the_first_message`
(the same column-centre coordinates answer `False` with a provider returning `()` and
`True` with one message) and `::test_the_overlay_ships_installed_and_the_wheel_is_bound`
(a real `register()` installs the handler, records no error, and binds the scroll items).
The `addon` fixture no longer sets anything: it exercises the shipped configuration, which
is the point of flipping. `test_the_wheel_is_captured_only_over_the_transcript_column`
gained a registered transcript, because a boundary test whose every answer is `False` for
the emptiness reason would be vacuous.

The pinned surface still does **not** grow a second reply-rendering path — two paths for
the same replies is what the repo's "one path" rule forbids, and re-adding the native
stack is exactly where the measured composer-walks-down-the-panel defect came from.

## Known limitations

- **No monospace face.** Code blocks use font 0 at the code size over a darker band,
  unwrapped and clipped. `blf.load(path)` returns a second font id if a real monospace face
  is wanted later — additive, no redesign.
- **No selection or copy in the overlay.** `TranscriptMessage.index` carries the transcript
  position so a future copy action can address a message; today copying is the record
  panel's `COPYDOWN` button.
- **The label colour equals the body colour** because both derive from `wcol_box.text`. The
  speaker line is legible on its own row; an accent colour would have to be invented rather
  than read.
- **The wheel is captured inside the column.** If that proves disruptive, require `ctrl` on
  the keymap items rather than reintroducing a modal operator.
