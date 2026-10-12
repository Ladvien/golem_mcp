"""One SINGLE-SHOT completion for one arm of the fine-tune decision experiment.

    # op-format arms (a1, a2): inside Blender, because the tool calls dispatch
    blender --background --factory-startup \\
        --python scripts/run_finetune_arm.py -- \\
        --arm a2 --format ops --model qwen2.5-7b-instruct --draw 1 \\
        --instance Jar_seed0 --bench-root /Users/ladvien/3dcodebench

    # raw-bpy arms (a3, a4, a5): the host venv, no bpy needed
    .venv/bin/python scripts/run_finetune_arm.py \\
        --arm a4 --format raw --model blenderllm --draw 0 \\
        --instance Jar_seed0 --bench-root /Users/ladvien/3dcodebench

SINGLE-SHOT is the measurement, not a simplification (spec §5.2): the
specialist under consideration would be CALLED AS A TOOL by a planning
agent, so exactly one prompt, exactly one `client.chat`, no tool results
returned to the model, no retry beyond the client's own bounded
transport retry, no render, no eye. Running one arm agentically against
another arm single-shot is the largest confound available here, and it
is measured separately or not at all.

Two output formats reach the SAME scored artifact, `<model-dir>/<inst>/<inst>.py`:

* `ops`   — the reply's `tool_calls` are dispatched in order and the
            recorded sequence is lowered by
            `bench_bridge.standalone_script` with the harness prelude and
            the canonical-orientation epilogue, exactly as
            `scripts/run_3dcode_instance.py` does for a production roll.
* `raw`   — the reply's Python is written verbatim, with NO prelude and
            NO epilogue: a raw script has to stand alone, and the
            epilogue imports `blended`. `cd_yawmin` is therefore never
            compared across formats; `cd_pca` quotients orientation out
            and is what the arms are compared on.

The plan gate is deliberately absent: it lives in `AgentSession`, not in
`dispatch_tool`, and a single-shot response has no second turn in which
to satisfy it. A `declare_plan` call, if the model emits one, dispatches
harmlessly and emits no geometry.

Writes one JSON line per completion to
`docs/research/2026-09-19-finetune-decision/phaseB/<arm>/completions.jsonl`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
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
sys.path.insert(0, str(REPOSITORY_ROOT))
sys.path.insert(0, str(REPOSITORY_ROOT / "scripts"))
os.chdir(REPOSITORY_ROOT)

# After the path bootstrap above, so the pre-registration module imports.
from finetune_decision_thresholds import (
    ARMS,
    draw_sampling,
    model_directory,
)

COMPLETIONS_ROOT = (
    REPOSITORY_ROOT / "docs" / "research" / "2026-09-19-finetune-decision" / "phaseB"
)
PROMPT_FILENAME = "prompt_description.txt"
# The parse results this runner can report. One vocabulary, so Phase B's
# funnel and Phase A's classifier read the same words.
PARSE_OK = "OK"
PARSE_NO_CODE = "NO_CODE"
PARSE_SYNTAX_ERROR = "SYNTAX_ERROR"
PARSE_NO_TOOL_CALLS = "NO_TOOL_CALLS"
PARSE_UNKNOWN_TOOL = "UNKNOWN_TOOL"
PARSE_ARGUMENT_ERROR = "ARGUMENT_ERROR"
PARSE_ERR_CONNECTION = "ERR_CONNECTION"
PARSE_ERR_MODEL_CALL = "ERR_MODEL_CALL"


def parse_arguments(argv):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--arm", required=True, choices=sorted(ARMS))
    parser.add_argument("--format", required=True, choices=("ops", "raw"))
    parser.add_argument("--model", default="")
    parser.add_argument("--draw", type=int, required=True)
    parser.add_argument("--instance", required=True)
    parser.add_argument("--bench-root", required=True)
    parser.add_argument("--results-root", default="results/text_to_3D_agent")
    parser.add_argument(
        "--completions-out",
        default="",
        help="override the completions.jsonl path (default: phaseB/<arm>/completions.jsonl)",
    )
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args(argv)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_completion(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        handle.write(json.dumps(record) + "\n")


def main(argv) -> int:
    arguments = parse_arguments(argv)
    if ARMS[arguments.arm]["format"] != arguments.format:
        raise SystemExit(
            f"arm {arguments.arm} is pre-registered as "
            f"{ARMS[arguments.arm]['format']!r}, not {arguments.format!r}"
        )
    temperature, seed = draw_sampling(arguments.draw)
    model = arguments.model or ARMS[arguments.arm]["model"]
    if model != ARMS[arguments.arm]["model"]:
        raise SystemExit(
            f"arm {arguments.arm} is pre-registered on "
            f"{ARMS[arguments.arm]['model']!r}, not {model!r}"
        )

    from blended.agent.loop import ModelConfig, OllamaClient
    from blended.agent.system_prompt import assembled_prompt_fingerprint
    from blended.agent.tools import TOOL_SCHEMAS, TOOL_SCHEMAS_FINGERPRINT

    bench_root = Path(arguments.bench_root).resolve()
    prompt_path = bench_root / "data" / arguments.instance / PROMPT_FILENAME
    if not prompt_path.exists():
        raise SystemExit(f"no {prompt_path}")
    description = prompt_path.read_text().strip()

    model_dir = model_directory(arguments.arm, arguments.draw)
    work_directory = (
        bench_root / arguments.results_root / model_dir / arguments.instance
    )
    script_path = work_directory / f"{arguments.instance}.py"
    if script_path.exists() and not arguments.overwrite:
        print(f"[SKIP] {model_dir}/{arguments.instance}", flush=True)
        return 0
    work_directory.mkdir(parents=True, exist_ok=True)

    completions_path = (
        Path(arguments.completions_out)
        if arguments.completions_out
        else COMPLETIONS_ROOT / arguments.arm / "completions.jsonl"
    )

    if arguments.format == "ops":
        from blended.agent.system_prompt import build_system_prompt
        from blended.evaluate.bench_task_prompt import (
            SINGLE_SHOT_OPS_TASK_TEMPLATE,
        )

        system_text = build_system_prompt()
        user_text = SINGLE_SHOT_OPS_TASK_TEMPLATE.format(description=description)
        offered = TOOL_SCHEMAS
    else:
        from blended.evaluate.raw_bpy_arm import raw_system_prompt, raw_task_text

        system_text = raw_system_prompt(bench_root)
        user_text = raw_task_text(description)
        offered = None

    record = {
        "arm": arguments.arm,
        "format": arguments.format,
        "model": model,
        "draw": arguments.draw,
        "seed": seed,
        "temperature": temperature,
        "instance": arguments.instance,
        "system_prompt_sha256": sha256_text(system_text),
        "user_prompt_sha256": sha256_text(user_text),
        "raw_output": "",
        "wall_time_s": 0.0,
        "finish_reason": "",
        "parse_result": "",
        "n_tool_calls": 0,
        "n_tool_calls_dispatched": 0,
        "n_ops": 0,
        "n_hatch": 0,
        "hatch_reasons": [],
        "script_chars": 0,
        "script_written": False,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "assembled_prompt_fingerprint": assembled_prompt_fingerprint(),
        "tool_schemas_fingerprint": TOOL_SCHEMAS_FINGERPRINT,
    }

    # A lane that cannot honour the pinned seed says so per completion
    # rather than letting the record imply a control it does not have.
    configuration = ModelConfig.from_environment(
        model=model, vision_model="", temperature=temperature, seed=seed
    )
    client = OllamaClient(configuration)
    if configuration.uses_claude_code:
        record["seed"] = None
        record["temperature"] = None

    status = client.check_connection()
    print(f"[connection] {status.summary()}", flush=True)
    if not status.ok:
        record["parse_result"] = PARSE_ERR_CONNECTION
        record["raw_output"] = status.detail[:2000]
        write_completion(completions_path, record)
        print(f"[ERR_CONNECTION] {arguments.instance}: {status.detail}", flush=True)
        return 1

    messages = [
        {"role": "system", "content": system_text},
        {"role": "user", "content": user_text},
    ]
    spent_before = client.spent
    started = time.monotonic()
    try:
        assistant = client.chat(messages, offered)
    except RuntimeError as model_error:
        record["wall_time_s"] = round(time.monotonic() - started, 2)
        record["parse_result"] = PARSE_ERR_MODEL_CALL
        record["raw_output"] = str(model_error)[:2000]
        write_completion(completions_path, record)
        print(f"[ERR_MODEL_CALL] {arguments.instance}: {model_error}", flush=True)
        return 1
    record["wall_time_s"] = round(time.monotonic() - started, 2)
    # TurnCost's own names: prompt side is `input_tokens` (plus whatever
    # a caching lane read), completion side is `output_tokens`.
    record["prompt_tokens"] = client.spent.input_tokens - spent_before.input_tokens
    record["completion_tokens"] = (
        client.spent.output_tokens - spent_before.output_tokens
    )
    record["finish_reason"] = assistant.get("finish_reason", "")

    if arguments.format == "raw":
        code = _finish_raw(assistant, record, script_path)
    else:
        code = _finish_ops(assistant, record, script_path, work_directory)
    write_completion(completions_path, record)
    print(
        f"[{record['parse_result']}] {model_dir}/{arguments.instance} "
        f"chars={record['script_chars']} {record['wall_time_s']}s",
        flush=True,
    )
    return code


def _finish_raw(assistant: dict, record: dict, script_path: Path) -> int:
    """Write the reply's Python verbatim, or record which stage failed."""
    from blended.evaluate.raw_bpy_arm import extract_python, parses

    reply = assistant.get("content", "") or ""
    record["raw_output"] = reply
    source = extract_python(reply)
    if source is None:
        record["parse_result"] = PARSE_NO_CODE
        return 0
    ok, detail = parses(source)
    record["script_chars"] = len(source)
    if not ok:
        record["parse_result"] = PARSE_SYNTAX_ERROR
        print(f"[SYNTAX_ERROR] {detail}", flush=True)
        return 0
    # No prelude and no epilogue: a raw script must stand alone.
    script_path.write_text(source if source.endswith("\n") else source + "\n")
    record["script_written"] = True
    record["parse_result"] = PARSE_OK
    return 0


