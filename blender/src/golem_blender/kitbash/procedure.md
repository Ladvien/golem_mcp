# golem kitbash

Design a kit of modular pieces (walls, floors, bridges, rocks, ...) that snap together, then build it one piece at a time in the user's open Blender through the golem MCP. The units and the aesthetic live in YAML so a later request, or a second kit, builds pieces that fit by construction. Every approved piece ships as a verified `.glb`, **its Blender source `.blend`** (required: without it the piece cannot be edited and re-exported later), a replayable recipe, and evidence that it has no z-fighting.

## 0. Modes and the kit directory

Pick the mode from the files present in the kit directory.

|Mode|Trigger|Does|
|---|---|---|
|Design|no `kit.yaml` at the kit dir|interview -> `units.yaml`, `style.yaml`, `kit.yaml`, baked textures; then offers Build|
|Build|`kit.yaml` exists with `planned` pieces|builds the next `planned` piece, dispatching on the entry's `source`: built section 6, generated section 6G, assembled section 6A, pack (already approved); demonstrates it, asks for approval, then exports and records it; repeats|
|Compatible kit|user names an existing kit dir|new `kit.yaml` whose `units:` and `style:` point at the existing files (never copied), plus a catalog interview only; then Build|
|Pack|user names a folder of .glb files|`register_kit_pack` -> `kit.yaml` (`source: pack`); confirm `grid_m` from `grid_candidates`; write `units.yaml` with `grid_m`, `storey_m` = the most common height, the rest from the section 3 batch 4 defaults; no `style.yaml`|
|Replay|"rebuild <Piece>" or a stale piece|replays `pieces/<Piece>.yaml` calls, re-measures, compares, and re-exports on request|

Ask for the kit directory at the start; default `./kits/<slug>/` relative to the current working directory. `<slug>` is lowercase `[a-z0-9_]+`, derived from the kit name. Layout:

```
kits/<slug>/
  kit.yaml            # catalog + pointers to units/style
  units.yaml          # only when this kit owns its units
  style.yaml          # only when this kit owns its style
  style_document.md   # the style document, given by the user or written from the interview (section 3.0); style.yaml's document: names it
  textures/<Material>.png   # beside the style.yaml that declares them
  pieces/<Piece>.yaml # replay recipe + measurements, written on approval
  glb/<Piece>.glb
  blend/<Piece>.blend # REQUIRED Blender source of every approved piece (save_blend); a project may name its own source dir
  zfight/             # evidence written by snippet M: <Piece>_views.png, <Piece>_zoom.png, <Piece>_diff_view<N>.png
```

## 1. Preconditions and golem rules

- Run `lsof -nP -iTCP:9876 -sTCP:LISTEN`, then make `list_scene` your first golem call (read-only probe). Nothing listening, or a reply that starts with `PAUSED:`: stop and ask the user to open Blender with the golem add-on. Never start Blender or bpy yourself. A `PAUSED:` can follow a good `lsof` when Blender restarted in between; do not retry in a loop, ask the user. Other clients may share the Blender: re-run `list_scene` if the scene is not as you left it, and never delete objects this skill did not create.
- Call `declare_plan` once per piece (<= 8 steps) before any scene change; a declared plan holds until the next `declare_plan`, so re-declaring per piece is legal. Pass `plan_step` on every scene-changing call.
- `run_python` is allowed only for the snippets in section 9, each with its fixed `reason`. Any other use must name the missing op in `reason`. Never pass `object_name` to a snippet: the gate would measure that object and render a contact sheet, which raises a Pillow `_imaging` ImportError inside Blender on this install (after the snippet already ran).
- Issue dependent calls one at a time. Calls in the same batch run concurrently: a `read` raced the `bash` that wrote its file, and two scene-changing calls can reorder.
- Same failure twice: stop and describe it to the user.
- `add_box`/`add_cylinder` return unlinked objects. `link_into_scene` every object, and the cutter too, before a boolean (`UnlinkedOperand` otherwise).
- Questions go through the `ask` tool: 2-5 options per question, related questions batched, "Other" is added automatically. If `ask` is unavailable, use a numbered list in chat.
- Validate every YAML write by parsing it: `python3 -c "import sys,yaml; yaml.safe_load(open(sys.argv[1]))" <file>`. On failure fix and re-parse before going on. Edit existing YAML with the `edit` tool, not by rewriting it.
- **Every export ships with its `.blend`.** `export_asset` requires `blend_path`; a piece exported any other way (snippet D) is saved with the `save_blend` tool (`object_names`, `blend_path`) right after. Both verify the written file: every object present, triangle counts equal to the live ones. A piece without a verified `.blend` is not approved. If this session's golem has no `save_blend` tool, or `export_asset` takes no `blend_path`, golem is older than the requirement: stop and tell the user. A `.blend` edited by hand after approval is the piece's master from then on (section 8).
- Leave the user's view as found: snippet J saves it before `set_pixel_art_view` and restores it at the end (B10).

## 2. File schemas

`nodes["blended_image"]` and the `blended-kitbash/...@1` schema ids are persisted names in existing kits and materials; they keep the old package name on purpose.

`units.yaml`, the compatibility contract:

```yaml
schema: blended-kitbash/units@1
version: 1                  # bump on ANY edit; pieces record the version they were built against
length_unit: metre          # 1 Blender unit = 1 m
frame:
  up: "+Z"                  # Blender; glTF export maps Blender (x, y, z) -> glTF (x, z, -y)
  front: "-Y"               # the face a viewer sees in Blender; glTF +Z
grid_m: 2.0                 # footprint module; every footprint is a whole number of cells
storey_m: 3.0               # wall / cliff / stair height module
character_height_m: 1.8     # scale figure in previews
snap_tolerance_m: 0.001     # bounds and connector checks
proud_m: 0.015              # min plane gap between same-facing faces of different objects/materials; snippet Z fails any overlap closer than 0.99 * proud_m
thickness:
  wall_m: 0.3
  floor_m: 0.2
openings:                   # asked when Walls or Openings are in the catalog; the units gauge cuts the door
  door: {width_m: 1.2, height_m: 2.2}
  window: {width_m: 1.0, sill_m: 1.0, head_m: 2.2}   # only when windows are in the catalog
stairs:                     # only when stairs are in the catalog
  rise_m: 0.25              # storey_m / rise_m must be an integer (= steps_per_storey)
  steps_per_storey: 12
  run_m: 0.3333             # chosen so steps_per_storey * run_m is a whole number of cells
water_level_m: -0.3         # only when water is in the catalog; top of water tiles
roof_pitch_deg: 40          # only when roofs are in the catalog
pivot:
  default: footprint_centre_base   # pivot at the footprint centre, z = 0
  walls: centreline_on_y0          # walls run along X, thickness centred on y = 0, ends on x = +-length/2
  joints: grid_vertex              # posts/corners centred on the grid vertex they fill
  floors: top_at_z0                # floor slabs span z = -floor_m .. 0; bridge decks too
connectors:                 # vocabulary; pieces store resolved instances in kit.yaml
  wall_end:   {normal_axis: x, spans_m: {y: [-0.15, 0.15], z: [0.0, 3.0]}}
  floor_edge: {normal_axis: x, spans_m: {y: [-1.0, 1.0], z: [-0.2, 0.0]}}   # per cell; scales with cells along y
```

`style.yaml`, the aesthetic:

```yaml
schema: blended-kitbash/style@1
version: 1
document: style_document.md  # the style document this style was taken from (section 3.0)
summary: "one sentence the user approved"
setting: "e.g. damp medieval harbour town"
camera: {kind: isometric, typical_distance_m: 20}   # isometric|top_down|third_person|first_person
references:                  # mood only unless use: shape; never modelled from mood images
  - {source: "/abs/path/or/url", use: mood}
shape_language:
  primary_masses: [2, 6]     # per piece
  min_feature_m: 0.15        # features smaller than this are modelled only if they change the silhouette
  bevel: {mode: none, width_m: 0.02, segments: 1}    # none|small
  round_segments: 8          # add_cylinder/add_lathe segment_count
  irregularity: {mode: subtle, max_tilt_deg: 2.0, max_offset_m: 0.03, seed: 7}   # straight|subtle|wonky
  proportions: "e.g. chunky: trims and frames 1.5x real size"
  silhouette_rules: ["roofs overhang walls by >= 0.3 m", "..."]
  wear: none                 # none|chipped_corners|broken_tops
surfaces:
  swatch_m: 1.0              # one texture image covers swatch_m x swatch_m; grid_m / swatch_m must be an integer
  texture_px: 64             # pixels per swatch
  filter: nearest            # nearest|linear (Image Texture interpolation Closest|Linear)
palette:                     # material NAME is the contract other kits and engines key on
  - {name: Stone, role: "walls, foundations", kind: flat, rgb: [0.55, 0.53, 0.50], roughness: 0.85}
  - name: Brick
    role: "chimneys"
    kind: procedural         # baked at design time to textures/Brick.png, then used as an image everywhere
    rgb: [0.55, 0.25, 0.20]  # Workbench/diffuse colour and the colour the bake must resemble
    roughness: 0.8
    # scale MULTIPLIES the Blender node's own Scale (5): brick 0.4 = 4 bricks across one swatch, 8 rows, tiles seamlessly; 4.0 was 3 px bricks (noise) at 64 px.
    # color_a/color_b are the two brick colours; the mortar is black. Noise and Wave are not periodic, so judge their seam in the tiling preview.
    procedural: {kind: brick, scale: 0.4, color_a_rgb: [0.55, 0.25, 0.2], color_b_rgb: [0.35, 0.33, 0.3]}
    image: textures/Brick.png
  - {name: Planks, role: "bridge decks", kind: image, rgb: [0.45, 0.32, 0.2], roughness: 0.9,
     source_image: "/abs/original.png", image: textures/Planks.png}
budgets:                     # triangles per piece; every material object is ALSO <= 2000 (golem default gate)
  tile: 50
  wall: 300
  joint: 150
  opening: 400
  stairs: 400
  bridge: 600
  roof: 400
  fence: 200
  terrain: 400
  rock: 150
  plant: 400
  water: 50
  prop: 300
  trim: 100
```

