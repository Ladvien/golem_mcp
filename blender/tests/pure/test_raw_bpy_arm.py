"""The raw-bpy arms' reply parsing: what counts as a script, and what a
malformed one reports. Pure.

Schema conformance for arms A3-A5 of the fine-tune decision experiment is
`extract_python` returning text AND `parses` saying yes, so every case
here is a rate this experiment reports.
"""

from __future__ import annotations

from blended.evaluate.raw_bpy_arm import extract_python, parses

SCRIPT = "import bpy\n\nbpy.ops.mesh.primitive_cube_add(size=2.0)\n"


def test_a_fenced_reply_yields_the_source_inside_the_fence():
    reply = f"```python\n{SCRIPT}```"
    assert extract_python(reply) == SCRIPT.strip()
    assert parses(extract_python(reply)) == (True, "")


def test_an_unfenced_reply_is_the_script_itself():
    assert extract_python(SCRIPT) == SCRIPT.strip()


def test_prose_around_a_fence_is_dropped():
    reply = (
        "Here is the code you asked for:\n\n"
        f"```py\n{SCRIPT}```\n\n"
        "Hope this helps! Let me know if you want ribs."
    )
    extracted = extract_python(reply)
    assert extracted == SCRIPT.strip()
    assert "Hope this helps" not in extracted and "Here is the code" not in extracted


def test_a_broken_indent_is_refused_and_names_its_line():
    ok, detail = parses(
        "import bpy\nfor i in range(3):\nbpy.ops.mesh.primitive_cube_add()\n"
    )
    assert not ok
    assert "IndentationError" in detail and "line 3" in detail


def test_an_empty_reply_has_no_script_at_all():
    assert extract_python("") is None
    assert extract_python("   \n\n") is None
    assert extract_python(None) is None
