"""The raw-bpy answer format: the benchmark's own prompt, and parsing a reply.

The harness has no raw-bpy output path — every scored script it emits is
assembled by `bench_bridge.standalone_script` from recorded tool calls.
The fine-tune decision experiment
(`docs/research/2026-09-19-finetune-decision-experiment.md`) needs the
other format for its control arms A3-A5, which answer with a whole
Python file and no tools at all.

Two decisions worth stating, because a different choice changes the
numbers:

* The system prompt is the **benchmark's own**
  `prompts/text_to_3d_system_prompt.txt`, read verbatim, not a new one
  written here. It already demands "nothing but Python", names the
  Blender Python API, forbids network/`os`/`sys` imports, asks for one
  object at the origin and no render, and states the 240 s budget. Using
  it keeps A3-A5 comparable to 3DCodeBench's published baselines
  (DOI 10.48550/arXiv.2606.01057) and keeps the prompt-parity diff
  against the op arms small and auditable.
* Extraction is deliberately TOLERANT (a fenced block wins, otherwise
  the whole reply), because the spec's stage-1 metric is schema
  conformance and a reply that is valid Python inside a fence is a
  formatting deviation, not a code-writing failure. The benchmark's own
  `core/visual_critique._extract_code` is private and sits beside a
  broken constant (`_PROMPT_DIR` points at `prompt/` while the directory
  on disk is `prompts/`), so it is not importable here.

Pure Python: no `bpy`, so the raw arms run in the host venv and this
module is testable in the pure suite.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from blended.evaluate.bench_task_prompt import RAW_TASK_TEMPLATE

# Relative to the benchmark checkout root.
RAW_SYSTEM_PROMPT_PATH = "prompts/text_to_3d_system_prompt.txt"

# A fenced block anywhere in the reply, ```python / ```py / bare ```.
_FENCED_BLOCK = re.compile(r"```(?:python|py)?[ \t]*\n(.*?)(?:```|\Z)", re.DOTALL)
# A reply that is itself fenced, with nothing outside the fence.
_LEADING_FENCE = re.compile(r"^\s*```(?:python|py)?[ \t]*\n?", re.IGNORECASE)
_TRAILING_FENCE = re.compile(r"\n?\s*```\s*$", re.IGNORECASE)


def raw_system_prompt(bench_root: Path | str) -> str:
    """3DCodeBench's own text-to-3D system prompt, verbatim.

    A missing file is fatal: an arm run against a prompt this harness
    invented instead of the benchmark's would not be the measurement the
    spec registered.
    """
    path = Path(bench_root) / RAW_SYSTEM_PROMPT_PATH
    return path.read_text()


def raw_task_text(description: str) -> str:
    """The op arms' task text minus the one bullet naming `run_python`."""
    return RAW_TASK_TEMPLATE.format(description=description)


def extract_python(reply_text: str | None) -> str | None:
    """The Python source in a reply, or None when there is none.

    Precedence: a fenced block if the reply has one, else the whole
    reply with any stray leading/trailing fence removed. An empty or
    whitespace-only reply returns None — that is the spec's `O2`, "no
    usable output", and it must not be reported as a syntax error.
    """
    if not reply_text or not reply_text.strip():
        return None
    match = _FENCED_BLOCK.search(reply_text)
    if match:
        source = match.group(1).strip()
        return source or None
    source = _TRAILING_FENCE.sub("", _LEADING_FENCE.sub("", reply_text.strip())).strip()
    return source or None


def parses(source: str) -> tuple[bool, str]:
    """(does it parse, the first line of the error).

    `ast.parse` only: a script that imports `bpy` cannot be compiled in
    the host venv, and executing it to find out is what the bake does.
    """
    try:
        ast.parse(source)
    except SyntaxError as error:
        return False, f"{type(error).__name__}: {error.msg} (line {error.lineno})"
    return True, ""