`kit.yaml`, the catalog:

```yaml
schema: blended-kitbash/kit@1
name: "Harbour Walls"
slug: harbour
units: units.yaml            # or ../other_kit/units.yaml (compatible kit; never copied)
style: style.yaml            # or ../other_kit/style.yaml
palette_additions: []        # same entry shape as style.palette; for materials only this kit needs
compatible_with: []          # other kit dirs whose approved .glb pieces join assembly previews
shelf_pitch_m: 8.0           # spacing of approved pieces on the shelf row (computed, see B9)
catalog:
  - name: Wall_Straight      # CamelCase_With_Underscores, unique within the kit and its compatible kits
    family: walls
    class: wall              # key into style.budgets
    footprint_cells: [1, 0]  # x, y cells; 0 = thickness-only axis
    size_m: [2.0, 0.3, 3.0]  # resolved Blender-frame extents the built piece must measure
    bounds_min_m: [-1.0, -0.15, 0.0]
    bounds_max_m: [1.0, 0.15, 3.0]
    materials: [Stone]
    budget_tris: 300
    underside_visible: false # true for bridge, roof, stairs and anything floating (bounds_min z > 0): then coplanar undersides FAIL and the below-ground view is rendered
    connectors:              # resolved: plane position and spans the piece must show on that plane
      - {side: "+x", profile: wall_end, plane_m: 1.0, spans_m: {y: [-0.15, 0.15], z: [0.0, 3.0]}}
      - {side: "-x", profile: wall_end, plane_m: -1.0, spans_m: {y: [-0.15, 0.15], z: [0.0, 3.0]}}
    assembly:                # what the assembly preview places beside it (approved pieces only)
      - {piece: Wall_Straight, offset_m: [2.0, 0.0, 0.0], yaw_deg: 0}
    notes: ""
    status: planned          # planned|approved|skipped|stale
    source: built            # built|generated|pack|assembled; absent means built
    reference: {query: "wooden barrel harbour", saved: [openverse_dc68c275-69eb-470a-a8e0-305b7420585f], path: restyle}   # generated: ids from references.yaml; path: restyle|direct
    glb: /abs/piece.glb      # pack: the piece's file; register_kit_pack writes it with size_m, bounds_*_m, triangles and materials
    parts: [{kit: ../other_kit, piece: Wall_A, offset_m: [0.0, 0.0, 0.0], yaw_deg: 0}]   # assembled: pieces of other kits or packs placed by offset
```

`pieces/<Piece>.yaml`, the replay recipe and measurements:

```yaml
schema: blended-kitbash/piece@1
piece: Wall_Straight
kit: harbour
units_version: 1
style_version: 1
approved: 2026-10-09
calls:                       # every golem MCP call that built the piece, in order, minus plan_step and declare_plan
  - {tool: add_box, args: {name: Wall_Straight__Stone, width_m: 2.0, depth_m: 0.3, height_m: 3.0, location_m: [0, 0, 0]}}
  - {tool: link_into_scene, args: {object_name: Wall_Straight__Stone}}
  - {tool: assign_material, args: {object_name: Wall_Straight__Stone, name: Stone, base_color_rgb: [0.55, 0.53, 0.5], roughness: 0.85}}
measured:
  bounds_min_m: [-1.0, -0.15, 0.0]
  bounds_max_m: [1.0, 0.15, 3.0]
  triangles: {Wall_Straight__Stone: 12, total: 12}
  connectors: {"+x": ok, "-x": ok}
  zfight: {static_same_facing: 0, static_underside_warn: 0, metamorphic_worst_px: 0, views: 5, underside_checked: false}
export:
  glb: glb/Wall_Straight.glb
  blend: blend/Wall_Straight.blend   # the save_blend report's path; objects and triangle counts verified
  gltf_min_m: [-1.0, 0.0, -0.15]
  gltf_max_m: [1.0, 3.0, 0.15]
  materials: [Stone]
  images: 0
master: recipe              # recipe|blend; blend once the .blend was edited by hand (section 8)
generation: {reference_id: openverse_dc68c275-69eb-470a-a8e0-305b7420585f, path: restyle, image_tool_call: {tool: generate_image, args: {}}, mesh_tool_call: {tool: generate_3d, args: {}}, published_to: /mnt/codex_fs/game_assets/models/gen_ai/props/<output_name>}   # generated pieces only; path: restyle|direct
```

Recipe rule: record the literal numbers actually sent, never expressions. `run_python` calls are recorded with their full `source` and `reason`. Do not record failed or undone calls. If a revision removed and rebuilt an object, the recipe holds only the final sequence; to get that, rebuild from the first changed object onward rather than patching in place.

Generated pieces: `generation:` records where the mesh came from, and `calls` start at `import_generated_asset` with the literal arguments sent. Replay re-imports the immutable published GLB (`published_to` in `generation`); it never calls the image or mesh generators again.

## 3. Design mode (interview -> YAML)

### 3.0 Style document

Before batch 1, ask (`ask`): "Do you have a game style document?" Options: `Yes - give the path (Other)`, `No - interview me`, `Use an existing kit's style`.

- **Path given.** `cp` it to `<kit dir>/style_document.<ext>` and `read` it in full. Extract it into a table with the columns `field | value | where in the document`. The fields: setting, visual target, pillars, camera, character height and scale, palette, shape language (masses, bevel, irregularity, wear, min feature), materials and texel density, budgets, references, and asset list (every object or environment piece the document names or implies). A field the document does not state says `not stated`. Show the table, then run only the batches below that cover the `not stated` fields; the extracted values become the recommended options.
- **Interview.** Run batches 1-8 plus one extra batch, asked right after batch 1: pillars (1-3 short phrases), a one-sentence visual target, and up to 3 reference games (free text). Then write `<kit dir>/style_document.md` with the sections `Visual target`, `Pillars`, `Camera and scale`, `Shape language`, `Palette and materials`, `Budgets`, `Asset list`, `References`, filled from the answers.
- **Existing kit's style.** Compatible mode (end of this section).

Then propose the catalog from the asset list. Each entry gets a family and piece from section 4 and a `source`:

- modular hard-surface pieces that snap together: `built`;
- organic, irregular or hero props (rocks, plants, statues, furniture with curves): `generated`;
- anything a registered pack kit already contains: `pack`, used through an `assembled` entry.

Show it as a table and ask Approve / Edit (edits through Other). In the path flow this table replaces batches 2 and 3; in the interview flow batches 2 and 3 produce the asset list and this step only assigns `source`. `style.yaml` gets `document: style_document.md`.

### 3.1 Batches

Every numeric question offers 3-4 computed options plus the automatic "Other". Mark the recommended option. Ask in these batches, in this order:

1. **Identity and use** (one `ask` batch): kit name (free text through Other, with a suggestion offered), kit dir (default `./kits/<slug>/`), camera kind (`isometric` / `top_down` / `third_person` / `first_person`), and whether this is a new kit or compatible with an existing kit dir. If compatible, switch to Compatible mode.
2. **Families** (one batch of 4 multi-select questions, using the section 4 family groups).
3. **Pieces per chosen family** (one multi-select question per family listing its 5 standard pieces, with Other for extras). Then ask once: "Variants?" with none / 2 of each organic piece (rocks, plants, cliffs) / 3 of each organic piece. Variants are separate catalog entries suffixed `_A`, `_B`, `_C`.
4. **Units** (one batch; ask only the fields the chosen families need). Options: `grid_m` 1 / 2 / 4 (recommended 2); `storey_m` 2.5 / 3 / 4 (recommended 3); `wall_m` 0.2 / 0.3 / 0.5 (recommended 0.3); `floor_m` 0.1 / 0.2 / 0.3 (recommended 0.2). The door is asked whenever Walls or Openings is chosen; stairs, water level and roof pitch use the `units.yaml` example values as the recommended option. Validate before writing:
   - `storey_m / rise_m` is an integer. If not, offer the nearest rise that divides it.
   - `steps_per_storey * run_m` is a whole number of cells, using `run_m = ceil(steps*0.28 / grid_m) * grid_m / steps`.
   - Door width <= `grid_m - 2*wall_m` and door height < `storey_m`.
   - `snap_tolerance_m` is fixed at 0.001 and `proud_m` at 0.015 (not asked).
