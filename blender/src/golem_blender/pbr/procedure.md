# PBR texture authoring: the loop

A texture is authored, not guessed. The loop is: generate, LOOK at it,
revise, apply, look again, export. The step that is easy to get wrong
is the LOOKING, so it is stated first and stated loudest.

## The one rule that makes the difference

**Review the EEVEE render, never the Workbench contact sheet.**

Workbench reads only `material.diffuse_color` and never the shader
graph. Measured in this repository's Blender 5.2 with a solid-red image
texture against a green `diffuse_color`: EEVEE rendered bright red
(0.683) and Workbench rendered bright green (0.621). A texture reviewed
through the Workbench sheet is reviewed blind. `preview_texture` renders
in EEVEE for exactly this reason; `render_views` does not show textures.

## The steps, in order

0. **Choose how the base colour is made.** There are two routes, and
   the choice is not obvious from the result.

   - `generate_procedural_base_color(texture_name="<Name>")` builds it
     from Blender's own nodes - a Voronoi pattern's cell edges are the
     joints, each cell is a stone, and the cell's own random value is
     its colour. The whole set can then be made with bpy alone: the
     base colour, the relief, and the ORM and normal map baked from
     that relief.
   - `generate_texture_base(prompt="...")` generates it with FLUX on
     the golem server. That is the photoreal route, and the only one
     that is.

   Measured: the procedural map TILES and the generated one does not.
   The procedural map's seam is 0.025x the texture's largest ordinary
   features; the generated one's is 1.38x, and it is a property of
   the SAMPLE - four generations of one prompt measured 1.38x, 1.57x,
   1.10x and 1.38x. The procedural relief inherits that: the normal
   map baked from it has a seam of 0.18x against the generated map's
   0.39x.

   So: for a surface that repeats across a floor, take the procedural
   route. For a hero asset's colour, take the generated one.

1. **Look at a REAL reference first.**
   `search_reference_images(query="<the surface>", count=12)` and then
   `save_reference_images(search_id="<the id>", numbers=[...],
   kit_slug="<a name>")`. This is the step that decides whether the
   texture is right, and it is not optional.

   A generated texture is plausible, and plausible is not the same as
   right. Measured: a first cobblestone map came back as neat
   rectangular blocks, and the reference photo of an actual medieval
   street showed rounded river pebbles with sand between them. The
   prompt had said "cobblestone", which the model read as blocks. The
   reference is what told the difference; without it the wrong map
   would have been applied and exported.

   Look at the numbered contact sheet the search returns, pick the
   images that show the SURFACE (a top-down view beats a street
   scene), and read the shape, the colour and the gap pattern off
   them. Then say it in the prompt.

2. **Generate the base colour.**
   `generate_texture_base(prompt="<the surface, described>", output_name="<Name>")`.
   Describe the SURFACE, not the object, and describe it the way the
   reference showed it: "weathered red brick wall, dry, mortar visible"
   reads as a texture; "a brick" reads as a picture of a brick. Say how
   MANY stones are across the frame — "about sixteen big flat oval
   stones" puts the scale in the map, and the scale is what the
   geometry has to match. The map is written as
   `T_<Name>_BaseColor.png` into the texture directory and comes back
   as an image you can look at.

3. **Look at the map.** The image the generation call returned is the
   map itself, not the object with the map on it. Judge it there
   against the reference: is it the same shapes, the same scale, the
   same colour? Is it tileable, and is there lighting baked into it
   that will fight the scene's lighting?

4. **Revise it if it is wrong.**
   `generate_texture_base(prompt="...", output_name="<Name>",
   init_image_path="<the previous map>", image_strength=...)`.
   `init_image_path` must be under the codex root (`~/mnt/codex_fs/...`).
   **`image_strength` is how much of the init the result KEEPS: 1 is
   the init almost unchanged, 0 discards it.** Measured against mflux,
   not assumed — the mean difference from the init was 0.5 at strength
   1.0, 17.1 at 0.6, 45.2 at 0.25 and 37.3 at 0.0. So to REPLACE the
   map, use a LOW strength (0.0-0.3); to nudge it, use a HIGH one
   (0.6-0.9). Change the `seed` for a different result at the same
   strength.

