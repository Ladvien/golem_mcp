"""Loads and renders the prompt templates in `prompts/`.

The prompt is the tunable artifact of this harness, so it lives as text
a person (or another agent) can read and diff — one file per revision —
rather than as string surgery inside a module. `prompt_versions.py`
stays the registry: it says which revisions exist, what each one changed
and what that change measured. This module only turns a template into
text.

WHY JINJA AND NOT str.format: the prompt bodies are prose full of
braces-adjacent markdown and code, and `format` would choke on any of
it. Jinja's delimiters (`{{ }}`, `{% %}`, `{# #}`) appear nowhere in the
bodies — asserted in tests, so the day one does the collision is a red
test, not a mangled prompt.

BLENDER: jinja2 is not in Blender's bundled Python; a lane that runs
blended inside Blender puts the venv's site-packages on sys.path (the
bench prelude, the MCP bridge tool-code). There is no fallback renderer,
because a second rendering path is a second prompt.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

PROMPT_DIRECTORY = Path(__file__).resolve().parent / "prompts"
TEMPLATE_SUFFIX = ".md.j2"
WORKING_AGREEMENT_STEM = "working_agreement_v"
# Skill modules live one level down so `available_revisions()` keeps its
# flat glob and a new skill can never be mistaken for a revision.
SKILL_SUBDIRECTORY = "skills"
SKILL_DIRECTORY = PROMPT_DIRECTORY / SKILL_SUBDIRECTORY


class TemplateNotFound(FileNotFoundError):
    """Named template is absent. There is no default template."""


@lru_cache(maxsize=1)
def _environment():
    from jinja2 import Environment, FileSystemLoader, StrictUndefined

    return Environment(
        loader=FileSystemLoader(str(PROMPT_DIRECTORY)),
        # An undefined variable must be an error, not an empty string.
        # A prompt with a silently blank section is the worst kind of
        # bug here: it still runs, and the agent simply never learns the
        # thing that section existed to tell it.
        undefined=StrictUndefined,
        # The bodies are whitespace-significant markdown: bullet
        # indentation and blank lines between paragraphs are load
        # bearing, and a trailing newline is part of the text.
        keep_trailing_newline=True,
        trim_blocks=False,
        lstrip_blocks=False,
        autoescape=False,
    )


def template_path(name: str) -> Path:
    path = PROMPT_DIRECTORY / f"{name}{TEMPLATE_SUFFIX}"
    if not path.exists():
        available = ", ".join(
            sorted(
                str(p.relative_to(PROMPT_DIRECTORY))
                for p in PROMPT_DIRECTORY.rglob("*.j2")
            )
        )
        raise TemplateNotFound(f"No template {path.name!r}. Available: {available}.")
    return path


def render(name: str, **variables) -> str:
    """Render one template by stem (no suffix)."""
    template_path(name)  # raise a useful error before jinja raises a vague one
    return _environment().get_template(f"{name}{TEMPLATE_SUFFIX}").render(**variables)


def render_working_agreement(revision: int) -> str:
    return render(f"{WORKING_AGREEMENT_STEM}{revision}")


def available_revisions() -> tuple[int, ...]:
    """Revision numbers that have a template on disk, ascending."""
    found = []
    for path in PROMPT_DIRECTORY.glob(f"{WORKING_AGREEMENT_STEM}*{TEMPLATE_SUFFIX}"):
        stem = path.name[len(WORKING_AGREEMENT_STEM) : -len(TEMPLATE_SUFFIX)]
        if stem.isdigit():
            found.append(int(stem))
    return tuple(sorted(found))


def render_skill(name: str) -> str:
    """Render one capability module by stem (no suffix, no directory)."""
    return render(f"{SKILL_SUBDIRECTORY}/{name}")


def available_skills() -> tuple[str, ...]:
    """Skill module names that have a template on disk, sorted."""
    return tuple(
        sorted(
            path.name[: -len(TEMPLATE_SUFFIX)]
            for path in SKILL_DIRECTORY.glob(f"*{TEMPLATE_SUFFIX}")
        )
    )