5. **Units gauge demonstration.** `declare_plan`, then build `KitbashGauge__Floor` (one-cell slab, `add_box(grid, grid, floor_m, location z=-floor_m)`), `KitbashGauge__Wall` (`add_box(grid, wall_m, storey, location (0, grid/2, 0))`) and `KitbashGauge__Figure` (`add_cylinder` radius 0.25, height `character_height_m`, 8 segments, at (0.5, 0, 0)); `link_into_scene` each. When the units have a door, build `KitbashGauge__DoorCutter` = `add_box(door.width, wall_m + 0.2, door.height + 0.05, location (0, grid/2, -0.05))` (it passes 0.05 below the wall base: exactly coplanar faces raise `BooleanNoOp`), `link_into_scene` it, and `boolean_difference` it out of the wall. Then snippet I (CENTRE (0, grid/2, storey/2), distance 3 * grid + storey, elevation 25, azimuth -30), `get_screenshot_of_area_as_image {area_ui_type: VIEW_3D}`, `read` the image, and ask "Units look right?" (Approve / Change values). On approval `remove_object_and_mesh` the floor, wall and figure.
6. **Aesthetic** (one batch): setting (free text), irregularity (`straight` / `subtle` / `wonky`), bevel (none / small), round segments (6 / 8 / 12), detail floor `min_feature_m` (default by camera: isometric and top_down 0.15, third_person 0.05, first_person 0.02), wear (none / chipped_corners / broken_tops), references (paths or URLs, each marked mood or shape). Images under 512 px on the long edge are refused as shape sources.
7. **Budgets**: show the `style.yaml` budget table multiplied by the camera factor (isometric and top_down x1, third_person x2, first_person x4; each piece capped at 2000 x its material count) and ask Approve / Edit.
8. **Palette.** Propose 3-6 materials named after the roles the chosen families need (walls, trim, roof, ground, foliage, metal, water). For each entry ask kind (flat / procedural / image) and colour. Then:
   - When any entry is textured, `surfaces.swatch_m` must divide `grid_m`; otherwise offer to change one of them. Ask `texture_px` (32 / 64 / 128) and `filter` (nearest / linear).
   - Image entries: copy `source_image` into `<style dir>/textures/<Material>.png` with `cp`. If the source is not PNG, convert with `~/golem_mcp/blender/.venv/bin/python -c "from PIL import Image; ..."`; if Pillow is missing there, ask the user for a PNG.
   - Procedural entries: build the swatch with `add_box("KitbashSwatch__<Material>", swatch_m, swatch_m, 0.02, location (swatch_m/2, swatch_m/2, 0))`, `link_into_scene`, snippet C (anchor (0, 0)), `assign_procedural_material(..., name="<Material>__proc", ...)`, then snippet B (bake). `read` the PNG at 4x (`Image.NEAREST`) tiled 2x2: a pattern that is noise at 64 px means `scale` is too high. Re-tune by calling `assign_procedural_material` again (idempotent) and re-baking.
   - Every textured entry gets a tiling preview: snippet J (save), `set_pixel_art_view` (without it the Solid viewport shows flat material colours), `add_box("KitbashTile__<Material>", 2*swatch_m, 2*swatch_m, swatch_m, location (swatch_m, swatch_m, 0))`, link, snippet C, `assign_image_texture_material` with the PNG, snippet H when `filter: nearest`, snippet I, screenshot, and ask Approve / Re-tune. Remove the swatch and tile objects after approval.
9. **Write files**: `units.yaml`, `style.yaml`, `kit.yaml` (catalog resolved per section 5), each parsed with the section 1 check. Show a one-screen summary (units, palette, catalog count by family), then ask "Start building now?" (Yes / Later).

Compatible mode runs only steps 1-3 and 9. It sets `units:` and `style:` to the existing kit's files and `compatible_with: [<existing kit dir>]`. It asks whether new materials are needed (into `palette_additions`, with step 8's bake/preview for textured ones; textures go in `kits/<new>/textures/`). Catalog names must not collide with the compatible kit's catalog.

## 4. Piece catalog (the prompt list)

Family questions (multi-select):
- Structure: Ground & floors, Walls, Joints & pillars, Openings & inserts.
- Connections and cover: Stairs & ramps, Bridges & walkways, Roofs & ceilings, Fences & railings.
- World: Terrain & cliffs, Rocks, Plants, Water & shore.
- Dressing: Props, Trims & greebles.

Standard pieces per family (the per-family question) with the build recipe. Names are prefixes; variants get `_A`/`_B`/`_C`.

Generated, pack and assembled entries keep the family and class of what they are (rock, prop, ...), so the style budgets apply to them unchanged.

|Family|Pieces offered|Class|Size and pivot rule|Build recipe with ops|
|---|---|---|---|---|
|Ground & floors|Floor_1x1, Floor_2x2, Floor_Edge, Floor_Corner, Path_Straight|tile|cells x grid, z -floor_m..0, centre pivot|`add_box` slab at z=-floor_m; edge/corner trims are a second box unioned (overlap >= 0.01) or a second material object proud by `proud_m`|
|Walls|Wall_Straight, Wall_Half (half cell), Wall_Low (half storey), Wall_Ruined, Wall_End_Cap|wall|length cells x grid along X, thickness wall_m on y=0, z 0..storey|`add_box`; trims/base course as extra material objects standing `proud_m` off the faces and stopping `proud_m` short of each connector plane (length - 2*proud_m); Ruined = `boolean_difference` with 2-3 rotated boxes through the top; End cap = wall_m x wall_m post|
|Joints & pillars|Corner_Outer, Corner_Inner, Wall_T, Wall_Cross, Pillar|joint|post (wall_m + 2*proud_m)^2 centred on the grid vertex, z 0..storey; Pillar side 1.5*wall_m|`add_box` post. The four joint pieces differ only in trim on the faces that stay exposed. Walls end exactly on grid vertices, so the post fills the corner notch two meeting walls leave.|
|Openings & inserts|Wall_Door, Wall_Window, Arch, Door_Leaf, Window_Frame|opening|as Wall_Straight; openings centred on x=0 from `units.openings`|Wall box, then `boolean_difference` with a cutter longer than wall_m by 0.1 each side and 0.05 past the base; Arch head = `add_cylinder` cutter rotated 90 deg about X (`rotate_object_euler` + `apply_object_transform`) unioned to a box cutter; Door_Leaf/Window_Frame sized to the opening minus 0.01 per side, pivot base centre|
|Stairs & ramps|Stairs_Straight, Stairs_Landing, Ramp, Ladder, Platform|stairs|width 1 cell, run steps*run_m along +Y, rise storey|One `add_box` per step (height (i+1)*rise, depth run_m + 0.01 overlap), each `boolean_union`ed in order. `linear_array` is forbidden here: its copies self-intersect. Ramp = box then `boolean_difference` with a rotated box; Platform = floor slab raised to storey|
|Bridges & walkways|Bridge_Span, Bridge_End, Bridge_Support, Bridge_Railing, Bridge_Arch|bridge|deck along X, cells x grid long, 1 cell wide, deck top z=0 (flush with floors)|Deck `add_box` at z=-floor_m; railings (posts + rails) as their own material object; Support = box/cylinder from z=-storey to -floor_m; Arch = deck box with `boolean_difference` of a cylinder rotated about Y|
|Roofs & ceilings|Roof_Slope, Roof_Ridge, Roof_Gable_End, Roof_Corner_Hip, Ceiling_Slab|roof|1 cell footprint, pitch `roof_pitch_deg`, base z=0 = wall top|Slope = box rotated about X by pitch, `apply_object_transform`, then `boolean_intersect` with the footprint box; Gable = wall box minus two rotated boxes; Ceiling = floor slab|
|Fences & railings|Fence_Straight, Fence_Post, Fence_Gate, Railing_Straight, Railing_Corner|fence|1 cell along X on y=0, height about 0.5*character_height|Posts `add_box`/`add_cylinder` at +-length/2 (on grid vertices) unioned with rails overlapping >= 0.01|
|Terrain & cliffs|Cliff_Straight, Cliff_Corner_Outer, Cliff_Corner_Inner, Slope, Ledge|terrain|1 cell, top z=0, down to -storey|Box then 3-5 `boolean_difference` cuts with boxes rotated within `irregularity` limits on the exposed face only; connector faces stay flat|
|Rocks|Rock_Small, Rock_Medium, Rock_Large, Rock_Cluster, Rubble_Pile|rock|S/M/L about 0.25/0.5/1.0 x grid, base z=0 (sunk 0.02)|Box intersect/difference 3-6 rotated boxes (facet cuts); angles from `irregularity.seed`, recorded as literals; Cluster = 2-3 rocks unioned|
|Plants|Tree, Tree_Dead, Bush, Grass_Tuft, Log_Stump|plant|base z=0 centre|`add_lathe` trunk (all radii > 0, apex ring 0.02) as one material object; canopy `add_lathe`/`add_cylinder` with `round_segments` as another|
|Water & shore|Water_Tile, Shore_Edge, Shore_Corner, Dock_Plank, Pier_Post|water|1 cell; water top at `water_level_m`|Thin `add_box` at water level; shore = ground slab with a `boolean_difference` bevel cut toward the water side|
|Props|Crate, Barrel, Lamp_Post, Sign, Bench|prop|base centre, sized against character_height|Primitives + unions; Barrel = `add_lathe`|
|Trims & greebles|Beam, Ledge_Trim, Pipe, Buttress, Banner|trim|snaps to wall faces: back face at y = -(wall_m/2 + proud_m) or front at +(wall_m/2 + proud_m)|Single box/cylinder/lathe|

