"""Does the rewritten test still catch a broken timeout branch?

Copies the repo's gpu.py to a scratch module, removes the `except TimeoutExpired`
branch, runs the REAL test against the mutated module, and reports.
"""
import pathlib, shutil, subprocess, sys, tempfile

repo = pathlib.Path("/Users/ladvien/golem_mcp")
scratch = pathlib.Path(tempfile.mkdtemp())
pkg = scratch / "golem_mcp"
pkg.mkdir()
shutil.copy(repo / "src/golem_mcp/gpu.py", pkg / "gpu.py")
(pkg / "__init__.py").write_text("")
shutil.copy(repo / "tests/test_gpu.py", scratch / "test_gpu.py")

source = (pkg / "gpu.py").read_text()
marker = "        except subprocess.TimeoutExpired:\n            _stop(proc)\n            raise GpuJobError(f\"{label} exceeded {timeout_s}s and was killed\") from None\n"
assert marker in source, "timeout branch not found verbatim"
broken = source.replace(
    marker,
    "        except subprocess.TimeoutExpired:\n            proc.kill()\n            proc.communicate()\n",
)
(pkg / "gpu.py").write_text(broken)

result = subprocess.run(
    [sys.executable, "-m", "pytest", str(scratch / "test_gpu.py"), "-q", "-k", "timeout_is_terminated", "-p", "no:cacheprovider"],
    capture_output=True, text=True, cwd=scratch, env={"PYTHONPATH": str(scratch), "PATH": "/usr/bin:/bin:/usr/sbin:/sbin"},
)
print("with the raise removed (job killed but NOT reported):")
print(result.stdout.strip().splitlines()[-1] if result.stdout.strip() else result.stderr[-400:])
print("exit code:", result.returncode)
