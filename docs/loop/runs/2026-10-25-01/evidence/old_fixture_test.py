"""The OLD fixture, verbatim, at a 1 s timeout: does it survive a slow first exec?"""
import os, pathlib, subprocess, sys, tempfile, time

def old_fixture_run(delay_s: float) -> tuple[bool, int]:
    base = pathlib.Path(tempfile.mkdtemp())
    terminated = base / "terminated"
    script = base / "gpu-tenant"
    script.write_text(
        "#!/usr/bin/env bash\n"
        f"if [ -n \"$FAKE_EXEC_DELAY_S\" ]; then sleep \"$FAKE_EXEC_DELAY_S\"; fi\n"
        f"sleep 30 &\n"
        f"trap 'kill $!; echo done > {terminated}; exit 143' TERM\n"
        "wait\n"
    )
    script.chmod(0o755)
    proc = subprocess.Popen([str(script)], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, start_new_session=True,
                            env={**os.environ, "FAKE_EXEC_DELAY_S": str(delay_s)})
    try:
        proc.communicate(timeout=1)
    except subprocess.TimeoutExpired:
        proc.terminate(); proc.communicate(timeout=60)
    return terminated.exists(), proc.returncode

print("old fixture, 1 s timeout:")
for delay in (0.0, 0.05, 0.25, 0.5, 1.5):
    ran, rc = old_fixture_run(delay)
    print(f"  startup delay {delay:>4}s -> trap ran: {ran}, rc {rc}")
