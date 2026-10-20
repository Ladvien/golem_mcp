# SPDX-FileCopyrightText: 2026 Thomas Brittain
#
# SPDX-License-Identifier: GPL-3.0-or-later

# pylint: disable=C0114  # See tool doc-string.

"""
PBR texture sets: generate the base colour, preview the result, export the set.

Three tools, and the boundary between them is measured rather than
arranged:

- ``generate_texture_base`` runs in this server process and needs no
  Blender: it calls the golem server on big, which runs FLUX, and writes
  the map into the texture directory. It is in TOOLS_WITHOUT_BLENDER, so
  a closed Blender does not pause it.
- ``preview_texture`` renders the object, so it needs the OPEN Blender
  and goes through the add-on's exec. The render is in a shader-accurate
  engine (EEVEE), because the Workbench contact sheet reads only
  ``material.diffuse_color`` and therefore cannot show a texture at all
  (measured: a solid-red texture with a green diffuse_color rendered
  bright green in Workbench and bright red in EEVEE).
- ``export_texture_set`` copies files, so it needs no Blender either.

The apply step is NOT a tool here: the ops ``assign_pbr_texture_set``,
``bake_orm_map``, ``bake_normal_map`` and ``pbr_texture_report`` are
already exposed as tools by the facade, and a second path to the same
action is what ``tests/pure/test_one_path_ops.py`` exists to prevent.
"""

__all__ = ("register",)

import json
from pathlib import Path

from golem_blender.pbr import generate as pbr_generate
from golem_blender.pbr import paths as pbr_paths
from mcp.server.fastmcp import (  # pylint: disable=import-error,no-name-in-module
    FastMCP,
    Image,
)
from mcp.types import ToolAnnotations  # pylint: disable=import-error,no-name-in-module

from blmcp.tools.golem_pbr_textures_toolcode import Params
from blmcp.tools_helpers import (
    toolcode_format_call,
    toolcode_load_from_filepath,
    toolcode_wrap_with_calling_convention,
)
from blmcp.tools_helpers.connection import send_code
from blmcp.tools_helpers.golem_blender_bridge import (
    REPOSITORY_SRC,
    VENV_SITE_PACKAGES,
    source_fingerprint,
)
from blmcp.tools_helpers.golem_remote import GolemRemote
from blmcp.tools_helpers.live_blender import require_live_blender

# The golem server's image-generation tool.
GENERATE_IMAGE_TOOL = "generate_image"
# The model the lane generates with by default.
DEFAULT_MODEL = "flux2-klein-4b"
# The default init-image influence. The mflux CLI says 0 is no influence
# and 1 is full replacement.
DEFAULT_IMAGE_STRENGTH = 0.4