General modelling rules:
- Objects are named `<Piece>__<Material>`. The FIRST material in the catalog entry's `materials` is the body: it alone defines connectors (snippet F measures connector cross-sections on the body only), so trims may stand `proud_m` off the body's faces without failing the joint check. Every other piece in the kit carries the same trims at the same heights, which keeps neighbouring trims continuous.
- Apply every object's transform before measuring (`apply_object_transform` after any `move_object_to`/`rotate_object_euler` on a base primitive).
- Unions overlap by at least 0.01 m. Cutters pass fully through, extending at least 0.05 m past each face, base included.
- Booleans consume their operand and keep only the target's material slots, so multi-material means one object per material. `linear_array` bakes copies into one mesh; copies that do not touch become separate components and overlapping ones self-intersect, so either fails the default gate.
- **No z-fighting by construction.** Two faces that face the same way, overlap, and lie less than `proud_m` apart in plane z-fight, so the colour that wins flips with the camera. Never make them: (1) a trim or cap that runs to a connector plane would share the body's end face, so it stops `proud_m` short of that plane (a 2.0 m wall gets a 1.97 m base course); this was the z-fight in the smoke run, visible as brick speckle on the end of a stone base course; (2) a trim standing off a face stands exactly `proud_m` off (or deeper), never flush; (3) a second material that has to sit flush is embedded in the body's volume and stands proud on the visible faces only; (4) when a hidden duplicate face is the only conflict, delete the face (an extra boolean) instead of lifting it. Coincident faces across a join (neighbour end faces, back to back) face opposite ways and are fine. A face on the piece's lowest plane facing down is an underside: it is hidden by the ground and only a warning, unless the entry says `underside_visible`.
- `add_bevel` + `apply_all_modifiers` only when `bevel.mode: small`.
- Irregularity: tilt each secondary primitive by <= `max_tilt_deg` and offset it by <= `max_offset_m`, from a sequence derived from `seed` and the piece name. The literal values go into the recipe. Connector faces and footprint extents are never perturbed.
- `export_asset` cannot ship a multi-material piece (one object, root node must equal the object name, one-component gate); pieces export through snippet D, then `save_blend` writes their `.blend`.

## 5. Resolving a catalog entry (written into kit.yaml at design time)

- `size_m`: X = cells_x * grid (walls/fences/bridges), or post size for joints. Y = cells_y * grid, or wall_m for thickness-only axes. Z = per family rule.
- `bounds_min_m` / `bounds_max_m` are the BODY object's bounds (the first material), computed from `size_m` plus the pivot rule (centred X/Y; Z from the family rule, e.g. floors -floor_m..0, cliffs -storey..0). Trims may exceed them by `proud_m` plus their own depth across the faces and stop `proud_m` short of the connector planes; joint bounds of all objects are recorded in the recipe, not checked against the catalog. Organic classes (rock, plant) store `size_m` as a target only, with bounds tolerance 15 percent instead of `snap_tolerance_m`. Every other class must hit body bounds within `snap_tolerance_m`.
- `connectors`: walls, openings and fences get `wall_end` on +-x. Floors, bridges, water, terrain and paths get `floor_edge` on every side that has a neighbour (+-x and +-y, with the span along the edge scaled to the cells). Joints, rocks, plants, props and trims get none.
- `underside_visible`: true for bridge, roof and stairs classes and for any piece whose `bounds_min_m` z is above 0.001; false otherwise.
- `assembly` defaults: walls and openings get a Wall_Straight at +grid on X and a joint at the shared vertex if one is in the catalog. Floors get a 2x2 arrangement of themselves. Bridges get Bridge_End at each end and a Floor_1x1 beyond. Stairs get a Platform at the top. Everything else gets the character figure beside it. A layout entry naming the piece under test places copies of that piece (snippet G, own object names). Entries naming other pieces are placed only when those are `approved` or come from `compatible_with` kits; the rest are skipped. The piece under test itself always stays at the origin; assembly offsets are always +X/+Y.

## 6. Build mode: one piece at a time

- **B0. Load.** `read` kit.yaml, units.yaml, style.yaml (and `palette_additions`). Parse-check them. If a `pieces/*.yaml` has `units_version` or `style_version` different from the current files, set that catalog entry to `stale` and tell the user (offer Replay per section 8). Pick the first `planned` piece in catalog order. Before the first piece of a session, run the z-fight canary (Z-fight protocol, step 1).
- **B1. Plan.** Show the resolved entry (size, bounds, connectors, materials, budget, recipe idea from section 4) in 6 lines or fewer. `declare_plan` with <= 8 steps: one per material object, then measure, look, show, export+record.
- **B2. Build** each material object with ops per section 4. Keep an in-memory call log of every successful call for the recipe.
- **B3. Surface.** Flat entries: `assign_material(name, rgb, roughness)`. Textured entries (procedural ones are already baked to PNG): snippet C with anchor = the piece's `bounds_min_m` (x, y), then `assign_image_texture_material(object, <Material>, <abs png>)`, then snippet H when `filter: nearest`.
- **B4. Measure** with snippets F and Z over all the piece's objects (body first). Compare against the entry:
  - `body_bounds_*` within tolerance of the entry's `bounds_*` (joint `bounds_*` are recorded only);
  - every connector `ok`;
  - total tris <= `budget_tris`, and each object <= 2000;
  - material names within palette + `palette_additions`;
  - snippet Z: `fail_same_facing == 0` (and no `underside` entries when `underside_visible`);
  - every object passed the gate (verdict of its last gated call, or `inspect_object`).

  Any failure is fixed before showing (critique rounds <= 3). Each critique names the feature and the number, e.g. "bounds max z 3.04, expected 3.00" or "Wall_Straight__Brick and __Stone: same-facing overlap on plane x = 1.0, gap 0.0".
