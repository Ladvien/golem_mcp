"""OT-51: pose-bone data paths are read the way Blender writes them.

A pattern that stops at the first quote reads `pose.bones["a\\"b"]` as the
bone `a\\`: the clip reader would then report "no such bone" for a real
bone, or key the wrong one. These tests fail on that pattern.
"""

import pytest

from golem_blender.ops._pose_paths import (
    ROTATION_QUATERNION_CHANNEL,
    escape_identifier,
    parse_pose_bone_path,
    pose_bone_path,
)


@pytest.mark.parametrize(
    "bone_name",
    [
        "upperarm_l",
        "mixamorig:LeftArm",
        'quote"in',
        "back\\slash",
        'both\\"mixed',
        "dot.in.name",
        "bracket]name",
        "has space",
    ],
)
def test_a_path_round_trips_whatever_the_bone_is_called(bone_name):
    path = pose_bone_path(bone_name, ROTATION_QUATERNION_CHANNEL)

    parsed = parse_pose_bone_path(path)

    assert parsed is not None
    assert parsed.bone_name == bone_name
    assert parsed.channel == ROTATION_QUATERNION_CHANNEL


def test_a_quote_in_a_name_is_escaped_the_way_blender_writes_it():
    assert escape_identifier('a"b') == 'a\\"b'
    assert escape_identifier("a\\b") == "a\\\\b"
    assert pose_bone_path('a"b', "location") == 'pose.bones["a\\"b"].location'


@pytest.mark.parametrize(
    "data_path",
    [
        "location",
        'pose.bones["a"]',
        'pose.bones["a"]["custom_property"]',
        'pose.bones["a"].constraints["Copy"].influence',
        'pose.bones["a"].location[0]',
        'bones["a"].rotation_quaternion',
        "",
    ],
)
def test_a_path_that_is_not_a_plain_pose_bone_property_is_not_parsed(data_path):
    assert parse_pose_bone_path(data_path) is None
