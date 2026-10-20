# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Checks that the MCP server exposes the expected tool listing.
"""

__all__ = ()

import asyncio
import os
import sys
import unittest

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from golem_blender.agent.tools import TOOL_SCHEMAS

# Root of the repository.
_REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The tools golem_blender serves beside the upstream ones.
_GOLEM_BLENDER_TOOL_NAMES = frozenset(schema["function"]["name"] for schema in TOOL_SCHEMAS)

# Complete expected tool listing.
# When a tool is added, changed, or removed this must be updated.
# Run with `--update` to regenerate from a live server query.

# BEGIN: EXPECTED_TOOLS
EXPECTED_TOOLS = [
    {
        "name": "get_blendfile_summary_datablocks",
        "description": "\n"
        "Return a summary of the blend file: data-block counts, active workspace, and render engine.\n",
        "inputSchema": {
            "properties": {},
            "title": "get_blendfile_summary_datablocksArguments",
            "type": "object",
        },
    },
    {
        "name": "get_blendfile_summary_datablocks_for_cli",
        "description": "\n"
        "Return a data-block summary, answered by the open Blender, which must have *blend_file* open or the call pauses.\n",
        "inputSchema": {
            "properties": {"blend_file": {"title": "Blend File", "type": "string"}},
            "required": ["blend_file"],
            "title": "get_blendfile_summary_datablocks_for_cliArguments",
            "type": "object",
        },
    },
    {
        "name": "get_blendfile_summary_missing_files",
        "description": "\n"
        "Report external file references that are missing from disk\n"
        "(images, libraries, fonts, sounds, movie clips, caches, sequences).\n",
        "inputSchema": {
            "properties": {},
            "title": "get_blendfile_summary_missing_filesArguments",
            "type": "object",
        },
    },
    {
        "name": "get_blendfile_summary_missing_files_for_cli",
        "description": "\n"
        "Report missing file references, answered by the open Blender, which must have *blend_file* open or the call pauses.\n",
        "inputSchema": {
            "properties": {"blend_file": {"title": "Blend File", "type": "string"}},
            "required": ["blend_file"],
            "title": "get_blendfile_summary_missing_files_for_cliArguments",
            "type": "object",
        },
    },
    {
        "name": "get_blendfile_summary_of_linked_libraries",
        "description": "\n"
        "Return a tree of directly and indirectly linked library files.\n",
        "inputSchema": {
            "properties": {},
            "title": "get_blendfile_summary_of_linked_librariesArguments",
            "type": "object",
        },
    },
    {
        "name": "get_blendfile_summary_of_linked_libraries_for_cli",
        "description": "\n"
        "Return linked-library info, answered by the open Blender, which must have *blend_file* open or the call pauses.\n",
        "inputSchema": {
            "properties": {"blend_file": {"title": "Blend File", "type": "string"}},
            "required": ["blend_file"],
            "title": "get_blendfile_summary_of_linked_libraries_for_cliArguments",
            "type": "object",
        },
    },
    {
        "name": "get_blendfile_summary_path_info",
        "description": "\n"
        "Simple/fast access to the blend file's path, save status, age, and backups.\n",
        "inputSchema": {
            "properties": {},
            "title": "get_blendfile_summary_path_infoArguments",
            "type": "object",
        },
    },
    {
        "name": "get_blendfile_summary_path_info_for_cli",
        "description": "\n"
        "Return path info, answered by the open Blender, which must have *blend_file* open or the call pauses.\n",
        "inputSchema": {
            "properties": {"blend_file": {"title": "Blend File", "type": "string"}},
            "required": ["blend_file"],
            "title": "get_blendfile_summary_path_info_for_cliArguments",
            "type": "object",
        },
    },
    {
        "name": "get_blendfile_summary_usage_guess",
        "description": "\n"
        "Guess the primary use-cases of the current blend file (scored 0-100 with certainty).\n",
        "inputSchema": {
            "properties": {},
            "title": "get_blendfile_summary_usage_guessArguments",
            "type": "object",
        },
    },
    {
        "name": "get_blendfile_summary_usage_guess_for_cli",
        "description": "\n"
        "Guess use-cases, answered by the open Blender, which must have *blend_file* open or the call pauses.\n",
        "inputSchema": {
            "properties": {"blend_file": {"title": "Blend File", "type": "string"}},
            "required": ["blend_file"],
            "title": "get_blendfile_summary_usage_guess_for_cliArguments",
            "type": "object",
        },
    },
    {
        "name": "get_object_detail_summary",
        "description": "\n"
        "Return a structured summary of the object identified by *name*.\n"
        "\n"
        "Includes type, transforms, parent, children, modifiers, constraints,\n"
        "materials, visibility, data-block name, and collections.\n",
        "inputSchema": {
            "properties": {"name": {"title": "Name", "type": "string"}},
            "required": ["name"],
            "title": "get_object_detail_summaryArguments",
            "type": "object",
        },
    },
    {
        "name": "get_objects_summary",
        "description": "\n"
        "Return the scene's collection hierarchy and their objects.\n"
        "\n"
        "Each collection lists its objects (name, type, parent, data name,\n"
        "selection, visibility) and nested child collections.\n",
        "inputSchema": {
            "properties": {},
            "title": "get_objects_summaryArguments",
            "type": "object",
        },
    },
    {
        "name": "get_python_api_docs",
        "description": "\n"
        "Return the Blender Python API docs for *identifier*, or list\n"
        "modules matching a trailing-``*`` discovery pattern.\n"
        "\n"
        "*identifier* should be a fully-qualified Python name (e.g.\n"
        "``bpy.app`` or ``bpy.types.Scene.frame_current``).\n"
        "The trailing-``*`` forms are supported as discovery entry-points:\n"
        "\n"
        "- ``*`` enumerates the top-level modules (``bpy``, ``bmesh``,\n"
        "  ``mathutils``, ``gpu``, ...).\n"
        "- ``X.*`` enumerates the direct-child identifiers under the\n"
        "  *X* namespace (``bpy.*`` -> ``bpy.app``, ``bpy.context``, ...).\n"
        "\n"
        "Both return a ``namespace`` response even when ``X.rst`` would\n"
        "otherwise resolve to ``exact``; the ``.*`` form lets an agent\n"
        "force the child listing.\n"
        "\n"
        "The response always carries ``kind``, ``found``, and ``identifier``.\n"
        "The remaining keys depend on ``kind``:\n"
        "\n"
        '- ``"exact"`` (``found=True``): ``<identifier>.rst`` was read.\n'
        "  Extra keys: ``content`` (RST text), ``examples``. When the\n"
        "  file exceeds 32 KB, ``content`` is replaced with a dot-point\n"
        "  summary of the file's top-level definitions (prefixed by a\n"
        "  header noting the truncation) and ``examples`` is empty -\n"
        "  re-query individual members for their rendered blocks.\n"
        '- ``"namespace"`` (``found=True``):\n'
        "  no ``<identifier>.rst`` but ``<identifier>.<child>.rst`` siblings exist.\n"
        "  Extra key: ``submodules`` (list of child identifiers).\n"
        '- ``"definition"`` (``found=True``):\n'
        "  *identifier* is defined inside a parent RST\n"
        "  (e.g. ``bpy.props.IntProperty`` lives in ``bpy.props.rst``).\n"
        "  Extra keys: ``content`` (rendered block), ``examples``.\n"
        '- ``"partial"`` (``found=False``):\n'
        "  the parent RST was located but the trailing component isn't defined in it.\n"
        "  Extra keys:\n"
        "  - ``parent`` the identifier whose RST was loaded.\n"
        "  - ``available`` top-level definitions in that RST.\n"
        "  - ``submodules`` sibling identifiers ``<parent>.<child>`` with their own RSTs,\n"
        "    filtered to those whose last component contains every character of the missing tail.\n"
        "\n"
        "  For a toctree landing page like ``bpy.types`` ``available`` is empty and ``submodules``\n"
        "  is the near-miss list; for a self-contained module like ``bpy.props`` it's the reverse.\n"
        '- ``"suggestions"`` (``found=False``):\n'
        "  no direct match, but *identifier* appears as a component of other files.\n"
        "  Extra key: ``suggestions`` (list of full identifiers).\n"
        '- ``"missing"`` (``found=False``): nothing matched.\n'
        "\n"
        "``examples`` (present on the ``exact`` and ``definition`` kinds)\n"
        "is a list of ``{path, content}`` entries referenced from this documentation.\n",
        "inputSchema": {
            "properties": {"identifier": {"title": "Identifier", "type": "string"}},
            "required": ["identifier"],
            "title": "get_python_api_docsArguments",
            "type": "object",
        },
    },
    {
        "name": "get_screenshot_of_area_as_image",
        "description": "\n"
        "Take a screenshot of a single Blender area and return it as a PNG image.\n"
        "\n"
        "*area_ui_type* matches the area's ``ui_type``.\n"
        "\n"
        "*size_limit_in_bytes* caps the image size in bytes.\n"
        "Zero (the default) uses the MCP message size limit.\n",
        "inputSchema": {
            "properties": {
                "area_ui_type": {
                    "enum": [
                        "VIEW_3D",
                        "IMAGE_EDITOR",
                        "UV",
                        "ShaderNodeTree",
                        "CompositorNodeTree",
                        "GeometryNodeTree",
                        "TextureNodeTree",
                        "SEQUENCE_EDITOR",
                        "CLIP_EDITOR",
                        "DOPESHEET_EDITOR",
                        "GRAPH_EDITOR",
                        "NLA_EDITOR",
                        "TEXT_EDITOR",
                        "CONSOLE",
                        "INFO",
                        "TOPBAR",
                        "STATUSBAR",
                        "OUTLINER",
                        "PROPERTIES",
                        "FILE_BROWSER",
                        "SPREADSHEET",
                        "PREFERENCES",
                    ],
                    "title": "Area Ui Type",
                    "type": "string",
                },
                "size_limit_in_bytes": {
                    "default": 0,
                    "title": "Size Limit In Bytes",
                    "type": "integer",
                },
            },
            "required": ["area_ui_type"],
            "title": "get_screenshot_of_area_as_imageArguments",
            "type": "object",
        },
    },
    {
        "name": "get_screenshot_of_window_as_image",
        "description": "\n"
        "Take a screenshot of the entire Blender window and return it as a PNG image.\n"
        "\n"
        "*size_limit_in_bytes* caps the image size in bytes.\n"
        "Zero (the default) uses the MCP message size limit.\n",
        "inputSchema": {
            "properties": {
                "size_limit_in_bytes": {
                    "default": 0,
                    "title": "Size Limit In Bytes",
                    "type": "integer",
                }
            },
            "title": "get_screenshot_of_window_as_imageArguments",
            "type": "object",
        },
    },
    {
        "name": "get_screenshot_of_window_as_json",
        "description": "\n"
        "Return a JSON description of the Blender window layout, areas, active object, and selection.\n",
        "inputSchema": {
            "properties": {},
            "title": "get_screenshot_of_window_as_jsonArguments",
            "type": "object",
        },
    },
    {
        "name": "register_kit_pack",
        "description": "Register a folder of .glb pieces (e.g. a Kenney pack) as a golem kit (kit.yaml) with measured sizes, for kitbashing new assets.",
        "inputSchema": {
            "properties": {
                "pack_dir": {"title": "Pack Dir", "type": "string"},
                "kit_dir": {"title": "Kit Dir", "type": "string"},
                "kit_name": {"title": "Kit Name", "type": "string"},
                "license": {"title": "License", "type": "string"},
            },
            "required": ["pack_dir", "kit_dir", "kit_name", "license"],
            "title": "register_kit_packArguments",
            "type": "object",
        },
    },
    {
        "name": "generate_texture_base",
        "description": "Generate a base-colour texture on the golem server and write it into the texture set; returns the image and its paths.\n"
        "\n"
        "`init_image_path` refines an existing map: it must be a path under\n"
        "the codex root (the Mac's `~/mnt/codex_fs/...`). `image_strength`\n"
        "is how much of the init image the result KEEPS: 1 is the init\n"
        "almost unchanged, 0 discards it. Measured, not assumed \u2014 the\n"
        "mean difference from the init was 0.5 at strength 1.0, 17.1 at\n"
        "0.6, 45.2 at 0.25 and 37.3 at 0.0. So to REPLACE the map, use a\n"
        "LOW strength; to keep it and nudge it, use a HIGH one. The\n"
        "written file is `T_<output_name>_BaseColor.png`.\n",
        "inputSchema": {
            "properties": {
                "prompt": {"title": "Prompt", "type": "string"},
                "output_name": {
                    "default": "",
                    "title": "Output Name",
                    "type": "string",
                },
                "model": {
                    "default": "flux2-klein-4b",
                    "title": "Model",
                    "type": "string",
                },
                "seed": {"default": 42, "title": "Seed", "type": "integer"},
                "steps": {"default": 8, "title": "Steps", "type": "integer"},
                "width": {"default": 1024, "title": "Width", "type": "integer"},
                "height": {"default": 1024, "title": "Height", "type": "integer"},
                "init_image_path": {
                    "default": "",
                    "title": "Init Image Path",
                    "type": "string",
                },
                "image_strength": {
                    "default": 0.4,
                    "title": "Image Strength",
                    "type": "number",
                },
                "texture_dir": {
                    "default": "",
                    "title": "Texture Dir",
                    "type": "string",
                },
            },
            "required": ["prompt"],
            "title": "generate_texture_baseArguments",
            "type": "object",
        },
    },
    {
        "name": "preview_texture",
        "description": "Render the named object in a shader-accurate engine so its texture can be seen; returns the render as an image.\n"
        "\n"
        "This is the EEVEE render, NOT the Workbench contact sheet: Workbench\n"
        "reads only the material's viewport colour, so a texture reviewed\n"
        "through it is reviewed blind. `contact_sheet=True` returns the\n"
        "five-view sheet; `False` returns a single view.\n",
        "inputSchema": {
            "properties": {
                "object_name": {"title": "Object Name", "type": "string"},
                "resolution_px": {
                    "default": 512,
                    "title": "Resolution Px",
                    "type": "integer",
                },
                "contact_sheet": {
                    "default": True,
                    "title": "Contact Sheet",
                    "type": "boolean",
                },
            },
            "required": ["object_name"],
            "title": "preview_textureArguments",
            "type": "object",
        },
    },
    {
        "name": "export_texture_set",
        "description": "Copy a texture set's maps and its metadata into the export directory; returns the written paths as JSON.\n"
        "\n"
        "`extras` are files copied alongside the maps \u2014 the environment\n"
        "map the set was lit with, the reference photos it was authored\n"
        "from. Without them the export says how the set was MADE but not\n"
        "how to light it, so it is not reusable on its own.\n"
        "\n"
        "The export directory is written as a CLEAN SET: a file a\n"
        "previous export put there and this one does not include is\n"
        "removed, and the result says what was removed under \"removed\".\n"
        "A file no export claims is left alone.\n",
        "inputSchema": {
            "properties": {
                "texture_name": {"title": "Texture Name", "type": "string"},
                "texture_dir": {
                    "default": "",
                    "title": "Texture Dir",
                    "type": "string",
                },
                "destination": {
                    "default": "",
                    "title": "Destination",
                    "type": "string",
                },
                "extras": {
                    "anyOf": [
                        {"items": {"type": "string"}, "type": "array"},
                        {"type": "null"},
                    ],
                    "default": None,
                    "title": "Extras",
                },
            },
            "required": ["texture_name"],
            "title": "export_texture_setArguments",
            "type": "object",
        },
    },
    {
        "name": "search_reference_images",
        "description": "Search Openverse, Wikimedia Commons, Pexels and Brave for reference images; returns a numbered contact sheet and the items' sources and licenses.",
        "inputSchema": {
            "properties": {
                "query": {"title": "Query", "type": "string"},
                "sources": {
                    "anyOf": [
                        {"items": {"type": "string"}, "type": "array"},
                        {"type": "null"},
                    ],
                    "default": None,
                    "title": "Sources",
                },
                "count": {"default": 24, "title": "Count", "type": "integer"},
                "license_filter": {
                    "default": "any",
                    "title": "License Filter",
                    "type": "string",
                },
            },
            "required": ["query"],
            "title": "search_reference_imagesArguments",
            "type": "object",
        },
    },
    {
        "name": "save_reference_images",
        "description": "Download the numbered images of a search into the kit's codex_fs reference folder with provenance; returns Mac and big paths.",
        "inputSchema": {
            "properties": {
                "search_id": {"title": "Search Id", "type": "string"},
                "numbers": {
                    "items": {"type": "integer"},
                    "title": "Numbers",
                    "type": "array",
                },
                "kit_slug": {"title": "Kit Slug", "type": "string"},
            },
            "required": ["search_id", "numbers", "kit_slug"],
            "title": "save_reference_imagesArguments",
            "type": "object",
        },
    },
    {
        "name": "jump_to_tab_by_name",
        "description": "\nSwitch the active workspace tab to *name*.\n",
        "inputSchema": {
            "properties": {"name": {"title": "Name", "type": "string"}},
            "required": ["name"],
            "title": "jump_to_tab_by_nameArguments",
            "type": "object",
        },
    },
    {
        "name": "jump_to_tab_by_space_type",
        "description": "\n"
        "Switch to a workspace whose main area matches *space_type*.\n"
        "\n"
        "If *allow_edits* is True and no matching workspace exists, a new one\n"
        "is created by duplicating the current workspace.\n",
        "inputSchema": {
            "properties": {
                "space_type": {"title": "Space Type", "type": "string"},
                "allow_edits": {
                    "default": False,
                    "title": "Allow Edits",
                    "type": "boolean",
                },
            },
            "required": ["space_type"],
            "title": "jump_to_tab_by_space_typeArguments",
            "type": "object",
        },
    },
    {
        "name": "jump_to_view3d_object_by_name",
        "description": "\n"
        "Move the 3D viewport to focus on an object by *name*.\n"
        "\n"
        "golem's scene-changing tools frame the objects they touched on\n"
        "their own. Call this to show the user a different part, or one a\n"
        "`run_python` chunk changed without naming it.\n"
        "\n"
        "If *allow_edits* is True the object may be un-hidden and its\n"
        "collections enabled to make it visible.\n",
        "inputSchema": {
            "properties": {
                "name": {"title": "Name", "type": "string"},
                "allow_edits": {
                    "default": False,
                    "title": "Allow Edits",
                    "type": "boolean",
                },
            },
            "required": ["name"],
            "title": "jump_to_view3d_object_by_nameArguments",
            "type": "object",
        },
    },
    {
        "name": "jump_to_view3d_object_data_by_name",
        "description": "\n"
        "Move the 3D viewport to the object whose data block matches *name*.\n"
        "\n"
        "If *allow_edits* is True the object may be un-hidden and its\n"
        "collections enabled to make it visible.\n",
        "inputSchema": {
            "properties": {
                "name": {"title": "Name", "type": "string"},
                "allow_edits": {
                    "default": False,
                    "title": "Allow Edits",
                    "type": "boolean",
                },
            },
            "required": ["name"],
            "title": "jump_to_view3d_object_data_by_nameArguments",
            "type": "object",
        },
    },
    {
        "name": "render_thumbnail_to_path",
        "description": "\n"
        "Render a small, low-quality thumbnail into Blender's temp directory as\n"
        "``blender_mcp/<basename of output_path>`` (temporarily overrides settings);\n"
        "the format's extension is added when missing. Returns the written ``filepath``.\n",
        "inputSchema": {
            "properties": {"output_path": {"title": "Output Path", "type": "string"}},
            "required": ["output_path"],
            "title": "render_thumbnail_to_pathArguments",
            "type": "object",
        },
    },
    {
        "name": "render_viewport_to_path",
        "description": "\n"
        "Render the current scene into Blender's temp directory as ``blender_mcp/<basename of output_path>``\n"
        "using current render settings; the format's extension is added when missing.\n"
        "Returns the written ``filepath``.\n",
        "inputSchema": {
            "properties": {"output_path": {"title": "Output Path", "type": "string"}},
            "required": ["output_path"],
            "title": "render_viewport_to_pathArguments",
            "type": "object",
        },
    },
    {
        "name": "search_api_docs",
        "description": "\n"
        "Full-text search over the bundled Blender Python API reference.\n"
        "\n"
        "Returns a ranked list of hits. Each hit has:\n"
        "\n"
        "- ``path``: file path relative to the bundled docs.\n"
        "- ``text``: the matching paragraph plus ``context``\n"
        "  paragraphs on either side.\n"
        "- ``breadcrumb``: the section path containing the hit\n"
        "  (``Section > Sub-section > ...``).\n"
        "- ``index``: the hit's position in the result list.\n"
        "- ``score``: a relevance score; higher is better.\n"
        "\n"
        "The query is tokenised on whitespace and matched\n"
        "case-insensitively. Every token must appear somewhere in\n"
        "the paragraph body, the file path, or an enclosing section\n"
        "title - in any order. Common English stop-words (``the``,\n"
        "``a``, ``how``, ``to``, ...) are dropped, so natural\n"
        'phrasings like ``"how to bake"`` work as expected. Regular\n'
        "expressions are not supported.\n"
        "\n"
        "Use ``context`` to pull more surrounding paragraphs into\n"
        "each hit (symmetric, default 0). Use ``index`` with the\n"
        "position of a previous hit (same query) to get that hit\n"
        "alone with its text widened to its enclosing section.\n"
        "\n"
        "Read-only; consults bundled RST files only.\n",
        "inputSchema": {
            "properties": {
                "query": {"title": "Query", "type": "string"},
                "max_results": {
                    "default": 20,
                    "title": "Max Results",
                    "type": "integer",
                },
                "context": {"default": 0, "title": "Context", "type": "integer"},
                "index": {
                    "anyOf": [{"type": "integer"}, {"type": "null"}],
                    "default": None,
                    "title": "Index",
                },
            },
            "required": ["query"],
            "title": "search_api_docsArguments",
            "type": "object",
        },
    },
    {
        "name": "search_manual_docs",
        "description": "\n"
        "Full-text search over the bundled Blender user manual.\n"
        "\n"
        "Returns a ranked list of hits. Each hit has:\n"
        "\n"
        "- ``path``: file path relative to the bundled docs.\n"
        "- ``text``: the matching paragraph plus ``context``\n"
        "  paragraphs on either side.\n"
        "- ``breadcrumb``: the section path containing the hit\n"
        "  (``Section > Sub-section > ...``).\n"
        "- ``index``: the hit's position in the result list.\n"
        "- ``score``: a relevance score; higher is better.\n"
        "\n"
        "The query is tokenised on whitespace and matched\n"
        "case-insensitively. Every token must appear somewhere in\n"
        "the paragraph body, the file path, or an enclosing section\n"
        "title - in any order. Common English stop-words (``the``,\n"
        "``a``, ``how``, ``to``, ...) are dropped, so natural\n"
        'phrasings like ``"how to bake"`` work as expected. Regular\n'
        "expressions are not supported.\n"
        "\n"
        "Use ``context`` to pull more surrounding paragraphs into\n"
        "each hit (symmetric, default 0). Use ``index`` with the\n"
        "position of a previous hit (same query) to get that hit\n"
        "alone with its text widened to its enclosing section.\n"
        "\n"
        "Read-only; consults bundled RST files only.\n",
        "inputSchema": {
            "properties": {
                "query": {"title": "Query", "type": "string"},
                "max_results": {
                    "default": 20,
                    "title": "Max Results",
                    "type": "integer",
                },
                "context": {"default": 0, "title": "Context", "type": "integer"},
                "index": {
                    "anyOf": [{"type": "integer"}, {"type": "null"}],
                    "default": None,
                    "title": "Index",
                },
            },
            "required": ["query"],
            "title": "search_manual_docsArguments",
            "type": "object",
        },
    },
]
# END: EXPECTED_TOOLS


def _list_tools() -> list[dict[str, object]]:
    """
    Starts the MCP server and returns the full tool listing.
    """

    # Async is required because the MCP client SDK is async-only.
    async def _run() -> list[dict[str, object]]:
        env = os.environ.copy()
        env["PYTHONPATH"] = os.path.join(_REPO_DIR, "mcp")
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "blmcp"],
            env=env,
        )
        async with (
            stdio_client(params) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            result = await session.list_tools()
            # golem_blender's surface is pinned by TOOL_SCHEMAS_FINGERPRINT;
            # this snapshot pins the upstream tools only.
            return [
                {
                    "name": t.name,
                    "description": t.description,
                    "inputSchema": t.inputSchema,
                }
                for t in result.tools
                if t.name not in _GOLEM_BLENDER_TOOL_NAMES
            ]

    return asyncio.run(_run())


class TestToolListing(unittest.TestCase):
    """
    Checks that the live tool listing matches the frozen snapshot.
    """

    _tools: list[dict[str, object]]

    @classmethod
    def setUpClass(cls) -> None:
        cls._tools = _list_tools()

    def test_tools_match_expected(self) -> None:
        """
        Checks that the live tool listing exactly matches ``EXPECTED_TOOLS``.
        """
        self.assertEqual(self._tools, EXPECTED_TOOLS)


def _update_expected_tools() -> None:
    """
    Re-generates the ``EXPECTED_TOOLS`` block from a live server query.
    """
    import json
    import subprocess

    filepath = os.path.abspath(__file__)
    with open(filepath, "r", encoding="utf-8") as fh:
        source = fh.read()
    begin = source.index("# BEGIN: EXPECTED_TOOLS\n") + len("# BEGIN: EXPECTED_TOOLS\n")
    end = source.index("# END: EXPECTED_TOOLS\n")
    formatted = json.dumps(_list_tools(), indent=4)
    formatted = (
        formatted.replace(": true", ": True")
        .replace(": false", ": False")
        .replace(": null", ": None")
    )
    formatted = formatted.replace("\\n", '\\n"\n"')
    # Also handles the `\n"` case (no trailing empty string).
    formatted = formatted.replace('\\n"\n""', '\\n"')
    formatted = "EXPECTED_TOOLS = " + formatted + "\n"
    with open(filepath, "w", encoding="utf-8") as fh:
        fh.write(source[:begin] + formatted + source[end:])
    subprocess.check_call(["autopep8", "--in-place", filepath])


if __name__ == "__main__":
    if "--update" in sys.argv:
        sys.argv.remove("--update")
        _update_expected_tools()
    else:
        unittest.main()
