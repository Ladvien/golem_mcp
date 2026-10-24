"""Does the rewritten test catch a timeout branch that REPORTS but never stops the job?"""
import pathlib, shutil, subprocess, sys, tempfile

repo = pathlib.Path("/Users/ladvien/golem_mcp")
scratch = pathlib.Path(tempfile.mkdtemp())
pkg = scratch / "golem_mcp"; pkg.mkdir()
shutil.copy(repo / "src/golem_mcp/gpu.py", pkg / "gpu.py")
(pkg / "__init__.py").write_text("")
shutil.copy(repo / "tests/test_gpu.py", scratch / "test_gpu.py")

source = (pkg / "gpu.py").read_text()
marker = ('        except subprocess.TimeoutExpired:\n'
          '            _stop(proc)\n'
          '            raise GpuJobError(f"{label} exceeded {timeout_s}s and was killed") from None\n')
assert marker in source
# Report the timeout but never stop the job: the sleep runs to 30 s.
broken = source.replace(marker,
    '        except subprocess.TimeoutExpired:\n'
    '            raise GpuJobError(f"{label} exceeded {timeout_s}s and was killed") from None\n')
(pkg / "gpu.py").write_text(broken)

result = subprocess.run(
    [sys.executable, "-m", "pytest", str(scratch / "test_gpu.py"), "-q", "-k", "timeout_is_terminated", "-p", "no:cacheprovider"],
    capture_output=True, text=True, cwd=scratch, env={"PYTHONPATH": str(scratch), "PATH": "/usr/bin:/bin:/usr/sbin:/sbin"},
)
print(result.stdout.strip().splitlines()[-1] if result.stdout.strip() else result.stderr[-500:])
print("exit code:", result.returncode)