- **B5. Look.**
  1. Textured piece: snippet J (save), once per session, then `set_pixel_art_view`; it overwrites scene display settings and the Solid viewport colour type without restoring them.
  2. Z-fight metamorphic and visual check: snippet M (Z-fight protocol, step 3). `read` `<OUT>_views.png` and `<OUT>_zoom.png`.
  3. `render_views(<largest object>, look_for=<one named feature>)`, and again with `xray: true` when the piece has more than one material object. If it raises a Pillow `_imaging` ImportError (this install's golem venv), skip it: the views sheet from step 2 plus snippet I screenshots replace it.
  4. Scale figure: `add_cylinder("KitbashPreview__Figure", 0.25, character_height_m, 8, location (bounds_min_m.x - 0.5, 0, 0))` + `link_into_scene` (the -X side is free because assembly offsets are +X/+Y). Run snippet G (assembly preview), then the assembly z-fight checks (protocol step 4), snippet I framing the assembly, `get_screenshot_of_area_as_image {area_ui_type: VIEW_3D}`, `read` the screenshot. Textured pieces: snippet K to a file, crop 260 px around a joint, `Image.NEAREST` x3, `read` it, and check the texture phase continues across the joint. Then snippet G-cleanup and `remove_object_and_mesh("KitbashPreview__Figure")`. Preview calls are not recorded in the recipe.
- **B6. Demonstrate.** Post the compliance table (check | expected | measured | ok), including the rows "z-fight static (Z): 0 same-facing" and "z-fight metamorphic (M): worst diff px over V views", the render, views sheet, zoom sheet and screenshot, and the tri count. Say in one sentence what you saw at each junction in the zoom sheet. Ask: Approve / Skip piece / Stop here; typed Other = revision request.
- **B7. Revise.** Apply the request by rebuilding from the first affected object (`remove_object_and_mesh` it and its successors, rebuild, re-log), then back to B4. Re-check each earlier critique by name and re-run the whole z-fight protocol: a fix to one critique can regress another, and moving one face can create a new coplanar pair (LL3M). After 3 revision rounds on one piece, ask whether to continue revising, approve as is, or skip.
- **B8. Skip.** `remove_object_and_mesh` the piece's objects, set `status: skipped`, continue with B0.
- **B9. Approve.**
  1. Snippet D exports `glb/<Piece>.glb` (a single-object piece prints a harmless "No mesh data to join").
  2. `save_blend(object_names=<the piece's objects>, blend_path=<abs kit dir>/blend/<Piece>.blend)`. Its report must list every `<Piece>__<Material>` object with the triangle counts snippet F measured. A missing report or a mismatch is a failure, fixed before recording.
  3. Run snippet E on the host and check: roots == [Piece]; tris == the measured total; material names == the piece materials; images == the count of textured materials; inverted == 0; `gltf_min/max` == the Blender bounds mapped (x, z, -y) within 1e-4; and when `filter: nearest`, every sampler `magFilter == 9728`. Any mismatch is a failure, fixed before recording.
  4. Write `pieces/<Piece>.yaml` (section 2, with `measured.zfight`, `export.blend` and `master: recipe`) and set the kit.yaml entry to `status: approved`. Parse-check both files.
  5. Shelve the piece: `move_object_to` every material object to `(i * shelf_pitch_m, shelf_pitch_m, 0)`, i = count of previously approved pieces, `shelf_pitch_m` = largest catalog `size_m` X or Y + grid_m (written to kit.yaml once).
  6. Continue with B0 for the next piece.

  A project that builds its committed files headless from a code recipe (Sanctuary: `tools/blended/build_kit_models.sh`, see its AGENTS.md "Model sources") replaces steps 1-2 with that build, and the build itself must write the `.blend` (Sanctuary: `game_assets/models/kit/<Piece>.blend`, Git LFS). The requirement is the same: no committed `.glb` without its `.blend`. Record the project's paths in `export.glb` and `export.blend`.
- **B10. Stop/finish.** Snippet J (restore) if it was saved. Report approved, skipped, remaining and stale counts, the kit dir, the `.glb` and `.blend` written this session, and the objects left in the scene (the shelf row).

### Z-fight protocol

A piece passes only when every step holds. Both detectors were proven live: they fail a base course that shares the body's end faces (static: 8 same-facing triangle pairs; metamorphic: 99 to 762 differing pixels per side view; the zoom sheet shows brick speckle) and pass the same wall with the course stopped `proud_m` short.

1. **Canary, once per Blender session, before the first piece.** Build `KitbashZprobe__A` = `add_box(1, 1, 1, location (0, 0, 0))` and `KitbashZprobe__B` = `add_box(1, 1, 0.5, location (0, 0, 0))` (their side faces are coplanar), link both, give them different flat colours with `assign_material`. Snippet Z must report `fail_same_facing > 0` and snippet M (CENTRE (0, 0, 0.5), RADIUS_M 0.9, LOOK_AT [(0.5, 0, 0.25)]) must return `ok: false` (measured: 12 pairs, 37k to 62k px per side view). Then remove both objects and their materials (`KitbashZprobe_A`, `KitbashZprobe_B`). If either check passes the canary, it is blind: stop and tell the user.
2. **Static (Z)** on the piece's objects: `fail_same_facing == 0`. `underside` entries are warnings, failures when `underside_visible`. `opposite_facing` entries are reported only.
3. **Metamorphic (M)** on the piece alone, before snippet G: `ok: true`. The relation: shifting an orthographic camera along its own axis must not change the picture, but it changes depth quantisation, so any z-fighting pixel flips. `CENTRE` and `RADIUS_M` come from snippet F (centre and half-diagonal of `bounds_*`); `OUT` = `<kit dir>/zfight/<Piece>` (create the dir); `INCLUDE_UNDERSIDE` = the entry's `underside_visible`. `LOOK_AT` = one world point at every junction: the middle of each end of every non-body object, where a trim meets the body top, each opening edge, each joint post face (wall example: (-1, 0, 0.2), (1, 0, 0.2), (0, -0.165, 0.4), (0, 0.165, 0.4)). Pass = every view has `diff_px <= 4` (one or two stray silhouette pixels are rasteriser noise) and `covered >= 0.02` (an empty render cannot pass).
4. **Assembly.** After snippet G, run Z with the piece's objects plus the `__preview` copies, and run M over the assembly (CENTRE and RADIUS_M of the combined bounds, `OUT` = `<kit dir>/zfight/<Piece>_assembly`) when the piece has more than one material object or its assembly places neighbours.
5. **Visual inspection.** `read` the views sheet and the zoom sheet (`covered` and the black filler tile in the views sheet are padding). Any speckle, flicker, shimmer or bleed-through at a junction fails the piece even when M passed: M cannot see a fight whose winner is the same at every shift. Check at least two scales of every junction: the zoom sheet and the 3/4 screenshot.
6. **On failure** the critique names the two objects, the plane (`plane_d` and `at` from Z), the view and pixel box (`box` from M) and the zoom tile; fix by the section 4 rules and re-run steps 2-5 in full. If M raises, stop and report: do not skip the z-fight check.

## 6G. Generated pieces (catalog `source: generated`)

For organic, irregular or hero pieces: a reference image from the web, restyled in the game's style or used as is, becomes a mesh through TRELLIS. Tools: `search_reference_images`, `save_reference_images` (no Blender, no plan), `generate_image`, `generate_3d` (run on the GPU machines, no plan), `import_generated_asset` (changes the scene: it needs the piece's plan).

1. **Search.** `search_reference_images(query=<the entry's reference.query, default "<piece noun> <setting>">, count=24)`. Show the contact sheet and say which sources were skipped and why (`skipped_sources`). Ask a multi-select with the options `1`..`N`, in groups of up to 5 per question, plus `Search again (Other: new query)` and `Skip piece`.
2. **Save.** `save_reference_images(search_id, numbers, kit_slug)`; the files land under `~/mnt/codex_fs/game_assets/references/<kit slug>/` (big sees them as `/mnt/codex_fs/...`). Record the returned ids in `reference.saved`.
   - A license of `unknown`, `by-nc*` or `by-nd*`: show the license and the landing URL, and ask "Use for a mesh anyway?" (Yes / Pick another). Meshing a picture is a derivative work, which NC and ND do not allow.
   - `too_small_for_shape: true`: say so and recommend restyle.
3. **Path, per saved image.** Ask "Restyle in the game's style first, or straight to TRELLIS?" (Restyle first / Straight to TRELLIS / Skip image).
4. **Restyle.**
   - `generate_image(prompt="<piece description>, a single isolated object centred and filling 70-80% of the frame, plain light grey background, soft even light from above-front, three-quarter view about 35 degrees around and 15 degrees above, <style.yaml summary>, <shape_language.proportions>, colours <palette names and roles>", model="flux2-klein-9b", image_path=<the saved entry's big_path>, image_strength=0.4, width=1024, height=1024, seed=<n, start 1>)`.
   - Show the result: `read` `<reference_dir with /mnt/codex_fs replaced by ~/mnt/codex_fs>/reference.png`.
   - Ask Approve / Retry (seed + 1) / Closer to photo (strength - 0.1, minimum 0.1) / Freer (strength + 0.1, maximum 0.8) / Straight to TRELLIS instead.
5. **Mesh.** `generate_3d(image=<the generate_image local_path, or the saved entry's big_path for direct>, output_name="<kit slug>_<Piece>_<unix time>", asset_type=<"environments" for classes terrain, rock, plant and water, else "props">, decimation_target=max(2000, 4 * budget_tris), source_prompt=<the restyle prompt, or the reference's title>, source_image_model=<"flux2-klein-9b", or "web reference: <source>">)`. Its `published_to` directory is immutable; the GLB is `<published_to>/asset.glb`.
6. **Import.** `declare_plan`, then `import_generated_asset(glb_path=<published_to>/asset.glb, object_name="<Piece>__Generated", height_m=<the entry's size_m z>, triangle_count=<budget_tris>)`. It takes the big path as returned and reads it through the Mac mount.
   - Orientation: run snippet I and take a screenshot. If the piece's front is not facing -Y, `rotate_object_euler` + `apply_object_transform`, and record both calls.
