#!/usr/bin/env python3
"""Capture the environment every number in the fine-tune decision rests on.

    .venv/bin/python scripts/finetune_decision_env.py \\
        --bench-root /Users/ladvien/3dcodebench

Spec §2 of `docs/research/2026-09-19-finetune-decision-experiment.md`
lists seven preconditions and says to verify and RECORD all of them. A
precondition that fails is recorded as a field, not raised: the report
has to be able to say which one, and a half-written `env.json` says
nothing.

Writes `docs/research/2026-09-19-finetune-decision/env.json`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent


def venv_site_packages() -> Path:
    candidates = sorted(
        (REPOSITORY_ROOT / ".venv" / "lib").glob("python3.*/site-packages")
    )
    if not candidates:
        raise SystemExit(f"no dev venv under {REPOSITORY_ROOT / '.venv'}")
    return candidates[-1]


sys.path.insert(0, str(venv_site_packages()))
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))
sys.path.insert(0, str(REPOSITORY_ROOT / "scripts"))

import finetune_decision_thresholds as registered

OUTPUT_JSON = (
    REPOSITORY_ROOT / "docs" / "research" / "2026-09-19-finetune-decision" / "env.json"
)
BLENDER_BINARY = "/Applications/Blender.app/Contents/MacOS/Blender"
GPU_HOST = "big"
# The repository's git binary on this machine needs the Command Line
# Tools developer dir: /usr/bin/git is a shim that refuses until the
# Xcode licence is accepted, and accepting it needs sudo.
GIT_DEVELOPER_DIR = "/Library/Developer/CommandLineTools"
COMMAND_TIMEOUT_SECONDS = 60


def shell(command: list[str], **kwargs) -> dict:
    """Run a command and record what it said, success or not."""
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT_SECONDS,
            check=False,
            **kwargs,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return {"command": " ".join(command), "ok": False, "error": str(error)}
    return {
        "command": " ".join(command),
        "ok": completed.returncode == 0,
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip()[:4000],
        "stderr": completed.stderr.strip()[:1000],
    }


def parse_arguments(argv):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--bench-root", required=True)
    parser.add_argument("--results-root", default="results/text_to_3D_agent")
    return parser.parse_args(argv)


def harness_identity() -> dict:
    from blended.agent.prompt_versions import get_revision
    from blended.agent.system_prompt import assembled_prompt_fingerprint
    from blended.agent.tools import (
        OP_FUNCTIONS,
        SERVICE_TOOL_NAMES,
        TOOL_SCHEMAS,
        TOOL_SCHEMAS_FINGERPRINT,
    )
    from blended.version import TARGET_BLENDER_SERIES

    revision = get_revision(None)
    return {
        "target_blender_series": TARGET_BLENDER_SERIES,
        "prompt_revision": revision.revision,
        "prompt_revision_identity": revision.identity,
        "assembled_prompt_fingerprint": assembled_prompt_fingerprint(),
        "tool_schemas_fingerprint": TOOL_SCHEMAS_FINGERPRINT,
        "op_count": len(OP_FUNCTIONS),
        "service_tool_count": len(SERVICE_TOOL_NAMES),
        "tool_schema_count": len(TOOL_SCHEMAS),
    }


def prompt_sizes(bench_root: Path) -> dict:
    """What each arm's prompt actually costs, in characters.

    Both formats are measured here so the report's prompt-parity section
    quotes a measurement rather than an estimate.
    """
    import json as json_module

    from blended.agent.system_prompt import build_system_prompt
    from blended.agent.tools import TOOL_SCHEMAS
    from blended.evaluate.bench_task_prompt import (
        RAW_TASK_TEMPLATE,
        SINGLE_SHOT_OPS_TASK_TEMPLATE,
    )
    from blended.evaluate.raw_bpy_arm import raw_system_prompt

    ops_system = build_system_prompt()
    schemas = json_module.dumps(TOOL_SCHEMAS)
    try:
        raw_system = raw_system_prompt(bench_root)
    except OSError as error:
        return {"error": str(error)}
    return {
        "ops_system_prompt_chars": len(ops_system),
        "ops_system_prompt_sha256": hashlib.sha256(ops_system.encode()).hexdigest(),
        "tool_schemas_json_chars": len(schemas),
        "ops_task_template_chars": len(SINGLE_SHOT_OPS_TASK_TEMPLATE),
        "raw_system_prompt_chars": len(raw_system),
        "raw_system_prompt_sha256": hashlib.sha256(raw_system.encode()).hexdigest(),
        "raw_task_template_chars": len(RAW_TASK_TEMPLATE),
    }


def bench_facts(bench_root: Path, results_root: str) -> dict:
    """The benchmark side of §2: is it runnable, and how many tasks."""
    instances_path = REPOSITORY_ROOT / registered.INSTANCES_FILE
    instances = [
        line.strip() for line in instances_path.read_text().splitlines() if line.strip()
    ]
    digest = hashlib.sha256(instances_path.read_bytes()).hexdigest()
    archived = bench_root / results_root
    render_logs = list(archived.glob("*/*/renders/render_log.json"))
    return {
        "bench_root": str(bench_root),
        "results_root": results_root,
        "instances_file": registered.INSTANCES_FILE,
        "instances": instances,
        "instances_sha256": digest,
        "instances_sha256_matches_registered": digest == registered.INSTANCES_SHA256,
        "bench_venv_python": str(bench_root / ".venv" / "bin" / "python"),
        "bench_venv_present": (bench_root / ".venv" / "bin" / "python").exists(),
        "archived_render_logs": len(render_logs),
        "scorer_scripts": sorted(
            path.name for path in (bench_root / "metrics").glob("*.py")
        ),
    }


def gpu_facts() -> dict:
    query = shell(
        [
            "ssh",
            GPU_HOST,
            (
                "nvidia-smi --query-gpu=name,driver_version,memory.total,"
                "memory.used --format=csv,noheader"
            ),
        ]
    )
    return {
        "host": GPU_HOST,
        "nvidia_smi": query,
        "cuda": shell(["ssh", GPU_HOST, "nvcc --version"]),
        "disk_home": shell(["ssh", GPU_HOST, "df -h /home"]),
        "tenancy": shell(["ssh", GPU_HOST, "gpu-tenant status"]),
        "served_models": shell(
            ["ssh", GPU_HOST, "curl -s http://127.0.0.1:8081/v1/models"]
        ),
        "weights": shell(
            [
                "ssh",
                GPU_HOST,
                (
                    'stat -c "%s %n" ~/models/blenderllm/*.gguf '
                    "~/models/qwen2.5-coder-7b-instruct/*.gguf"
                ),
            ]
        ),
    }


def local_serving_facts() -> dict:
    """Where the local arms were ACTUALLY served from.

    Not big's llama-swap, in the end: that card stayed committed to a
    live home-still conversion run, so A2/A3/A4 ran against a
    llama-server on this machine (Apple Silicon, Metal) reading the same
    GGUFs. Recorded here because "which machine generated the tokens" is
    part of every latency number in the report.
    """
    from blended.agent.loop import LOCAL_LLAMA_SERVER_ENDPOINT

    binary = Path.home() / ".local" / "llama.cpp-macos" / "llama-server"
    weights = sorted(
        (Path.home() / "mnt" / "codex_fs" / "models").glob("*/*.gguf")
    ) + sorted((Path.home() / "models").glob("*.gguf"))
    return {
        "endpoint": LOCAL_LLAMA_SERVER_ENDPOINT,
        "binary": str(binary),
        "binary_version": shell([str(binary), "--version"]),
        "props": shell(
            ["curl", "-s", "--max-time", "10", f"{LOCAL_LLAMA_SERVER_ENDPOINT}/props"]
        ),
        "precision": registered.SERVED_PRECISION,
        "context_tokens_total": 65_536,
        "slots": 4,
        "context_tokens_per_slot": registered.SERVED_CONTEXT_TOKENS,
        "weights_present": [
            {"path": str(path), "bytes": path.stat().st_size} for path in weights
        ],
        "host": shell(["sysctl", "-n", "machdep.cpu.brand_string"]),
        "memory_bytes": shell(["sysctl", "-n", "hw.memsize"]),
    }


def transcript_facts() -> dict:
    from blended.agent.tool_event import TOOL_EVENT_SCHEMA_VERSION

    iterations = REPOSITORY_ROOT / "_evaluate" / "iterations.jsonl"
    records = (
        [line for line in iterations.read_text().splitlines() if line.strip()]
        if iterations.exists()
        else []
    )
    with_events = 0
    for line in records:
        try:
            if json.loads(line).get("tool_events"):
                with_events += 1
        except json.JSONDecodeError:
            continue
    transcripts = sorted((REPOSITORY_ROOT / "logs").glob("chat-*.jsonl"))
    return {
        "tool_event_schema_version": TOOL_EVENT_SCHEMA_VERSION,
        "iterations_log": str(iterations),
        "iteration_records": len(records),
        "iteration_records_with_tool_events": with_events,
        "chat_transcript_directory": str(REPOSITORY_ROOT / "logs"),
        "chat_transcripts": len(transcripts),
    }


def registered_constants() -> dict:
    return {
        name: getattr(registered, name)
        for name in sorted(dir(registered))
        if name.isupper() and not name.startswith("_")
    }


def main(argv) -> int:
    arguments = parse_arguments(argv)
    bench_root = Path(arguments.bench_root).resolve()
    git_environment = {**os.environ, "DEVELOPER_DIR": GIT_DEVELOPER_DIR}
    document = {
        "experiment": "2026-09-19-finetune-decision",
        "spec": "docs/research/2026-09-19-finetune-decision-experiment.md",
        "repository": {
            "root": str(REPOSITORY_ROOT),
            "head": shell(
                ["git", "-C", str(REPOSITORY_ROOT), "rev-parse", "HEAD"],
                env=git_environment,
            ),
            "status_porcelain": shell(
                ["git", "-C", str(REPOSITORY_ROOT), "status", "--porcelain"],
                env=git_environment,
            ),
        },
        "blender": shell([BLENDER_BINARY, "--version"]),
        "harness": harness_identity(),
        "prompts": prompt_sizes(bench_root),
        "bench": bench_facts(bench_root, arguments.results_root),
        "gpu": gpu_facts(),
        "local_serving": local_serving_facts(),
        "transcripts": transcript_facts(),
        "arms": registered.ARMS,
        "hf_revisions": registered.HF_REVISIONS,
        "registered_constants": registered_constants(),
    }
    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON.write_text(json.dumps(document, indent=2, default=str) + "\n")
    print(f"[env] wrote {OUTPUT_JSON}", flush=True)
    print(
        f"[env] head={document['repository']['head'].get('stdout', '?')[:12]} "
        f"prompt={document['harness']['assembled_prompt_fingerprint']} "
        f"ops={document['harness']['op_count']} "
        f"schemas={document['harness']['tool_schema_count']}",
        flush=True,
    )
    print(
        f"[env] instances sha256 matches registered: "
        f"{document['bench']['instances_sha256_matches_registered']}",
        flush=True,
    )
    print(f"[env] gpu: {document['gpu']['nvidia_smi'].get('stdout', '?')}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
