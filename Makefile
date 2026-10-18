# golem is one repository with two environments that cannot be merged:
#   root      the GPU server on big (Python 3.11; torch and kimodo install on Linux only)
#   blender/  the Mac half beside Blender 5.2 (Python 3.13), see blender/Makefile
# --inexact keeps what is installed by hand (motion_correction on big, op plugins in blender/).
.PHONY: sync sync-golem sync-blender test test-golem test-blender test-blender-full

sync: sync-golem sync-blender

sync-golem:
	uv sync --python 3.11 --extra dev --inexact

sync-blender:
	$(MAKE) -C blender sync

test: test-golem test-blender

test-golem:
	uv run --frozen --extra dev pytest

test-blender:
	$(MAKE) -C blender test-pure test-mcp

test-blender-full:
	$(MAKE) -C blender test
