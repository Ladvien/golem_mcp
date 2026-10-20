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
   resolution_px=2048, ao_distance_m=0.06, roughness=0.85, metallic=0.0)`
   and `bake_normal_map(object_name="<the mesh>",
   output_path="<the normal path>", resolution_px=2048)`.
   The mesh needs a UV layer — call `unwrap_uvs` first if it has none.
   **The normal map's default method is `from_height`, and that is the
   one to use for a relief surface.** The `bake` method stores a
   CURVATURE measure, so on a smooth relief it is nearly flat:
   measured on a cobblestone slab, the baked map's encoded X channel
   spanned 0.482 to 0.518 and the from-height one spanned 0.388 to
   0.965. Use `bake` for a mesh whose relief is a crease or an edge
   rather than a surface.
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
- The ORM packs **R = ambient occlusion, G = roughness, B = metallic**.
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
  normal map.** Measured on a cobblestone slab: the ORM added +0.0193
  of contrast to the render against the albedo alone, and the normal
  map added +0.0027. The AO darkens the joints; the normal map only
  tilts the stones. So bake the ORM, and treat the normal map as the
  finishing detail.
- **The AO's reach saturates.** Measured on the same slab, a reach of
  0.01 m left 0.88% of the surface dark, 0.03 m left 2.90%, and
  0.06 m and beyond all left 3.08%: the joints are deep enough that
  any reach covering them darkens them completely. The default of
  0.06 m is the first value past the knee; a larger one only costs
  time.
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
| `preview_texture` | The EEVEE render that lets you SEE the texture. Needs the open Blender. |
| `add_relief_slab` | Builds the mesh the maps are baked from, with its relief from the albedo. |
| `assign_pbr_texture_set` | Puts the maps on the mesh as one material. |
| `bake_orm_map` | Bakes the AO and packs it with roughness and metallic. |
| `bake_normal_map` | Writes the tangent-space normal map. |
| `pbr_texture_report` | Says what the material has actually wired. |
| `export_texture_set` | Copies the set out with its metadata. |