_TOOL_CALL = toolcode_wrap_with_calling_convention(
    toolcode_load_from_filepath(__file__)
)


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        annotations=ToolAnnotations(
            title="Generate Texture Base Colour",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=True,
        )
    )
    async def generate_texture_base(
        prompt: str,
        output_name: str = "",
        model: str = DEFAULT_MODEL,
        seed: int = 42,
        steps: int = 8,
        width: int = 1024,
        height: int = 1024,
        init_image_path: str = "",
        image_strength: float = DEFAULT_IMAGE_STRENGTH,
        texture_dir: str = "",
    ) -> list:
        """Generate a base-colour texture on the golem server and write it into the texture set; returns the image and its paths.

        `init_image_path` refines an existing map: it must be a path under
        the codex root (the Mac's `~/mnt/codex_fs/...`), and a HIGHER
        `image_strength` changes more of it while a LOWER one keeps more
        of the original. The written file is `T_<output_name>_BaseColor.png`.
        """
        directory = Path(texture_dir) if texture_dir else pbr_paths.texture_root()
        texture_name = output_name or "Texture"

        arguments = {
            "prompt": prompt,
            "model": model,
            "output_name": f"pbr_{texture_name}",
            "seed": seed,
            "steps": steps,
            "width": width,
            "height": height,
        }
        if init_image_path:
            # big opens the init image, so it must be handed over as the
            # path big sees; a path outside the codex root is refused.
            arguments["image_path"] = pbr_paths.big_path(Path(init_image_path))
            arguments["image_strength"] = image_strength

        remote = GolemRemote()
        result = await remote.call_tool(GENERATE_IMAGE_TOOL, arguments)
        if result.isError:
            return [_error_text(result, "generate_image")]

        payload = _first_json_payload(result)
        if payload is None:
            return [_error_text(result, "generate_image")]
        if not payload.get("success", True):
            return [json.dumps(payload, indent=2)]

        source_png = _resolve_generated_png(payload)
        if source_png is None:
            return [
                json.dumps(
                    {
                        "success": False,
                        "error": (
                            "generate_image reported success but the generated PNG "
                            "is not where it said it would be."
                        ),
                        "result": payload,
                    },
                    indent=2,
                )
            ]

        written = pbr_generate.write_generated_texture(
            source_png=source_png,
            texture_name=texture_name,
            texture_directory=directory,
            model=model,
            seed=seed,
            steps=steps,
            width_px=width,
            height_px=height,
            prompt=prompt,
            image_strength=image_strength,
            init_image_path=init_image_path,
        )

        summary = {
            "success": True,
            "texture_name": texture_name,
            "mac_path": written.mac_path,
            "big_path": written.big_path,
            "model": written.model,
            "seed": written.seed,
            "steps": written.steps,
            "width_px": written.width_px,
            "height_px": written.height_px,
            "prompt": written.prompt,
            "image_strength": written.image_strength,
            "init_image_path": written.init_image_path,
        }
        return [
            Image(data=Path(written.mac_path).read_bytes(), format="png"),
            json.dumps(summary, indent=2),
        ]

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Preview Texture",
            readOnlyHint=True,
            destructiveHint=False,
        )
    )
    async def preview_texture(
        object_name: str,
        resolution_px: int = 512,
        contact_sheet: bool = True,
    ) -> list:
        """Render the named object in a shader-accurate engine so its texture can be seen; returns the render as an image.

        This is the EEVEE render, NOT the Workbench contact sheet: Workbench
        reads only the material's viewport colour, so a texture reviewed
        through it is reviewed blind. `contact_sheet=True` returns the
        five-view sheet; `False` returns a single view.
        """
        require_live_blender()

        params = Params(
            object_name=object_name,
            resolution_px=resolution_px,
            contact_sheet=contact_sheet,
            repository_src=str(REPOSITORY_SRC),
            venv_site_packages=VENV_SITE_PACKAGES,
            source_fingerprint=source_fingerprint(),
        )
        code = toolcode_format_call(_TOOL_CALL, params)
        response = send_code(code, strict_json=True)
        if response.get("status") != "ok":
            return [
                json.dumps(
                    {
                        "success": False,
                        "error": str(response.get("message", "Unknown error"))[:2000],
                    },
                    indent=2,
                )
            ]

        result = response.get("result") or {}
        if result.get("status") != "ok":
            return [
                json.dumps(
                    {
                        "success": False,
                        "error": str(result.get("message", "Unknown error"))[:2000],
                    },
                    indent=2,
                )
            ]

        paths = list(result.get("paths") or [])
        if not paths:
            return [
                json.dumps(
                    {"success": False, "error": "The render wrote no image."}, indent=2
                )
            ]

        images = [Image(data=Path(path).read_bytes(), format="png") for path in paths]
        summary = {
            "success": True,
            "paths": paths,
            "engine": result.get("engine", ""),
            "resolution_px": result.get("resolution_px", resolution_px),
            "object_name": result.get("object_name", object_name),
        }
        return [images[0], json.dumps(summary, indent=2), *images[1:]]

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Export Texture Set",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
        )
    )
    async def export_texture_set(
        texture_name: str,
        texture_dir: str = "",
        destination: str = "",
    ) -> str:
        """Copy a texture set's maps and its metadata into the export directory; returns the written paths as JSON."""
        directory = Path(texture_dir) if texture_dir else pbr_paths.texture_root()
        target = Path(destination) if destination else directory / texture_name
        report = pbr_generate.export_texture_set(
            texture_name,
            directory,
            target,
            metadata={"channel_packing": pbr_paths.ORM_CHANNEL_PACKING},
        )
        return json.dumps(report, indent=2)


def _first_json_payload(result) -> dict | None:
    """The first JSON object in a tool result's text content, or None."""
    for block in result.content or []:
        text = getattr(block, "text", None)
        if not text:
            continue
        try:
            payload = json.loads(text)
        except (TypeError, ValueError):
            continue
        if isinstance(payload, dict):
            return payload
    return None


def _error_text(result, tool_name: str) -> str:
    """The text of a failed remote call."""
    texts = [
        getattr(block, "text", "")
        for block in result.content or []
        if getattr(block, "text", "")
    ]
    return json.dumps(
        {
            "success": False,
            "error": f"{tool_name} failed on the golem server.",
            "detail": "\n".join(texts)[:2000],
        },
        indent=2,
    )


def _resolve_generated_png(payload: dict) -> Path | None:
    """The generated PNG on a filesystem this process can open.

    The golem server writes the image into its own output directory and
    publishes a copy under the codex root; the codex copy is the one
    this process can open, so it is preferred.
    """
    reference_dir = payload.get("reference_dir")
    if reference_dir:
        candidate = Path(reference_dir) / "reference.png"
        if candidate.is_file():
            return candidate

    remote_path = payload.get("remote_path")
    if remote_path:
        try:
            candidate = Path(pbr_paths.big_path(remote_path))
        except ValueError:
            candidate = None
        if candidate is not None and candidate.is_file():
            return candidate

    local_path = payload.get("local_path")
    if local_path:
        candidate = Path(local_path)
        if candidate.is_file():
            return candidate

    return None
