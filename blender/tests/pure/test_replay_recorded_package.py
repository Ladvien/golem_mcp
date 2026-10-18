"""Recorded run_python sources name the package as it was when recorded."""

from golem_blender.evaluate.replay import rename_recorded_package


def test_every_name_token_is_pointed_at_the_current_package():
    recorded = (
        "from blended.ops.legs import add_leg\n"
        "import blended.ops as ops\n"
        "x = blended.ops.primitives.add_box\n"
    )
    assert rename_recorded_package(recorded) == (
        "from golem_blender.ops.legs import add_leg\n"
        "import golem_blender.ops as ops\n"
        "x = golem_blender.ops.primitives.add_box\n"
    )


def test_strings_and_comments_are_left_as_recorded():
    recorded = "name = 'blended'  # blended stays\n"
    assert rename_recorded_package(recorded) == recorded


def test_a_source_that_does_not_tokenize_is_returned_unchanged():
    assert rename_recorded_package('"""unterminated') == '"""unterminated'