def _finish_ops(
    assistant: dict, record: dict, script_path: Path, work_directory: Path
) -> int:
    """Dispatch the reply's tool calls here, then lower them to a script."""
    import bpy

    from blended.agent.loop import dispatch_here
    from blended.evaluate.bench_bridge import (
        HATCH_TOOL_NAME,
        RecordedCall,
        canonical_orientation_epilogue,
        emits_geometry,
        prelude,
        standalone_script,
    )

    record["raw_output"] = json.dumps(
        {
            "content": assistant.get("content", ""),
            "tool_calls": assistant.get("tool_calls") or [],
        }
    )
    tool_calls = assistant.get("tool_calls") or []
    record["n_tool_calls"] = len(tool_calls)
    if not tool_calls:
        record["parse_result"] = PARSE_NO_TOOL_CALLS
        return 0

    # A fresh, empty scene: the benchmark re-bakes from empty, so the
    # completion must not be able to lean on a default cube.
    bpy.ops.wm.read_factory_settings(use_empty=True)

    def scene_signature():
        return tuple(
            sorted(
                (
                    obj.name,
                    len(obj.data.vertices)
                    if getattr(obj.data, "vertices", None) is not None
                    else -1,
                )
                for obj in bpy.data.objects
            )
        )

    recorded: list[RecordedCall] = []
    failures: list[str] = []
    # A call that would have emitted geometry, and whether any survived.
    # Measured 2026-09-19 on Plate_seed0: the reply carried 9 tool calls
    # including a real `add_lathe`, the op REFUSED its arguments at the
    # execute stage ("Profile radii must be positive; poles are added
    # automatically" — the model sent radius-0 points), and nothing
    # reached the script. That is the spec's `O1`, a malformed-argument
    # failure, and calling it "no tool calls" would hide a whole class.
    geometry_calls_attempted = 0
    output_directory = work_directory / "_agent"
    for tool_call in tool_calls:
        function_block = tool_call.get("function", {})
        tool_name = function_block.get("name", "")
        raw_arguments = function_block.get("arguments", {})
        try:
            call_arguments = (
                json.loads(raw_arguments)
                if isinstance(raw_arguments, str)
                else raw_arguments
            )
        except json.JSONDecodeError as error:
            failures.append(PARSE_ARGUMENT_ERROR)
            print(f"[ARGUMENT_ERROR] {tool_name}: {error}", flush=True)
            continue
        if not isinstance(call_arguments, dict):
            failures.append(PARSE_ARGUMENT_ERROR)
            print(
                f"[ARGUMENT_ERROR] {tool_name}: arguments are not an object", flush=True
            )
            continue
        before = scene_signature()
        # One line per call BEFORE it runs: a completion killed by the
        # sweep's wall clock otherwise says nothing about where it went,
        # and measured 2026-09-19 the op arm's long completions hang in
        # DISPATCH (median finished completion: 70 s, 200 output tokens),
        # not in generation.
        print(f"[dispatch] {tool_name}", flush=True)
        outcome = dispatch_here(tool_name, call_arguments, output_directory)
        record["n_tool_calls_dispatched"] += 1
        if emits_geometry(tool_name):
            geometry_calls_attempted += 1
        if not outcome.ok and outcome.text.startswith("Unknown tool:"):
            failures.append(PARSE_UNKNOWN_TOOL)
        elif not outcome.ok and emits_geometry(tool_name):
            # Either `op_call.ArgumentError` at bind time (stage_reached
            # empty) or the op's own contract refusing the values.
            failures.append(PARSE_ARGUMENT_ERROR)
        if tool_name == HATCH_TOOL_NAME:
            record["n_hatch"] += 1
            reason = call_arguments.get("reason", "")
            if isinstance(reason, str) and reason.strip():
                record["hatch_reasons"].append(reason.strip()[:300])
        recorded.append(
            RecordedCall(
                tool_name=tool_name,
                arguments=(
                    outcome.validated_arguments
                    if outcome.validated_arguments is not None
                    else call_arguments
                ),
                stage_reached=outcome.stage_reached,
                changed_scene=scene_signature() != before,
            )
        )

    script = standalone_script(
        recorded,
        prelude(str(venv_site_packages()), str(REPOSITORY_ROOT / "src")),
        canonical_orientation_epilogue(),
    )
    # `op_call_count` counts every facade op the script replays, READER ops
    # included, and `n_hatch` above counts chunks DISPATCHED, collected or
    # not. Neither is "what the score saw": Phase B counts that off the
    # baked script's labels (`finetune_phase_a.baked_call_counts`).
    record["n_ops"] = script.op_call_count
    record["script_chars"] = len(script.text)
    if script.included_count:
        script_path.write_text(script.text)
        record["script_written"] = True
        record["parse_result"] = PARSE_OK
        return 0
    # Nothing that emits geometry survived.
    if PARSE_UNKNOWN_TOOL in failures:
        record["parse_result"] = PARSE_UNKNOWN_TOOL
    elif geometry_calls_attempted:
        record["parse_result"] = PARSE_ARGUMENT_ERROR
    else:
        # Every call was a service tool — a plan, an inspection, a
        # render request. Schema-conforming, and it built nothing.
        record["parse_result"] = PARSE_NO_TOOL_CALLS
    return 0


extra_arguments = (
    sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else sys.argv[1:]
)
raise SystemExit(main(extra_arguments))
