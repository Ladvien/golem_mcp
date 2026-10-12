# Blender MCPB Extension

## Description
A lightweight MCP (Model Context Protocol) server for Blender.

Allows LLM assistants to interact with a running Blender instance – inspecting scenes, executing Python code, rendering, and navigating the interface.

## Features
It supports running arbitrary Python code within Blender. This allows for advanced scene analysis and debugging. It also bundles the complete API and user manual, served through the `get_python_api_docs`, `search_api_docs` and `search_manual_docs` tools, helping the LLM to access the latest version of both documentations.

## Installation

In this repository the server is a workspace member of the root `pyproject.toml`, installed editable into `.venv` (entry point `blender-mcp`); this fork also serves blended's own tool surface, which the upstream package lacks. It requires an add-on in Blender for this to work.

### Add-on
* Run `make install-mcp-addon` from the repository root: it symlinks `blender_mcp/addon/blender_mcp_addon` into Blender, enables it and allows online access (its socket needs it).
* The add-on listens on `localhost:9876` (override with `BLENDER_MCP_HOST` / `BLENDER_MCP_PORT` on the server).
* The server only ever uses that open Blender. Every tool looks for it first; when nothing answers, the result is an error that starts with `PAUSED:` and tells the agent to stop and tell you. No tool starts a headless Blender, so `BLENDER_PATH` is gone. The five `*_for_cli` tools answer from the open Blender when it has that file open (unsaved edits count) and otherwise pause naming the file it has. The three docs-only tools do not need Blender and never pause.
* After every scene-changing blended call the 3D viewport is re-centred on what the call created or changed (the scene is compared before and after, so a `run_python` chunk that names nothing is covered), and the result ends with a `viewport:` line.

### Server options
* `--transport stdio|http` (default `stdio`); `--host` / `--port` apply to `http` only. `--host` must be a loopback address (`127.0.0.1`, `localhost`, `::1`): the tools run arbitrary Python in Blender with no authentication, so any other host exits with an error, and the HTTP transport rejects non-loopback `Host` and `Origin` headers (DNS-rebinding protection).
* `--exit-on-source-change` / `--no-exit-on-source-change` (default: off): exit once `src/blended` or `blmcp` changed and held still, so a client that restarts a server that exits (omp) re-lists fresh tools. Needs `--transport stdio`.

## Examples

You can find more examples in the [documentation](https://www.blender.org/lab/mcp-server/).

### Example 1: Data-block renaming: fix types

**Demo file**: [Pebble Scattering](https://www.blender.org/download/demo/geometry-nodes/fields/pebble_scattering.blend)

**User prompt**: "With the current open Blender file fix the name of all the data-blocks to remove typos. Report back which data-blocks got fixed."

**Expected behaviour:**
- `GRP-rocks` → `GRP-pebble` [optionally, this is more opiniated]
- `LGT-Lights` → `LGT-lights`
- `Compositing Nodetree` → `Compositing Node Tree`

### Example 2: Querying data relations using natural language

**Demo file**: [Pebble Scattering](https://www.blender.org/download/demo/geometry-nodes/fields/pebble_scattering.blend)

**User prompt**: "Which objects are using the following material: pebbles"

**Expected behaviour:**
7 objects:
- `GEO-pebble`
- `GEO-pebble.001`
- `GEO-pebble.002`
- `GEO-pebble.003`
- `GEO-pebble.004`
- `GEO-pebble.005`
- `GEO-pebble.006`

### Example 3: Querying data relations using natural language

**Demo file**: [Classroom](https://download.blender.org/demo/test/classroom.zip)

**User prompt**: "Analyze the scene and list the outliers: objects with highest polygon count but smaller size from the camera point of view."

**Expected behavior:**
An analysis that consider the final amount of polygons after the object modifiers are applied. This usually happens by getting the object from the dependency graph.

The biggest outliers are: `coat 1` and `alphabet`.

Depending on whether or not the RENDER context was used (as oppose to the VIEWPORT context), the biggest outlier (`coat 1`) may show 37k or 74k polygons. This is the only object that has a modifier which is only used for rendering. Every other object should report the same poly-count regardless of the context.

## Privacy Policy
See our privacy policy: https://www.blender.org/privacy-policy/

## Support
For issues: https://projects.blender.org/lab/blender_mcp/issues