5. **Give the mesh a RELIEF to bake from.**
   `add_relief_slab(name="<mesh>", albedo_path="<the accepted map>",
   size_m=2.0, thickness_m=0.08, cell_count=512, depth_m=0.06)`.

   **Or build the relief PROCEDURALLY, with no image to read.**
   `source="voronoi"` makes the height field from the lane's own
   arithmetic - a Voronoi pattern's cell edges ARE the joints - and
   the field is PERIODIC: its seam is 0.00x, where an albedo-derived
   field's is 0.1604x. The maps baked from it tile exactly. The
   other sources are "brick" and "grain"; `source_scale_cells` sets
   the pattern's scale in cells across the slab.

   **The pattern follows the description.** `pbr.patterns` reads the
   surface's STRUCTURE first - a "wood floor" is a wood floor, a
   "stone tile" is a stone tile - and its material second. A voronoi
   cell is a separate rounded piece, so it is right for cobbles,
   gravel, ground and asphalt; a course is a course, so "brick" is
   right for a brick wall and a tile floor; and a plank shows the
   nested curves a tree's growth makes, so "grain" is right for wood.

   **A METAL is neither.** A steel plate is a SHEET, not a set of
   pieces, so the "metal" source is a set of BANDS - the grain of
   the rolling, the corrugation of the pressing - and the voronoi's
   separated cells are exactly wrong for it. Measured against ten
   real PBR sets, the metals read the worst of the twenty before
   this: one metal's contrast was 7.59x the truth's and another's
   brightness 0.15x, because a description saying "aged, black,
   brown, oxidized, steel" made the palette read black and the
   pattern read pieces - and neither is a steel plate.

   **The scale is the number of features, and the features are the
   pattern's own.** Measured, a line pattern's cell count IS its
   feature count, with the metal's bands running about twice as
   close together as the grain's lines:
   - a "grain" at 13 cells reads 0.96x the truth's feature count,
     and at 6 cells 0.92x;
   - a "metal" needs about 1.9 cells per feature: at 17 cells it
     reads 1.00x the truth's, at 42 cells 1.05x and at 14 cells
     1.03x.

   So the count of features in the surface you are matching sets the
   cells, and a metal takes about twice the grain's count.

   The slab RECORDS which source it used, and
   `relief_slab_report(object_name="<the slab>")` reads it back -
   because the two look identical and only the record says which,
   and the difference is the difference between a relief that tiles
   and one that cannot.

   The relief comes from the ALBEDO, so the baked maps' joints land on
   the texture's own mortar lines instead of near them. Without it the
   maps have nothing to carry: the occlusion finds no crevice and the
   normal map is flat.

   Two of its parameters are physical sizes, not counts, and both are
   measured:
   - `depth_m` is the joint's DEPTH. Below about half a centimetre the
     joint is a ramp the occlusion cannot find: 20 mm left 0.00% of
     the surface dark, 50 mm left 0.12% and 100 mm left 5.66%. Past
     about a tenth of a metre the cobbles stop being a paved surface
     and become islands in a pit. 60 mm is the deepest joint that
     still reads as a cobble street.
   - `cell_count` is how finely the mesh resolves the texture. With the
     depth held physical, every measure grows with it: at 128, 256 and
     512 cells the render's contrast gain was +0.016, +0.023 and
     +0.028, the normal map's signal 12.2%, 16.2% and 25.7%, and the
     occlusion's dark fraction 0.48%, 3.03% and 5.74%.

