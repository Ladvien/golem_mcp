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

1. **Generate the base colour.**
   `generate_texture_base(prompt="<the surface, described>", output_name="<Name>")`.
   Describe the SURFACE, not the object: "weathered red brick wall, dry,
   mortar visible" reads as a texture; "a brick" reads as a picture of a
   brick. The map is written as `T_<Name>_BaseColor.png` into the
   texture directory and comes back as an image you can look at.

2. **Look at the map.** The image the generation call returned is the
   map itself, not the object with the map on it. Judge it there: is it
   tileable, is the colour right, is there lighting baked into it that
   will fight the scene's lighting?

3. **Revise it if it is wrong.**
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

4. **Apply it to the object.**
   `assign_pbr_texture_set(object_name="<the mesh>", name="<Material>",
   base_color_path="<the accepted map>")`. The op takes the ORM and the
   normal map too, when they exist.

5. **Bake the maps that come from the MESH.**
   `bake_orm_map(object_name="<the mesh>", output_path="<the ORM path>",
   resolution_px=2048, ao_distance_m=0.05, roughness=0.7, metallic=0.0)`
   and `bake_normal_map(object_name="<the mesh>",
   output_path="<the normal path>", resolution_px=2048)`.
   These are baked, not generated: a generated normal map is a PICTURE
   of a normal map, not a surface normal.
   The mesh needs a UV layer — call `unwrap_uvs` first if it has none.

6. **Re-apply with all three maps** (the material is reused by name, so
   this updates the graph in place rather than stacking a second image
   node), and check it: `pbr_texture_report(object_name="<the mesh>")`
   says what is actually wired.

7. **Look at the object in context.**
   `preview_texture(object_name="<the mesh>")`. Now you are judging the
   texture ON the asset, in the lighting of the scene.

8. **Export the set.** `export_texture_set(texture_name="<Name>")`
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
- **Shade the mesh SMOOTH before baking its normal map.** The map holds
  the difference between the shading normal and the face normal, so a
  FLAT SHADED mesh bakes a constant map however much relief it has.
  Measured on a bevelled box: 1 distinct value flat shaded, 17 smooth
  shaded. The same applies to a UV atlas: a bevelled box's corners are
  below the unwrap's 66 degree limit, so `unwrap_uvs` with the default
  ANGLE_BASED method cannot solve it — use `method="SMART_PROJECT"`
  for a mesh whose faces are all shallow.

## What each op does

| Call | What it is for |
|---|---|
| `generate_texture_base` | The AI half: the base-colour map. No Blender needed. |
| `preview_texture` | The EEVEE render that lets you SEE the texture. Needs the open Blender. |
| `assign_pbr_texture_set` | Puts the maps on the mesh as one material. |
| `bake_orm_map` | Bakes the AO and packs it with roughness and metallic. |
| `bake_normal_map` | Bakes the tangent-space normal map. |
| `pbr_texture_report` | Says what the material has actually wired. |
| `export_texture_set` | Copies the set out with its metadata. |