7. **Measure, look, demonstrate, approve** per B4-B9 of section 6, with these differences:
   - bounds tolerance is 15 percent (the organic rule of section 5), and the report's `extents_m` and `bounds_min_m` are the numbers;
   - the palette check is replaced by "materials recorded" (the report's `material_names`, written to `kit.yaml`);
   - no connectors;
   - export through snippet D + `save_blend`: `export_asset`'s one-component gate rejects generated meshes.

`pieces/<Piece>.yaml` gets `generation:` (section 2); its `calls` start at `import_generated_asset`, so Replay re-imports the immutable published GLB instead of calling the generators again.

## 6A. Assembled pieces (catalog `source: assembled`)

A new asset built from pieces that already exist: approved pieces of this or a compatible kit, or the pieces of a registered pack (`register_kit_pack`). The parts stay unmodified; booleans and new primitives add what the parts lack.

1. `read` the `kit.yaml` of every kit named in `parts[].kit`. A part's GLB is `<that kit dir>/glb/<piece>.glb`, or the pack entry's `glb:` for a `source: pack` piece. Read `pack.license` too: Kenney packs are CC0; Quaternius packs (QAL v1.0) forbid redistribution, so their GLBs stay out of anything published.
2. `declare_plan` (<= 8 steps).
3. For each part:
   - the first use of a piece: `import_glb_piece(glb_path=<its GLB>, object_name="<Asset>__<Piece>")`, then `move_object_to` + `rotate_object_euler` to the part's `offset_m` and `yaw_deg`;
   - later uses of the same piece: `duplicate_object(object_name="<Asset>__<Piece>", new_name="<Asset>__<Piece>_<k>", location_m=<offset_m>, z_rad=<radians(yaw_deg)>)` with k = 2, 3, ...: each copy has its own mesh data, so a boolean on one cannot change the others, and each copy drops the source's parent so `location_m` is its WORLD location (pass `keep_parent=True` only when the part genuinely stays a child of the piece, and read `location_is_parent_relative` in the report).
4. Booleans and new primitives follow the section 4 rules. `import_glb_piece` counts components and boundary edges as imported (glTF stores vertices per face), and a boolean is gated like any other: a piece whose geometry is split or open fails that gate until it is welded (`weld_and_dissolve`) or left untouched.
5. The recipe records every call.
6. Measure with snippets F (body = the first part) and Z over all the part objects; look (B5); approve (B9, with snippet D joining all parts into one node `<Asset>`).

## 7. Textures across the kit

All textured surfaces use snippet C's world-anchored box projection: 1 UV unit = `swatch_m`, anchored at the piece's footprint min corner. Pieces snap on a grid that is a whole multiple of `swatch_m`, so the texture phase is identical on every piece and across compatible kits (verified live: a checker continued across the joints of a 2x2 floor with no phase jump). Faces pointing -X/-Y show the swatch mirrored, which tiling materials tolerate. Do not use `unwrap_uvs` CUBE_PROJECT: it works in object-local coordinates, so the phase would depend on the pivot.

Procedural entries exist in Blender only as `<Material>__proc` on the swatch object. Pieces only ever get the baked `<Material>` image material, so what the user approves is what ships (glTF exports a base colour only from an unconnected colour or an Image Texture node).

## 8. Replay mode

`read` `pieces/<Piece>.yaml`, `declare_plan` (group the calls into <= 8 steps), remove any existing objects named `<Piece>__<Material>` (only the shelved originals of this piece, not `__preview` copies), and execute `calls` in order with each tool and its args (dependent calls one at a time). Then run snippets F and Z and compare against `measured`: tris equal, bounds within 1e-4, z-fight counts equal. Verified live: replaying the 8 recorded calls of Wall_Straight reproduced triangles (12, 12, 24) and bounds exactly. If the user asked, re-export via B9 steps 1-2 and rewrite `export`. A stale piece cannot be replayed into compliance, because recipes are literal: say so and offer to rebuild the piece under the new units through B1-B9.

A piece whose `pieces/<Piece>.yaml` says `master: blend` (its `.blend` was edited by hand after approval) is never replayed from `calls`: the recipe no longer describes it. To change it, open or append its `.blend`, edit the `<Piece>__<Material>` objects in place (names, one object per material and identity transforms kept), then re-export through B9 steps 1-3 and save the edited file back over the `.blend`. When a user hand-edits an approved piece's `.blend`, set `master: blend` in its yaml (and in the project's registry, e.g. Sanctuary's `BLEND_MASTERED`).

## 9. run_python snippets

Placeholders are in `<>`. Always pass the fixed `reason`, and never an `object_name`. Verified live in Blender 5.2.

Snippet B, bake a procedural swatch. Reason: `"no bake op: bake a procedural material to a PNG so it ships in glTF"`.

```python
import bpy
OBJ, MAT, PX, OUT = "KitbashSwatch__<Material>", "<Material>__proc", <texture_px>, "<abs>/textures/<Material>.png"
o = bpy.data.objects[OBJ]; nt = bpy.data.materials[MAT].node_tree
scene, vl = bpy.context.scene, bpy.context.view_layer
img = bpy.data.images.new("kitbash_bake", PX, PX, alpha=False)
node = nt.nodes.new("ShaderNodeTexImage"); node.image = img; nt.nodes.active = node
prev_engine, prev_samples = scene.render.engine, scene.cycles.samples
prev_sel, prev_active = [x for x in scene.objects if x.select_get()], vl.objects.active
try:
    scene.render.engine = "CYCLES"; scene.cycles.samples = 1
    bake = scene.render.bake
    bake.use_pass_direct = False; bake.use_pass_indirect = False; bake.use_pass_color = True; bake.margin = 0
    for x in scene.objects: x.select_set(x == o)
    vl.objects.active = o
    bpy.ops.object.bake(type="DIFFUSE")
    img.filepath_raw = OUT; img.file_format = "PNG"; img.save()
    print({"saved": OUT, "px": PX})
finally:
    scene.render.engine = prev_engine; scene.cycles.samples = prev_samples
    for x in scene.objects: x.select_set(x in prev_sel)
    vl.objects.active = prev_active
    nt.nodes.remove(node); bpy.data.images.remove(img)
```

Snippet C, world-anchored box UVs. Reason: `"unwrap_uvs has no world-anchored box projection; kit textures must line up across pieces"`.

```python
import bpy, bmesh
NAMES, ANCHOR, S = [<object names>], (<ax>, <ay>, 0.0), <swatch_m>
for n in NAMES:
    o = bpy.data.objects[n]; me = o.data
    bm = bmesh.new(); bm.from_mesh(me); uv = bm.loops.layers.uv.verify()
    for f in bm.faces:
        nx, ny, nz = (abs(c) for c in f.normal)
        for l in f.loops:
            x, y, z = o.matrix_world @ l.vert.co
            if nz >= nx and nz >= ny: u, v = x - ANCHOR[0], y - ANCHOR[1]
            elif nx >= ny: u, v = y - ANCHOR[1], z - ANCHOR[2]
            else: u, v = x - ANCHOR[0], z - ANCHOR[2]
            l[uv].uv = (u / S, v / S)
    bm.to_mesh(me); bm.free(); me.update()
    print(n, "uv layers", len(me.uv_layers))
```

Snippet D, export a piece as one node. Reason: `"export_asset exports one object under its own name; a kit piece ships as one node <Piece> joined from its per-material objects"`.

```python
import bpy
NAMES, PIECE, OUT = [<object names>], "<Piece>", "<abs>/glb/<Piece>.glb"
assert PIECE not in bpy.data.objects, f"{PIECE} exists"
scene, vl = bpy.context.scene, bpy.context.view_layer
prev_sel, prev_active = [x for x in scene.objects if x.select_get()], vl.objects.active
copies, copy_names, mesh_names = [], [], []
try:
    for n in NAMES:
        src = bpy.data.objects[n]; c = src.copy(); c.data = src.data.copy()
        c.location = (0.0, 0.0, 0.0)          # shelved originals keep identity mesh data at origin
        scene.collection.objects.link(c); copies.append(c); copy_names.append(c.name); mesh_names.append(c.data.name)
    for x in scene.objects: x.select_set(x in copies)
    vl.objects.active = copies[0]
    bpy.ops.object.join()
    joined = vl.objects.active; joined.name = PIECE; joined.data.name = PIECE
    for x in scene.objects: x.select_set(x == joined)
    bpy.ops.export_scene.gltf(filepath=OUT, export_format="GLB", use_selection=True, export_apply=True)
    print({"exported": OUT, "tris": sum(len(p.vertices) - 2 for p in joined.data.polygons)})
finally:
    for name in [PIECE] + copy_names:          # by name: join already deleted the non-active copies
        c = bpy.data.objects.get(name)
        if c is not None: bpy.data.objects.remove(c)
    for name in mesh_names + [PIECE]:          # by name: the mesh of a joined-away copy is left orphaned
        me = bpy.data.meshes.get(name)
        if me is not None and me.users == 0: bpy.data.meshes.remove(me)
    for x in scene.objects: x.select_set(x in prev_sel)
    vl.objects.active = prev_active if prev_active and prev_active.name in bpy.data.objects else None
```

Snippet E, host-side check of the shipped file (run with `bash`, not `run_python`):

```sh
~/golem_mcp/blender/.venv/bin/python - "<abs>/glb/<Piece>.glb" <<'EOF'
import json, sys
from golem_blender.export.glb_report import asset_report, parse_glb
r = asset_report(sys.argv[1]); g, _ = parse_glb(sys.argv[1])
print(json.dumps({"roots": r.root_node_names, "tris": r.triangle_count,
  "materials": [m.get("name") for m in g.get("materials", [])], "images": r.image_count,
  "min": r.minimum_corner_m, "max": r.maximum_corner_m,
  "inverted": sum(m.inverted_facet_count for m in r.meshes.values()),
  "samplers": g.get("samplers", [])}))
EOF
```

Snippet F, measure a piece (read-only). Reason: `"no op measures joint bounds, triangles and connector cross-sections across several objects"`.

```python
import bpy, json
NAMES, TOL = [<object names>], <snap_tolerance_m>
CONNECTORS = [<{"side": "+x", "axis": 0, "plane_m": 1.0, "spans_m": {"1": [-0.15, 0.15], "2": [0.0, 3.0]}}, ...>]
pts, tris, body = [], {}, []
for n in NAMES:
    o = bpy.data.objects[n]
    world = [o.matrix_world @ v.co for v in o.data.vertices]
    pts += world
    if n == NAMES[0]: body = world             # NAMES[0] is the body object; connectors are measured on it only
    tris[n] = sum(len(p.vertices) - 2 for p in o.data.polygons)
tris["total"] = sum(tris.values())
out = {"bounds_min_m": [round(min(p[i] for p in pts), 5) for i in range(3)],
       "bounds_max_m": [round(max(p[i] for p in pts), 5) for i in range(3)],
       "body_bounds_min_m": [round(min(p[i] for p in body), 5) for i in range(3)],
       "body_bounds_max_m": [round(max(p[i] for p in body), 5) for i in range(3)], "triangles": tris,
       "materials": sorted({s.material.name for n in NAMES for s in bpy.data.objects[n].material_slots if s.material}),
       "connectors": {}}
for c in CONNECTORS:
    on = [p for p in body if abs(p[c["axis"]] - c["plane_m"]) <= TOL]
    spans = {k: [min(p[int(k)] for p in on), max(p[int(k)] for p in on)] if on else None for k in c["spans_m"]}
    ok = bool(on) and all(abs(spans[k][0] - e[0]) <= TOL and abs(spans[k][1] - e[1]) <= TOL for k, e in c["spans_m"].items())
    out["connectors"][c["side"]] = {"vertices": len(on), "spans": spans, "ok": ok}
print(json.dumps(out))
```

Axis indices: 0 = x, 1 = y, 2 = z. Convert kit.yaml connector entries (`normal_axis`, `spans_m` keyed by axis letter) into this form: `axis` = index of `normal_axis`, `spans_m` keys = the other axes' indices as strings. Negative control (measured): a 2.05 m body gives `ok: false` on both connectors and bounds +-1.025.

Snippet G, assembly preview. Reason: `"no duplicate op: place linked copies of approved pieces beside the new one to show how they join"`. Pieces from other kits are imported from their `.glb` with `bpy.ops.import_scene.gltf` into the same collection.

```python
import bpy, math
LAYOUT = [<{"names": ["Wall_Straight__Stone"], "offset_m": [2.0, 0.0, 0.0], "yaw_deg": 0}, {"glb": "/abs/other/glb/X.glb", "offset_m": [...], "yaw_deg": 0}>]
scene = bpy.context.scene
col = bpy.data.collections.get("KitbashPreview") or bpy.data.collections.new("KitbashPreview")
if col.name not in scene.collection.children: scene.collection.children.link(col)
for i, item in enumerate(LAYOUT):
    if "glb" in item:
        before = set(bpy.data.objects); bpy.ops.import_scene.gltf(filepath=item["glb"])
        new = [o for o in bpy.data.objects if o not in before]
    else:
        new = []
        for n in item["names"]:
            c = bpy.data.objects[n].copy(); c.name = f"{n}__preview{i}"; new.append(c)
    for c in new:
        for other in list(c.users_collection): other.objects.unlink(c)
        col.objects.link(c)
        c.location = item["offset_m"]; c.rotation_euler = (0.0, 0.0, math.radians(item["yaw_deg"]))
print({"preview_objects": len(col.objects)})
```

The piece under construction stays at the origin; a layout entry that names it places copies of it, and the offsets are relative to the origin. Snippet G-cleanup, same reason:

```python
import bpy
col = bpy.data.collections.get("KitbashPreview")
if col:
    for o in list(col.objects):
        mesh = o.data; bpy.data.objects.remove(o)
        if mesh is not None and mesh.users == 0 and isinstance(mesh, bpy.types.Mesh): bpy.data.meshes.remove(mesh)
    bpy.data.collections.remove(col)
print("preview cleared")
```

Snippet H, nearest filtering. Reason: `"assign_image_texture_material has no interpolation parameter"`. The exported sampler then carries `magFilter 9728`.

```python
import bpy
for name in [<material names>]:
    bpy.data.materials[name].node_tree.nodes["blended_image"].interpolation = "Closest"
print("closest set")
```

Snippet I, frame the 3D view at an elevated angle (the view keeps whatever angle the user left it at, often below the ground). Reason: `"no op sets the 3D viewport angle; frame the subject at an elevated angle for a readable screenshot"`.

```python
import bpy, math
from mathutils import Euler
CENTRE, DIST, ELEV_DEG, AZIM_DEG, ORTHO = (<cx>, <cy>, <cz>), <distance_m>, 25.0, -30.0, False
n = 0
for w in bpy.context.window_manager.windows:
    for a in w.screen.areas:
        if a.type == 'VIEW_3D':
            r3d = a.spaces.active.region_3d
            r3d.view_perspective = 'ORTHO' if ORTHO else 'PERSP'
            r3d.view_location = CENTRE
            r3d.view_distance = DIST
            r3d.view_rotation = Euler((math.radians(90.0 - ELEV_DEG), 0.0, math.radians(AZIM_DEG)), 'XYZ').to_quaternion()
            a.tag_redraw(); n += 1
print({'viewports_set': n})
```

Snippet J, save then restore the view settings that `set_pixel_art_view` overwrites (scene Workbench colour type, light, anti-aliasing, view transform, Solid viewport colour type, overlays). Set `MODE` to `save` or `restore`. Reason: `"no op saves or restores the viewport shading and scene display settings that set_pixel_art_view overwrites without restoring"`. Found as `MATERIAL / STUDIO / 8 / AgX` and Solid `MATERIAL` before.

```python
import bpy
MODE = "<save|restore>"
ns, sc = bpy.app.driver_namespace, bpy.context.scene
areas = [a for w in bpy.context.window_manager.windows for a in w.screen.areas if a.type == 'VIEW_3D']
if MODE == "save":
    ns["kitbash_prior_view"] = {"scene_color_type": sc.display.shading.color_type, "scene_light": sc.display.shading.light,
        "render_aa": sc.display.render_aa, "view_transform": sc.view_settings.view_transform,
        "viewports": [{"type": a.spaces.active.shading.type, "color_type": a.spaces.active.shading.color_type, "light": a.spaces.active.shading.light,
                       "show_overlays": a.spaces.active.overlay.show_overlays} for a in areas]}
    print("view saved", ns["kitbash_prior_view"])
else:
    p = ns.pop("kitbash_prior_view", None)
    assert p, "no saved view state"
    sc.display.shading.color_type = p["scene_color_type"]; sc.display.shading.light = p["scene_light"]
    sc.display.render_aa = p["render_aa"]; sc.view_settings.view_transform = p["view_transform"]
    for a, v in zip(areas, p["viewports"]):
        s = a.spaces.active; s.shading.type = v["type"]; s.shading.color_type = v["color_type"]; s.shading.light = v["light"]
        s.overlay.show_overlays = v["show_overlays"]; a.tag_redraw()
    print("view restored")
```

Snippet K, save the 3D view to a PNG so it can be cropped and zoomed on the host. Reason: `"no op saves a VIEW_3D screenshot to a file path, so a joint cannot be cropped and zoomed"`. Call it after snippet I in an earlier call, so the area has redrawn.

```python
import bpy
OUT = "<abs>/zfight/<name>_view.png"
for w in bpy.context.window_manager.windows:
    for a in w.screen.areas:
        if a.type == 'VIEW_3D':
            with bpy.context.temp_override(window=w, area=a):
                print(bpy.ops.screen.screenshot_area(filepath=OUT))
            break
```

Snippet Z, static z-fight detector (read-only). It triangulates every object in world space, groups triangles by plane, and flags any pair on near-identical planes (closer than `0.99 * proud_m`) whose 2D overlap has positive area (SAT penetration above 1e-5 m; shared edges never count). `same_facing` = FAIL, `underside` (down-facing on the lowest plane) and `opposite_facing` = warnings. Reason: `"no op detects coplanar overlapping faces (z-fighting) across the objects of a piece"`.

```python
import bpy, bmesh, json
from mathutils import Vector
NAMES, PROUD, EPS = [<object names, plus __preview copies for the assembly run>], <proud_m>, 1e-5
tris, zmin = [], 1e9
for n in NAMES:
    o = bpy.data.objects[n]
    bm = bmesh.new(); bm.from_mesh(o.data); bmesh.ops.triangulate(bm, faces=bm.faces[:])
    for f in bm.faces:
        p = [o.matrix_world @ v.co for v in f.verts]; zmin = min(zmin, *(q.z for q in p))
        nrm = (p[1] - p[0]).cross(p[2] - p[0]); area = nrm.length / 2
        if area < 1e-9: continue
        nrm.normalize()
        sign = 1.0 if next(c for c in nrm if abs(c) > 1e-6) > 0 else -1.0
        cn = nrm * sign
        u = cn.cross(Vector((0, 0, 1)) if abs(cn.z) < 0.9 else Vector((1, 0, 0))).normalized(); v = cn.cross(u)
        tris.append({"o": n, "cn": cn, "sign": sign, "d": cn.dot(p[0]), "uv": [(q.dot(u), q.dot(v)) for q in p], "c": sum(p, Vector()) / 3, "zn": nrm.z, "area": area})
    bm.free()
groups = {}
for t in tris: groups.setdefault(tuple(round(c, 3) + 0.0 for c in t["cn"]), []).append(t)
def pen(A, B):                       # SAT penetration depth of two 2D triangles; <= EPS means separated or only touching
    best = 1e9
    for P in (A, B):
        for i in range(3):
            (x0, y0), (x1, y1) = P[i], P[(i + 1) % 3]
            ax, ay = y0 - y1, x1 - x0; L = (ax * ax + ay * ay) ** 0.5
            if L < 1e-12: continue
            ax, ay = ax / L, ay / L
            a = [ax * x + ay * y for x, y in A]; b = [ax * x + ay * y for x, y in B]
            best = min(best, max(a) - min(b), max(b) - min(a))
            if best <= EPS: return best
    return best
hits, counts = [], {}
for g in groups.values():
    g.sort(key=lambda t: t["d"])
    for i, a in enumerate(g):
        for b in g[i + 1:]:
            if b["d"] - a["d"] >= PROUD * 0.99: break
            if pen(a["uv"], b["uv"]) > EPS:
                same = a["sign"] == b["sign"]
                under = same and a["zn"] < -0.999 and abs(a["c"].z - zmin) < 1e-3
                kind = "underside" if under else ("same_facing" if same else "opposite_facing")
                key = (a["o"], b["o"], kind, round(a["d"], 4)); counts[key] = counts.get(key, 0) + 1
                small = a if a["area"] <= b["area"] else b
                if len(hits) < 12: hits.append({"kind": kind, "objs": [a["o"], b["o"]], "gap_m": round(b["d"] - a["d"], 5), "at": [round(c, 3) for c in small["c"]]})
print(json.dumps({"fail_same_facing": sum(c for k, c in counts.items() if k[2] == "same_facing"), "warn": sum(c for k, c in counts.items() if k[2] != "same_facing"), "groups": [{"objs": [k[0], k[1]], "kind": k[2], "plane_d": k[3], "tri_pairs": c} for k, c in counts.items()], "examples": hits}))
```

Snippet M, metamorphic z-fight test plus junction close-ups. It draws the 3D view offscreen from several orthographic cameras and, per view, shifts the camera along its own axis by four distances; the picture must not change. It also writes an overview sheet and a zoom sheet (rows = `LOOK_AT` points, columns = four azimuths, 0.25 m half-width) to read. Overlays are switched off while it runs and restored. Reason: `"no op renders a piece from shifted orthographic cameras and compares the images; metamorphic z-fight test"`.

```python
import bpy, gpu, json, math
import numpy as np
from mathutils import Matrix, Vector
CENTRE, RADIUS_M, OUT = Vector((<cx>, <cy>, <cz>)), <half_diagonal_m>, "<abs>/zfight/<Piece>"
INCLUDE_UNDERSIDE, LOOK_AT = <False|True>, [<(x, y, z), ...>]
VIEWS = [(35.0, 30.0), (35.0, 120.0), (35.0, 210.0), (35.0, 300.0), (89.0, 0.0)] + ([(-35.0, 30.0)] if INCLUDE_UNDERSIDE else [])   # (elevation_deg, azimuth_deg)
SHIFTS_M = [0.0, 0.37 * RADIUS_M, -0.61 * RADIUS_M, 1.13 * RADIUS_M]
W = H = 768; THRESH, MAX_PX, MIN_COVER, ZOOM_HALF_M, TILE = 2, 4, 0.02, 0.25, 256
scene, vl = bpy.context.scene, bpy.context.view_layer
area = next(a for w in bpy.context.window_manager.windows for a in w.screen.areas if a.type == 'VIEW_3D')
space = area.spaces.active; region = next(r for r in area.regions if r.type == 'WINDOW')
def ortho(half, near, far): return Matrix(((1.0 / half, 0, 0, 0), (0, 1.0 / half, 0, 0), (0, 0, -2.0 / (far - near), -(far + near) / (far - near)), (0, 0, 0, 1)))
def fwd_of(elev, azim):
    e, a = math.radians(elev), math.radians(azim)
    return -Vector((math.cos(e) * math.sin(a), -math.cos(e) * math.cos(a), math.sin(e)))   # camera sits at elevation/azimuth and looks at the target
def shoot(off, n, fwd, target, dist, shift, proj):
    view = (Matrix.Translation(target - fwd * (dist + shift)) @ fwd.to_track_quat('-Z', 'Y').to_matrix().to_4x4()).inverted()
    off.draw_view3d(scene, vl, space, region, view, proj, do_color_management=True, draw_background=True)
    return np.array(off.texture_color.read(), dtype=np.uint8).reshape(n, n, 4)[:, :, :3].astype(np.int16)
def save(path, a):
    h, w = a.shape[:2]; img = np.concatenate([a / 255.0, np.ones((h, w, 1))], axis=2)
    im = bpy.data.images.new("kitbash_z", w, h, alpha=False); im.colorspace_settings.name = "Non-Color"
    im.pixels.foreach_set(img.ravel().astype(np.float32)); im.filepath_raw = path; im.file_format = "PNG"; im.save(); bpy.data.images.remove(im)
dist = 3.0 * RADIUS_M + 1.0
projP = ortho(RADIUS_M * 1.15, 0.1, dist + 3.0 * RADIUS_M)
prev_overlays = space.overlay.show_overlays; space.overlay.show_overlays = False
offW, offT = gpu.types.GPUOffScreen(W, H), gpu.types.GPUOffScreen(TILE, TILE)
report, bases = [], []
try:
    for vi, (elev, azim) in enumerate(VIEWS):                       # metamorphic: shifting an orthographic camera along its axis must not change the picture
        fwd = fwd_of(elev, azim); base = shoot(offW, W, fwd, CENTRE, dist, SHIFTS_M[0], projP); bases.append(base[::2, ::2])
        covered = float((np.abs(base - base[0, 0]).max(axis=2) > 4).mean())
        mask = np.zeros((H, W), bool)
        for s in SHIFTS_M[1:]: mask |= np.abs(shoot(offW, W, fwd, CENTRE, dist, s, projP) - base).max(axis=2) > THRESH
        box = None
        if mask.any():
            ys, xs = np.where(mask); box = [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())]
            img = base.astype(np.uint8).copy(); img[mask] = (255, 0, 255); save(f"{OUT}_diff_view{vi}.png", img)
        report.append({"view": vi, "elev": elev, "azim": azim, "covered": round(covered, 3), "diff_px": int(mask.sum()), "box": box, "ok": covered >= MIN_COVER and int(mask.sum()) <= MAX_PX})
    while len(bases) % 3: bases.append(np.zeros_like(bases[0]))
    save(f"{OUT}_views.png", np.concatenate([np.concatenate(bases[i:i + 3], axis=1) for i in range(0, len(bases), 3)], axis=0).astype(np.uint8))
    projT = ortho(ZOOM_HALF_M, 0.1, 8.0); rows = []                  # visual: magnified close-ups of every junction, from the four elevated sides
    for p in LOOK_AT: rows.append(np.concatenate([shoot(offT, TILE, fwd_of(35.0, az), Vector(p), 4.0, 0.0, projT) for az in (30.0, 120.0, 210.0, 300.0)], axis=1))
    if rows: save(f"{OUT}_zoom.png", np.concatenate(rows, axis=0).astype(np.uint8))
finally:
    offW.free(); offT.free(); space.overlay.show_overlays = prev_overlays
print(json.dumps({"ok": all(r["ok"] for r in report), "views": report, "sheet": f"{OUT}_views.png", "zoom": f"{OUT}_zoom.png"}))
```

## 10. Why (research)

- Connectors are the measuring unit: they double as measuring aids ("a passage n pins wide"), and matching rules let separately authored pieces combine. Hence `units.yaml` connector profiles, grid-vertex pivots and the per-connector check in snippet F. Códices et al., "Procedural generation of 3D maps with snappable meshes", IEEE Access 2022, DOI 10.1109/ACCESS.2022.3168832.
- Iterative render -> critique beats one pass, provided each critique names a concrete discrepancy. Hence B4-B7: measure, look, and phrase every failure as feature plus number. CodeGen-3D, IEEE Access 2026, DOI 10.1109/ACCESS.2026.3654948.
- The coder fixes only some critiques per round, so re-verify each one by name after every revision (B7), and re-run the z-fight protocol in full. LL3M, DOI 10.48550/arXiv.2508.08228.
- Game-ready assets need fine-grained control while ideation needs speed. Hence the interview offers computed defaults for speed and every number is overridable. Fukaya et al., Int. J. Human-Computer Interaction 2026, DOI 10.1080/10447318.2026.2632170.
- Low-poly means the fewest polygons that still sell the shape. Hence per-class triangle budgets and `min_feature_m`. Vaughan, *Digital Modeling*.
- A rendered picture has no ground-truth image to compare against, so z-fighting is tested with a metamorphic relation (Chen, Cheung and Yiu, "Metamorphic testing: a new approach for generating next test cases", HKUST-CS98-01, 1998): moving an orthographic camera along its axis leaves the correct picture unchanged and flips a z-fighting one. Every new check needs a negative control that fails (the canary), or it proves nothing.
- Kits snap to a grid whose sub-footprints are multiples of each other, so pieces from one grid combine without gaps. Hence `grid_m`, whole-cell footprints, and `grid_candidates` when a pack is registered. Burgess, "Skyrim's modular level design", GDC 2013, http://blog.joelburgess.com/2013/04/skyrims-modular-level-design-gdc-2013.html.
- Greybox first, then swap in kit pieces: layout is judged on cheap blocks before art is spent. Hence the section 5 sizes and bounds exist before any piece is built, and assembled pieces (section 6A) are placed by measured offsets. Unity, "Realizing rapid conceptual design with kitbashing", https://unity.com/blog/games/realizing-rapid-conceptual-design-with-kitbashing.
- Rule-based buildings can be generated from existing asset kits when connector validity rules say which pieces may meet. Hence pack and assembled pieces use the same connector and bounds vocabulary as built ones. HICSS 2025, https://scholarspace.manoa.hawaii.edu/items/6cfe2efe-651d-4b06-88df-199a9e9c710a.
- Theme-consistent asset sets come out better from a concept image first, then 3D. Hence section 6G restyles a reference in the game's style before TRELLIS. ThemeStation, SIGGRAPH 2024, DOI 10.1145/3641519.3657471 (in the local corpus).
- Image-to-3D inputs work best as a single centred object at 70-80 percent of the frame, on a plain light background, with soft light, in a three-quarter view. Hence the restyle prompt in section 6G. 3DCodeBench appendix C.5, DOI 10.48550/arXiv.2606.01057 (in the local corpus).
- An art bible carries: visual target, pillars, camera, scale, palette, shape language, materials and texel density, references, and per-class specs. Hence the style document of section 3.0 and its sections. https://blog.makko.ai/game-art-bible-template/ (a secondary source).
- Generators should offer ideation speed AND fine control. Hence section 6G asks per image whether to restyle or go straight to TRELLIS, and every number stays overridable. Fukaya et al., DOI 10.1080/10447318.2026.2632170 (in the local corpus).
- Pack licenses differ and decide what may be committed: Kenney packs are CC0; Quaternius packs are QAL v1.0, which forbids redistribution. Hence `pack.license` in `kit.yaml` and the web reference licenses in `references.yaml`. https://kenney.nl/support, https://quaternius.com/license.html.
