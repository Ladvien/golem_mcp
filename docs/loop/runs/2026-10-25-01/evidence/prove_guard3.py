import pathlib, shutil, subprocess, sys, tempfile
repo = pathlib.Path("/Users/ladvien/golem_mcp")
scratch = pathlib.Path(tempfile.mkdtemp()); pkg = scratch / "golem_mcp"; pkg.mkdir()
shutil.copy(repo / "src/golem_mcp/gpu.py", pkg / "gpu.py"); (pkg / "__init__.py").write_text("")
shutil.copy(repo / "tests/test_gpu.py", scratch / "test_gpu.py")
src = (pkg / "gpu.py").read_text()
print("baseline call has a timeout:", "timeout=timeout_s + GPU_QUEUE_TIMEOUT_S" in src)
mutant = src.replace("timeout=timeout_s + GPU_QUEUE_TIMEOUT_S", "timeout=None")
(pkg / "gpu.py").write_text(mutant)
r = subprocess.run([sys.executable, "-m", "pytest", str(scratch/"test_gpu.py"), "-q", "-k", "timeout_is_terminated", "-p", "no:cacheprovider"],
    capture_output=True, text=True, cwd=scratch, env={"PYTHONPATH": str(scratch), "PATH": "/usr/bin:/bin:/usr/sbin:/sbin"}, timeout=120)
print(r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr[-300:]); print("exit:", r.returncode)
