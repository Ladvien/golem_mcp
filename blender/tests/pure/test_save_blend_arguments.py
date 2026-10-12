"""OT-50: every exported asset ships with its .blend — the parts that need no Blender.

The write and the re-read are proven in tests/blender/test_save_blend.py;
this file pins the argument contract, the report shape and the two tool
schemas, so a regression shows on a machine without Blender too.
"""

import dataclasses
from pathlib import Path

import pytest

from blended.agent.tools import (
    SERVICE_TOOL_NAMES,
    TOOL_SCHEMAS,
    _required_blend_path,
)
from blended.export.blend import (
    BlendSaveError,
    BlendSaveReport,
    validate_blend_request,
)
from blended.harness import HarnessSettings, require_export_blend_path


def _tool(name: str) -> dict:
    return next(
        tool["function"] for tool in TOOL_SCHEMAS if tool["function"]["name"] == name
    )


def test_a_path_not_ending_in_blend_is_refused():
    for bad_path in ("thing.glb", "thing", "thing.blend1", "thing.BLEND"):
        with pytest.raises(BlendSaveError, match=r"\.blend"):
            validate_blend_request(["Thing"], Path("/tmp") / bad_path)


def test_no_names_and_repeated_names_are_refused():
    with pytest.raises(BlendSaveError, match="empty"):
        validate_blend_request([], Path("/tmp/thing.blend"))
    with pytest.raises(BlendSaveError, match="repeats"):
        validate_blend_request(["A", "A"], Path("/tmp/thing.blend"))
    with pytest.raises(BlendSaveError, match="list of names"):
        validate_blend_request("Thing", Path("/tmp/thing.blend"))
    with pytest.raises(BlendSaveError, match="non-empty string"):
        validate_blend_request(["Thing", ""], Path("/tmp/thing.blend"))


def test_a_good_request_comes_back_normalized():
    names, destination = validate_blend_request(["A", "B"], "/tmp/thing.blend")
    assert names == ("A", "B")
    assert destination == Path("/tmp/thing.blend")


def test_the_report_is_a_frozen_record_of_what_was_re_read():
    report = BlendSaveReport(
        blend_path=Path("/tmp/thing.blend"),
        file_size_bytes=10,
        object_names=("Thing",),
        triangle_counts={"Thing": 12},
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        report.file_size_bytes = 0  # type: ignore[misc]
    assert [field.name for field in dataclasses.fields(report)] == [
        "blend_path",
        "file_size_bytes",
        "object_names",
        "triangle_counts",
    ]


def test_export_asset_requires_a_blend_path_in_its_schema():
    schema = _tool("export_asset")["parameters"]
    assert "blend_path" in schema["properties"]
    assert set(schema["required"]) == {"object_name", "path", "blend_path"}


def test_save_blend_is_a_service_tool_with_its_two_required_arguments():
    assert "save_blend" in SERVICE_TOOL_NAMES
    schema = _tool("save_blend")["parameters"]
    assert schema["properties"]["object_names"]["type"] == "array"
    assert schema["properties"]["object_names"]["items"] == {"type": "string"}
    assert set(schema["required"]) == {"object_names", "blend_path"}


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"blend_path": ""},
        {"blend_path": "   "},
        {"blend_path": 7},
        {"blend_path": "relative/thing.blend"},
        {"blend_path": "/tmp/thing.glb"},
    ],
)
def test_the_tool_refuses_a_missing_or_bad_blend_path(arguments):
    blend_path, refusal = _required_blend_path(arguments)
    assert refusal, arguments
    assert ".blend" in refusal


def test_the_tool_accepts_an_absolute_blend_path():
    blend_path, refusal = _required_blend_path({"blend_path": "/tmp/thing.blend"})
    assert refusal == ""
    assert blend_path == Path("/tmp/thing.blend")


def test_a_glb_export_without_a_blend_path_is_refused_by_the_harness_settings():
    with pytest.raises(ValueError, match="export_blend_path"):
        require_export_blend_path(HarnessSettings(export_glb_path=Path("/tmp/a.glb")))
    # No export requested: no .blend needed. Both given: accepted.
    require_export_blend_path(HarnessSettings())
    require_export_blend_path(
        HarnessSettings(
            export_glb_path=Path("/tmp/a.glb"), export_blend_path=Path("/tmp/a.blend")
        )
    )
