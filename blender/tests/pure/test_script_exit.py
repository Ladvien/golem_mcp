"""OT-32: a Blender-hosted script's exit code must mean what it says.

Blender does not propagate an uncaught Python exception to its process
exit status — measured directly: `--python-expr "raise RuntimeError(...)"`
exits 0 while `raise SystemExit(3)` exits 3. Every chain in this repo
gates on exit codes, including the closing rule for a backlog item, so a
crash that reads as a success is the worst possible failure mode.
"""

from blended.run.script_exit import UNCAUGHT_EXCEPTION_EXIT_CODE, run_script_main


def test_a_clean_run_keeps_its_own_status():
    assert run_script_main(lambda: 0) == 0
    assert run_script_main(lambda: 2) == 2
    assert run_script_main(lambda: None) == 0  # a main that returns nothing succeeded
    assert run_script_main(lambda a, b: a + b, 1, 2) == 3


def test_a_deliberate_system_exit_passes_through():
    """A script that means to exit 2 still exits 2."""

    def refuses():
        raise SystemExit(2)

    assert run_script_main(refuses) == 2

    def bare():
        raise SystemExit

    assert run_script_main(bare) == 0

    def with_a_message():
        raise SystemExit("no instances in the file")

    assert run_script_main(with_a_message) == 1


def test_an_uncaught_exception_becomes_a_failing_status(capsys):
    """Measured 2026-09-10: iteration 109's visual gate raised EmptyFrame
    after the build and export, and `make converge` returned 0; three
    metered-lane briefs died on HTTP 429 and returned 0 too, so the chain
    recorded four successes it never had."""

    def dies():
        raise RuntimeError("the visual gate raised")

    assert run_script_main(dies) == UNCAUGHT_EXCEPTION_EXIT_CODE
    captured = capsys.readouterr()
    assert "the visual gate raised" in captured.err  # the traceback survives
    assert "would otherwise have exited 0" in captured.err


def test_an_interrupt_is_not_a_crash():
    def stopped():
        raise KeyboardInterrupt

    assert run_script_main(stopped) == 130


def test_every_blender_hosted_script_is_guarded():
    """The guard is worth nothing on the one entry point that forgets it."""
    from pathlib import Path

    scripts = Path(__file__).resolve().parents[2] / "scripts"
    hosted = [
        "run_agent_task.py",
        "chat_e2e.py",
        "calibrate_examiner.py",
        "calibrate_visual_gate.py",
        "pin_golden_views.py",
        "replay_iteration.py",
        "photo_to_model.py",
        "run_3dcode_instance.py",
    ]
    for name in hosted:
        source = (scripts / name).read_text()
        assert "run_script_main(main" in source, f"{name} exits 0 on a crash"
        assert "raise SystemExit(main(" not in source, (
            f"{name} still calls main unguarded"
        )


def test_the_code_is_the_conventional_software_error():
    assert UNCAUGHT_EXCEPTION_EXIT_CODE == 70  # EX_SOFTWARE