6. **Bake the maps that come from the MESH.**
   `bake_orm_map(object_name="<the mesh>", output_path="<the ORM path>",
   resolution_px=2048, ao_distance_m=0.06, roughness=0.6, metallic=0.0)`

   **The roughness and the metallic come from the DESCRIPTION.** They
   are not one constant for every material: the truth's roughness
   runs from 0.034 on a polished metal to 0.793 on a fabric, and a
   metal is METALLIC - its metallic channel is 1, and that is the one
   thing that makes it read as metal at all. `pbr.material` reads both
   from the description's words, the way the pattern and the palette
   do.

   The roughness to use, by what the description names, with the
   truth's own measured values:

   | The description says | The roughness is | The truth measures |
   |---|---|---|
   | a polished, mirror or chrome metal | 0.03-0.10 | 0.034 |
   | a brushed metal | 0.12 | - |
   | an aged, oxidised or rusty metal | 0.13-0.35 | 0.134 |
   | a corrugated or ribbed metal | 0.47 | 0.474 |
   | a smooth, plain wood | 0.50 | 0.492 |
   | a concrete or a plaster | 0.52 | 0.516 |
   | a tile | 0.45-0.51 | 0.335-0.514 |
   | a brick | 0.64 | 0.628-0.657 |
   | a ground, dirt or gravel | 0.50-0.54 | 0.497-0.541 |
   | an asphalt | 0.75 | 0.745 |
   | a fabric, wool or fur | 0.79 | 0.784-0.793 |

   A metal's metallic is 1.0 and everything else's is 0.0.

   and `bake_normal_map(object_name="<the mesh>",
   output_path="<the normal path>", resolution_px=2048)`.
   The mesh needs a UV layer — call `unwrap_uvs` first if it has none.
   **The normal map's default method is `from_height`, and that is the
   one to use for a relief surface.** The `bake` method stores a
   CURVATURE measure, so on a smooth relief it is nearly flat.
   Measured together on the same cobblestone slab (a 2 m relief at 512
   cells with a 60 mm joint, baked at 1024 px): the `from_height` map's
   encoded X channel spans 0.000 to 1.000 — the full range — and
   32.31% of its texels carry a real normal, while the `bake` map's
   spans 0.400 to 0.596 and only 0.32% do. Use `bake` for a mesh whose
   relief is a crease or an edge rather than a surface.
   The AO's reach is not a lever: across a tenfold range the
   occlusion's dark fraction moved 5.62% to 5.79%. The joint's DEPTH
   is the lever, and that is the mesh's, not the bake's.

7. **Apply the maps to the mesh.**
   `assign_pbr_texture_set(object_name="<the mesh>", name="<Material>",
   base_color_path="<the accepted map>", orm_path="<the ORM path>",
   normal_path="<the normal path>")`. The material is reused by name,
   so this updates the graph in place rather than stacking a second
   image node. Check it with
   `pbr_texture_report(object_name="<the mesh>")`, which says what is
   actually wired.

   **On an asset with more than one material, say which faces get the
   texture.** A game asset is not the slab the lane built: a barrel
   has a wood body, a metal band and a rope handle, and its faces are
   split between them. This op does not touch the other slots - but
   it also does not know which faces you meant, so the texture would
   sit on a slot nothing points at. Pass
   `faces=FaceSelector(kind="material_slot", material_slot_index=1)`
   and those faces move onto the new material while the others keep
   theirs.

8. **Look at the object in context.**
   `preview_texture(object_name="<the mesh>")`. Now you are judging the
   texture ON the asset, in the lighting of the scene.

9. **Export the set.** `export_texture_set(texture_name="<Name>")`
   copies the three maps and writes a `metadata.json` beside them.
   Pass `extras=[...]` to copy the environment map and the reference
   photographs with it, so the export is reusable on its own.

## The conventions

- The file names are `T_<Name>_BaseColor.png`, `T_<Name>_ORM.png` and
  `T_<Name>_Normal.png`.
- **A set's three maps are the same size.** They are all 2048, which is
  what every other set on codex_fs uses, and the generator and both
  bakes read that one number so a set cannot come out mismatched. It
  matters for the relief, not just for tidiness: the height field is
  sampled FROM the base colour, so at 1024 the 512-cell grid gets 2
  albedo pixels per cell and at 2048 it gets 4, and the occlusion's
  dark fraction rises from 10.29% to 12.13%.
- **A set tiles, and you CHECK that it does.** A set is something you
  repeat across a floor, so its own edges have to meet. The seam is a
  property of the GENERATED SAMPLE, not of the size: two generations
  of the same prompt and seed at different sizes had seams of 2.13x
  and 4.44x their own feature step, and in a tiled render the second
  one showed its tile boundaries as visible lines while the first did
  not.

  So `generate_texture_base` measures the seam it produced and reports
  it as `tile_seam_ratio`, with `tiles_cleanly` saying whether it is
  inside the limit. The ratio is the seam's step over the 95th
  percentile of the texture's own interior steps - the size of its
  largest ordinary features - because a seam no bigger than the
  biggest stone edge is invisible. The sets already on codex_fs measure
  0.20x to 3.50x, and the 3.50x one (the rock trim) does show its
  boundaries.

  A ratio near the limit is worth a LOOK before you accept it: a
  whole frame at 4x4 tiles makes a seam hard to judge, because the
  stones' own edges look like a grid. Magnify a tile boundary before
  believing that you can see a seam.

  **If the ratio is high, generate again with a different seed** and
  keep the one that measures lowest. That is the iteration loop, and
  the seam is the thing to iterate on.
