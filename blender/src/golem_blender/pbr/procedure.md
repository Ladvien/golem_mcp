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
   **A LOWER `image_strength` CHANGES MORE of the map; a higher one keeps
   more of the original.** This is measured against mflux, not assumed:
   from the same init image, strength 0 produced a wholly new pattern,
   0.25 kept the layout and changed the shapes, and 0.6 kept the init
   almost as it was. So to REPLACE the map, use a low strength
   (0.0-0.3); to nudge it, use a high one (0.6-0.9). Change the `seed`
   for a different result at the same strength.

5. **Apply it to the object.**
   `assign_pbr_texture_set(object_name="<the mesh>", name="<Material>",
   base_color_path="<the accepted map>")`. The op takes the ORM and the
   normal map too, when they exist.

6. **Bake the maps that come from the MESH.**
   `bake_orm_map(object_name="<the mesh>", output_path="<the ORM path>",
   resolution_px=2048, ao_distance_m=0.05, roughness=0.7, metallic=0.0)`
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

7. **Re-apply with all three maps** (the material is reused by name, so
   this updates the graph in place rather than stacking a second image
   node), and check it: `pbr_texture_report(object_name="<the mesh>")`
   says what is actually wired.

8. **Look at the object in context.**
   `preview_texture(object_name="<the mesh>")`. Now you are judging the
   texture ON the asset, in the lighting of the scene.

9. **Export the set.** `export_texture_set(texture_name="<Name>")`
   copies the three maps and writes a `metadata.json` beside them.

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

## What each op does

| Call | What it is for |
|---|---|
| `search_reference_images` | Finds a REAL photo of the surface. Do this first. |
| `save_reference_images` | Files the picked references with their licences. |
| `generate_texture_base` | The AI half: the base-colour map. No Blender needed. |
| `preview_texture` | The EEVEE render that lets you SEE the texture. Needs the open Blender. |
| `assign_pbr_texture_set` | Puts the maps on the mesh as one material. |
| `bake_orm_map` | Bakes the AO and packs it with roughness and metallic. |
| `bake_normal_map` | Writes the tangent-space normal map. |
| `pbr_texture_report` | Says what the material has actually wired. |
| `export_texture_set` | Copies the set out with its metadata. |
