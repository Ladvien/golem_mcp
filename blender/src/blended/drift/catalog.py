"""API drift catalog: known Blender API changes and their fixes.

This file is a first-class artifact, not a comment. Every time a
traceback teaches us that an API moved, the lesson lands here in the
same commit as the fix, so the agent (and the humans) stop paying for
it twice. 3DCodeBench's curation pipeline kept exactly this artifact
("Blender 5.0 API module" of their Experience Library) and found API
drift to be the dominant failure family.

Entry sources are tagged: [measured] = hit in one of our own sessions;
[3DCodeBench] = reported error fingerprint from arXiv:2606.01057.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DriftEntry:
    """One known API change: how it fails, and what to do instead."""

    symbol: str  # the API the old code reaches for
    changed_in: str  # Blender series where behavior changed
    error_signature: str  # distinctive substring of the traceback
    fix: str  # what current code should do
    source: str  # provenance tag


DRIFT_ENTRIES: tuple[DriftEntry, ...] = (
    DriftEntry(
        symbol="bpy.types.Action.fcurves",
        changed_in="5.0",
        error_signature="fcurves",
        fix=(
            "Actions are slotted/layered in 5.x: walk "
            "action.layers -> strips -> channelbags -> fcurves. "
            "action.fcurves does not exist in 5.x: reading it raises "
            "AttributeError ('Action' object has no attribute 'fcurves'; "
            "measured 5.2.0 LTS)."
        ),
        source="[measured] scp_characters session",
    ),
    DriftEntry(
        symbol="bpy.types.Mesh.use_auto_smooth",
        changed_in="4.1",
        error_signature="'Mesh' object has no attribute 'use_auto_smooth'",
        fix=(
            "use_auto_smooth was removed. Use the smooth-by-angle modifier "
            "or per-face smooth shading; do not set the attribute."
        ),
        source="[3DCodeBench] excluded-model failure fingerprint",
    ),
    DriftEntry(
        symbol="Principled BSDF input 'Specular'",
        changed_in="4.0",
        error_signature='bpy_prop_collection[key]: key "Specular" not found',
        fix=(
            "The Principled BSDF 'Specular' socket was renamed; use "
            "'Specular IOR Level' (and check socket names against the "
            "running version before indexing node.inputs by string)."
        ),
        source="[3DCodeBench] excluded-model failure fingerprint",
    ),
    DriftEntry(
        symbol="bpy.ops.mesh.primitive_cone_add(diameter1=...)",
        changed_in="2.8+",
        error_signature='keyword "diameter1" unrecognized',
        fix=(
            "Cone/cylinder primitive operators take radius1/radius2, not "
            "diameter1/diameter2. Prefer bmesh construction over bpy.ops "
            "primitives so argument drift cannot bite at all."
        ),
        source="[3DCodeBench] excluded-model failure fingerprint",
    ),
    DriftEntry(
        symbol="empty scene / evaluated_get on unlinked object",
        changed_in="all",
        error_signature="evaluated_get",
        fix=(
            "If bpy.context.scene.objects is empty the depsgraph has no "
            "instances: evaluated_get returns STORED values and every pose "
            "measures identical, with no error raised. Link the object into "
            "scene.collection and check len(scene.objects) before measuring."
        ),
        source="[measured] scp_characters session",
    ),
    DriftEntry(
        symbol="duplicate object names on retry (silent .001 suffix)",
        changed_in="all",
        error_signature=".001",
        fix=(
            "A failed attempt leaves its partial objects in the scene, so "
            "re-running a builder with the same name silently creates "
            "'Name.001' while name lookups still find the stale 'Name' - "
            "no error raised, wrong object measured. Ops are idempotent by "
            "name (constructors remove a same-name object first); builders "
            "must reuse deterministic names, never rely on Blender's "
            "auto-suffix."
        ),
        source="[measured] blended stage-1 retry test, 2026-08-21",
    ),
    DriftEntry(
        symbol="scene.display.shading.show_backface_culling in renders",
        changed_in="all",
        error_signature="show_backface_culling",
        fix=(
            "Backface culling is a VIEWPORT display setting: Workbench "
            "renders ignore it entirely (measured: 0 changed pixels), so a "
            "flipped normal cannot be visualized that way headless. Use the "
            "analyzer's ray-parity flipped_normal_triangle_count, or show "
            "it via shading contrast. show_xray DOES affect Workbench "
            "renders and is the supported transparency debug path."
        ),
        source="[measured] blended stage-4 pretest, 2026-08-21",
    ),
    DriftEntry(
        symbol="glTF export splits vertices at flat-shading seams",
        changed_in="all",
        error_signature="io_scene_gltf2",
        fix=(
            "glTF stores per-vertex normals, so exporting a flat-shaded "
            "watertight solid ships a file whose vertices are split along "
            "every sharp edge: re-imported it reads as dozens of "
            "disconnected components and boundary edges everywhere, with "
            "no error raised. Engines render it fine. Judge shipped GLBs "
            "on POSITION-WELDED topology (weld_and_dissolve first), never "
            "on the raw re-import - the same reason TRELLIS metadata "
            "reports as_shipped and position_welded topology separately."
        ),
        source="[measured] blended stage-8 export round-trip, 2026-08-21",
    ),
    DriftEntry(
        symbol="BVHTree.overlap on coplanar triangles",
        changed_in="all",
        error_signature="BVHTree",
        fix=(
            "BVHTree.overlap() silently returns an EMPTY list for "
            "exactly-coplanar triangle pairs - measured: two obviously "
            "overlapping triangles at z=0 report no pairs, the same two "
            "report a pair once one is nudged off-plane. No error, no "
            "warning, just a clean-looking zero. So BVHTree is unusable "
            "for any 2D/flattened work (UV overlap above all); use a "
            "uniform-grid or sweep broadphase plus an explicit 2D "
            "predicate. It remains correct for genuine 3D self-"
            "intersection, where the triangles are not coplanar."
        ),
        source="[measured] blended stage-3.2 UV overlap, 2026-08-21",
    ),
    DriftEntry(
        symbol="bpy.ops.uv.smart_project on curved geometry",
        changed_in="all",
        error_signature="smart_project",
        fix=(
            "smart_project silently produces a heavily OVERLAPPING atlas "
            "on curved/lathe geometry - measured on a barrel: 210 "
            "overlapping face pairs, 38% of covered texels multiply "
            "covered, max stack depth 40, while reporting a healthy "
            "looking 94% coverage (area sum double-counts overlap). It is "
            "clean on boxy meshes. bpy.ops.uv.unwrap(method='ANGLE_BASED') "
            "stayed at 0 overlaps on every mesh tested and is the default. "
            "cube_project stacks by design. Never trust an unwrap without "
            "measuring its overlap count."
        ),
        source="[measured] blended stage-3.2 unwrap comparison, 2026-08-21",
    ),
    DriftEntry(
        symbol="UV unwrap inherits pre-existing seams",
        changed_in="all",
        error_signature="uv_layers",
        fix=(
            "Unwrap solvers reuse the existing UV layout's seams and "
            "island structure, so unwrapping a mesh that already has UVs "
            "silently yields a different result than unwrapping it fresh "
            "- measured: a barrel unwrapped ANGLE_BASED right after "
            "SMART_PROJECT inherited that method's 26 overlapping islands "
            "instead of its own clean 344, with no warning. Clear "
            "mesh.uv_layers before unwrapping so the op is a pure "
            "function of the geometry."
        ),
        source="[measured] blended stage-3.2 unwrap determinism, 2026-08-21",
    ),
    DriftEntry(
        symbol="matrix_world is stale until view_layer.update()",
        changed_in="all",
        error_signature="matrix_world",
        fix=(
            "Setting object.location / .rotation_euler does NOT update "
            "matrix_world - the depsgraph evaluates it lazily. Reading it "
            "first returns the stale matrix (identity on a fresh object), "
            "so any op that bakes matrix_world into mesh data silently "
            "does NOTHING: no error, no warning, vertices untouched. "
            "Measured: an agent positioned three splayed stool legs via "
            "rotation_euler + location, called apply_object_transform, and "
            "all three stayed at the origin and unioned into a single "
            "central post. Call bpy.context.view_layer.update() before "
            "reading matrix_world."
        ),
        source="[measured] blended agent stool run, 2026-08-21",
    ),
    DriftEntry(
        symbol="version pin lags the installed Blender",
        changed_in="5.2",
        error_signature="BlenderVersionError",
        fix=(
            "The pin is what the system prompt tells the model it is "
            "coding against, so a stale pin is not just a red test - it "
            "hands the agent the wrong API contract. Measured 2026-08-22: "
            "the repo was pinned to (5, 0) on a Blender 5.2.0 LTS install, "
            "so build_system_prompt() opened every session with 'working "
            "inside Blender 5.0'. The full blender suite (72 tests) passed "
            "unchanged on 5.2, so no ops-vocabulary drift exists between "
            "the two series; the only defect was the lie in the prompt. "
            "Bump TARGET_BLENDER_SERIES deliberately and re-run the suite "
            "in the same commit - never set BLENDED_ALLOW_VERSION_SKEW to "
            "silence it, which keeps the wrong series in the prompt."
        ),
        source="[measured] blended prompt-convergence phase 0, 2026-08-22",
    ),
    DriftEntry(
        symbol="boolean modifier leaves an EMPTY material slot",
        changed_in="all",
        error_signature="materials",
        fix=(
            "Applying a boolean modifier appends a material slot to the "
            "target even when neither operand has a material - measured "
            "2026-08-22: len(mesh.materials) went 0 -> 1 with contents "
            "[None]. So len(mesh.materials) counts SLOTS, not materials, "
            "and 'has a material' checked that way passes on any mesh that "
            "has ever been through a boolean. Count slots whose contents "
            "are not None."
        ),
        source="[measured] blended acceptance-gate fixtures, 2026-08-22",
    ),
    DriftEntry(
        symbol="Material.use_nodes",
        changed_in="5.2",
        error_signature="use_nodes",
        fix=(
            "Deprecated, removal expected in Blender 6.0: "
            "DeprecationWarning on every read or write. A material "
            "created with bpy.data.materials.new() already has its "
            "node_tree and already reports use_nodes True, so setting it "
            "is a no-op that only emits a warning. Drop the assignment "
            "and use material.node_tree directly."
        ),
        source="[measured] blended materials op, 2026-08-22",
    ),
    DriftEntry(
        symbol="Workbench ignores the Principled BSDF base colour",
        changed_in="all",
        error_signature="diffuse_color",
        fix=(
            "Every inspection render here uses Workbench, which shades "
            "from material.diffuse_color (the viewport display colour) "
            "and never reads the shader graph. Measured 2026-08-22: a "
            "material with Base Color (0.72, 0.35, 0.22) rendered at "
            "(0.604, 0.608, 0.612) grey, because diffuse_color was still "
            "the default (0.8, 0.8, 0.8) - the vision model then reported "
            "'gray, not terracotta' as a real deviation and the agent "
            "chased it. Set BOTH fields; ops.materials.assign_material "
            "does, and is the only sanctioned way to make a material."
        ),
        source="[measured] blended iteration 1, 2026-08-22",
    ),
    DriftEntry(
        symbol="parity probe cannot see a blind recess",
        changed_in="all",
        error_signature="ray_cast",
        fix=(
            "A single ray answers only about the half-space in front of "
            "it. Measured 2026-08-22: a planter whose drainage hole was "
            "cut from the cavity DOWN into the floor but not out the "
            "bottom counted zero upward crossings from inside the recess "
            "- identical to a real through-hole - while the top-down "
            "render showed solid material on the same axis. To assert a "
            "hole passes through, sweep the WHOLE axis from beyond one "
            "side and require no hit at all (ClearAxisProbe), never "
            "inside/outside parity at a point."
        ),
        source="[measured] blended iteration 1, 2026-08-22",
    ),
    DriftEntry(
        symbol="object.dimensions ignores rotation",
        changed_in="all",
        error_signature="dimensions",
        fix=(
            "object.dimensions is the LOCAL bounding box times scale: it "
            "does not account for rotation at all. Measured 2026-08-22: a "
            "0.1 x 0.1 x 1.0 m box rotated a quarter turn about Y still "
            "reports dimensions (0.1, 0.1, 1.0) while occupying 1.0 m on "
            "world X. So verifying a stated size with obj.dimensions "
            "silently measures the wrong thing on any rotated part. "
            "Measure world extents instead: transform the eight "
            "bound_box corners by matrix_world and take max-min per axis "
            "(after view_layer.update())."
        ),
        source="[measured] blended transform ops, 2026-08-22",
    ),
    DriftEntry(
        symbol="bpy.mathutils",
        changed_in="all",
        error_signature="module 'bpy' has no attribute 'mathutils'",
        fix=(
            "mathutils is a TOP-LEVEL module, not an attribute of bpy: "
            "`from mathutils import Vector`, never `bpy.mathutils.Vector`. "
            "Measured 2026-08-22: the same AttributeError cost a tool call "
            "in both iteration 5 and iteration 6 of the convergence loop, "
            "in the middle of the verification chunk each time — so it "
            "burns budget at the point where a run is trying to finish."
        ),
        source="[measured] blended iterations 5 and 6, 2026-08-22",
    ),
    # The three entries below come from scp_characters. Only the first
    # is a genuine `match_traceback` matcher: Blender's own IndexError
    # reads "outdated internal index table, run ensure_lookup_table()
    # first", so that signature really appears in a traceback. The
    # other two name SILENT failures — the wrong space, stored
    # instead of evaluated values — which raise nothing at all. Their
    # signature is the symbol fragment, and they earn their place as
    # retry context the agent reads before re-attempting, not as
    # matchers.
    #
    # Three of the original six rows were removed:
    #   - evaluated_get: DUPLICATED the pre-existing "empty scene /
    #     evaluated_get on unlinked object" row (same error_signature);
    #     match_traceback on a traceback containing `evaluated_get(`
    #     returned BOTH, and retry.py printed the same advice twice.
    #   - Scene.render.fps / FBX: this repo's ingest lane is GLB
    #     (`grep -rn fbx src scripts` returns nothing), and the fps
    #     fact is already load-bearing in src/blended/reset.py's module
    #     docstring and CANONICAL_FPS.
    #   - view3d.view_axis: `grep -rn "view_axis|view_rotation|region_3d"
    #     src scripts` finds these nowhere outside this catalog.
    DriftEntry(
        symbol="bmesh.types.BMVert.index",
        changed_in="all",
        error_signature="ensure_lookup_table",
        fix=(
            "ensure_lookup_table() makes lookup by index valid but "
            "does NOT assign v.index; only bm.verts.index_update() "
            "does. Prefer holding BMVert identities over indices — "
            "an index read before index_update() is stale or -1, and "
            'the IndexError ("outdated internal index table") comes '
            "from the index LOOKUP, while the stale .index read is "
            "silent and returns -1."
        ),
        source="[measured] scp_characters bmesh ops, 2026-09-06",
    ),
    DriftEntry(
        symbol="bpy.types.Object.parent_type='BONE'",
        changed_in="all",
        error_signature="parent_type",
        fix=(
            "Bone parenting anchors at the bone TAIL, not the head. "
            "Compensate by -bone.length along the bone's LOCAL Y, "
            "and set matrix_parent_inverse to identity rather than "
            "fighting it."
        ),
        source="[measured] scp_characters rigging, 2026-09-06",
    ),
    DriftEntry(
        symbol="bpy.types.Bone.matrix_local",
        changed_in="all",
        error_signature="matrix_local",
        fix=(
            "matrix_local is REST space. Posed world space is "
            "armature.matrix_world @ pose_bone.matrix; reading rest "
            "data after posing silently measures the bind pose, "
            "producing identical numbers with no error."
        ),
        source="[measured] scp_characters rigging, 2026-09-06",
    ),
)


def validate_catalog() -> list[str]:
    """Return a list of schema problems (empty list = healthy catalog)."""
    problems: list[str] = []
    seen_symbols: set[str] = set()
    for entry in DRIFT_ENTRIES:
        if not entry.error_signature.strip():
            problems.append(f"{entry.symbol}: empty error_signature")
        if not entry.fix.strip():
            problems.append(f"{entry.symbol}: empty fix")
        if not (
            entry.source.startswith("[measured]")
            or entry.source.startswith("[3DCodeBench]")
        ):
            problems.append(f"{entry.symbol}: untagged source {entry.source!r}")
        if entry.symbol in seen_symbols:
            problems.append(f"duplicate symbol: {entry.symbol}")
        seen_symbols.add(entry.symbol)
    return problems


def match_traceback(traceback_text: str) -> list[DriftEntry]:
    """Return catalog entries whose signature appears in a traceback.

    This is the seam where the retry loop plugs in: on failure, matched
    entries are appended to the retry prompt so known drift is fixed on
    the first retry instead of rediscovered.
    """
    return [entry for entry in DRIFT_ENTRIES if entry.error_signature in traceback_text]