- The ORM packs **R = ambient occlusion, G = roughness, B = metallic**.
- **The lane does not destroy an asset's other material slots.** It
  takes the slot its material already held, or an empty one, and
  every other slot keeps its place and its faces.
- The base colour is sRGB. The ORM and the normal map are Non-Color
  data: they carry values, not colour.
- The normal map is TANGENT space, so it needs a UV layer, and it is
  flat (0.5, 0.5, 1.0) wherever the geometry is flat — that is correct,
  not a broken bake. It varies where the geometry has relief.
- **The geometry's relief and the texture's scale have to agree.** The
  map's features are laid over the UV layout, so a mesh whose cells
  are 15 mm across and a map whose stones are 200 mm across will not
  line up. Count the stones in the map, and size the mesh so the
  stone lands on the right number of cells.
- **The ORM's AO channel is what makes the relief read, not the
  normal map.** Measured on the current cobblestone slab (a 2 m relief
  at 512 cells with a 60 mm joint): the ORM added +0.0412 of contrast
  to the render against the albedo alone, and the normal map added
  +0.0041 — a tenth of the ORM's share. Together they added +0.0412:
  the normal map's contribution is already inside the ORM's. The AO
  darkens the joints; the normal map only tilts the stones. So bake
  the ORM, and treat the normal map as the finishing detail.
- **The AO's reach barely matters.** Measured on the same slab, a
  reach of 0.01 m left 6.63% of the surface dark, 0.02 m left 9.63%,
  and 0.03 m and beyond all left about 9.9% — 10.04% at 0.2 m. The
  joints are deep enough that any reach covering them darkens them
  completely, so a larger reach only costs time. The default of 0.06 m
  sits well past the knee.
- **Shade the mesh SMOOTH before baking its normal map.** The map
  holds the surface normal, and a FLAT SHADED mesh's surface normal
  is its face normal, so a FLAT SHADED mesh bakes a constant map
  however much relief it has. Measured on a bevelled box: 1 distinct
  value flat shaded, 17 smooth shaded. The same applies to a UV atlas:
  a bevelled box's corners are below the unwrap's 66 degree limit, so
  `unwrap_uvs` with the default ANGLE_BASED method cannot solve it —
  use `method="SMART_PROJECT"` for a mesh whose faces are all shallow.
- **A joint one cell wide is what a normal map can carry.** Measured
  on the baked map, a one-cell joint put signal on 4.16% of the
  texels, a two-cell joint on 0.02% and a three-cell joint on none:
  a wider joint is averaged away by the mesh, and the map then has
  nothing to hold.
- **The mesh's grid has to BE the texture's grid.** Cobbles are not
  on a grid — the joints of a real cobblestone texture measured gaps
  of 198, 166, 35, 195, 193, 15 and 175 pixels — so no regular cell
  grid lands on them and the mesh averages every joint away.
  `add_relief_slab` samples the texture's own grid for exactly this
  reason.

## What each op does

| Call | What it is for |
|---|---|
| `search_reference_images` | Finds a REAL photo of the surface. Do this first. |
| `save_reference_images` | Files the picked references with their licences. |
| `generate_texture_base` | The AI half: the base-colour map. No Blender needed. |
| `generate_procedural_base_color` | The procedural half: the base colour from Blender's nodes. Tiles exactly. |
| `preview_texture` | The EEVEE render that lets you SEE the texture. Needs the open Blender. |
| `add_relief_slab` | Builds the mesh the maps are baked from, with its relief from the albedo or from a procedural pattern. |
| `relief_slab_report` | Says which source a slab's relief came from. |
| `assign_pbr_texture_set` | Puts the maps on the mesh as one material. |
| `bake_orm_map` | Bakes the AO and packs it with roughness and metallic. |
| `bake_normal_map` | Writes the tangent-space normal map. |
| `assign_pbr_constants` | Writes flat roughness and metallic, for a material that needs no map. |
| `pbr_texture_report` | Says what the material has actually wired. |
| `unwrap_uvs` | Gives the mesh a UV layout, which the normal map needs. |
| `export_texture_set` | Copies the set out with its metadata. |
