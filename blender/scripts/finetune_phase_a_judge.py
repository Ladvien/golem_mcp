#!/usr/bin/env python3
"""G3 — does a non-passing but plausible asset miss an EXPLICIT constraint?

    .venv/bin/python scripts/finetune_phase_a_judge.py \\
        --bench-root /Users/ladvien/3dcodebench --sample 40

The one part of Phase A that needs the renders and the prompt rather
than a metric. G1 and G2 are separated by the shape-error decomposition
(ground truth against the reference mesh, reproducible); G3 — "executed,
plausible, misses an explicit instruction constraint" — cannot be read
off a distance, so the spec (§4) asks for a VLM judge plus a
hand-verified subset to estimate judge error.

`blended.evaluate.examiner` is deliberately NOT reused: it is
golden-reference-PAIRED with a closed deviation vocabulary, and there is
no pinned golden for a benchmark instance. This asks one question with a
two-field answer, and the eye is the licensed default eye.

The judge only RE-LABELS rows already inside `F_geom`, so no §3 rule
changes sign on its verdict — which is exactly why it is safe to run it
after the shares are known.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
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

from finetune_decision_thresholds import (
    GEOMETRY_CODES,
    JUDGE_HAND_VERIFIED,
    JUDGE_SAMPLE_SIZE,
)

PHASE_A_DIRECTORY = (
    REPOSITORY_ROOT / "docs" / "research" / "2026-09-19-finetune-decision" / "phaseA"
)
WORKING_DIRECTORY = REPOSITORY_ROOT / "outputs" / "finetune_decision"
TAXONOMY_CSV = PHASE_A_DIRECTORY / "taxonomy.csv"
JUDGE_JSONL = PHASE_A_DIRECTORY / "g3_judgements.jsonl"
VIEW_NAMES = ("Image_005.png", "Image_015.png", "Image_025.png", "Image_035.png")
# Stratification is over rolls, and the draw is seeded so the sample is
# the same sample on a re-run.
SAMPLE_SEED = 0

JUDGE_PROMPT = """\
You are judging one generated 3D asset against the text it was built from.

The four images are the SAME object from four camera angles of one turntable.

The text the builder was given:
---
{description}
---

Answer ONE question: does the object shown VIOLATE an EXPLICIT, checkable
constraint stated in that text? An explicit constraint is a stated count
("four legs", "three shelves"), a stated part that must be present ("with a
handle", "a lid"), a stated arrangement ("stacked", "hanging"), or a stated
material/shape word that a shape can contradict ("cylindrical", "square").

Rules:
- Proportions being somewhat off is NOT a violation. Overall shape quality is
  NOT a violation. Only a stated, checkable constraint counts.
- If the text does not state a checkable constraint, answer false.
- If you cannot see well enough to tell, answer false.

Reply with ONE line of JSON and nothing else:
{{"violated": true or false, "constraint": "<the exact phrase from the text, or \\"\\">"}}
"""


def parse_arguments(argv):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--bench-root", required=True)
    parser.add_argument("--results-root", default="results/text_to_3D_agent")
    parser.add_argument("--sample", type=int, default=JUDGE_SAMPLE_SIZE)
    parser.add_argument("--eye", default="claude-code:sonnet")
    return parser.parse_args(argv)


def refuse_to_overwrite_hand_verification(path: Path) -> None:
    """A re-run rewrites `g3_judgements.jsonl` from scratch, and the rows'
    `hand_verified` / `hand_violated` / `agrees` fields are typed by a
    human, not produced here. Losing them loses the judge's measured error
    rate, so refuse rather than truncate the file."""
    if not path.exists():
        return
    verified = sum(
        1
        for line in path.read_text().splitlines()
        if line.strip() and json.loads(line).get("hand_verified") is True
    )
    if verified:
        raise SystemExit(
            f"{path} holds {verified} hand-verified row(s); a re-run would "
            f"truncate them. Move the file aside first if that is intended."
        )


def geometry_rows() -> list[dict]:
    with TAXONOMY_CSV.open() as handle:
        return [
            row
            for row in csv.DictReader(handle)
            if row["code"] in GEOMETRY_CODES and row["third_party"] == "False"
        ]


def stratified(rows: list[dict], wanted: int) -> list[dict]:
    """Up to `wanted` rows, spread across rolls round-robin."""
    by_roll: dict[str, list[dict]] = {}
    for row in rows:
        by_roll.setdefault(row["model_dir"], []).append(row)
    generator = random.Random(SAMPLE_SEED)
    for roll_rows in by_roll.values():
        generator.shuffle(roll_rows)
    chosen: list[dict] = []
    while len(chosen) < wanted:
        added = False
        for roll in sorted(by_roll):
            if by_roll[roll]:
                chosen.append(by_roll[roll].pop())
                added = True
                if len(chosen) == wanted:
                    break
        if not added:
            break
    return chosen


def parse_verdict(text: str) -> dict:
    """The judge's two fields, or a recorded parse failure."""
    candidate = text.strip()
    start, end = candidate.find("{"), candidate.rfind("}")
    if start >= 0 and end > start:
        candidate = candidate[start : end + 1]
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError:
        return {"violated": None, "constraint": "", "parse_ok": False}
    violated = payload.get("violated")
    if not isinstance(violated, bool):
        return {"violated": None, "constraint": "", "parse_ok": False}
    return {
        "violated": violated,
        "constraint": str(payload.get("constraint", ""))[:300],
        "parse_ok": True,
    }


def main(argv) -> int:
    arguments = parse_arguments(argv)
    bench_root = Path(arguments.bench_root).resolve()
    results_root = bench_root / arguments.results_root
    if not TAXONOMY_CSV.exists():
        raise SystemExit(f"run scripts/finetune_phase_a.py first: no {TAXONOMY_CSV}")
    refuse_to_overwrite_hand_verification(JUDGE_JSONL)

    from blended.agent.loop import ModelConfig, OllamaClient, VisionDescriber

    rows = stratified(geometry_rows(), arguments.sample)
    print(f"[judge] {len(rows)} row(s) sampled for G3", flush=True)
    client = OllamaClient(
        ModelConfig.from_environment(model=arguments.eye, vision_model=arguments.eye)
    )
    status = client.check_connection()
    print(f"[judge] {status.summary()}", flush=True)
    if not status.ok:
        raise SystemExit(f"eye unreachable: {status.detail}")
    describer = VisionDescriber(client=client, vision_model=arguments.eye)

    JUDGE_JSONL.parent.mkdir(parents=True, exist_ok=True)
    judged = []
    with JUDGE_JSONL.open("w") as handle:
        for position, row in enumerate(rows, start=1):
            instance = row["instance"]
            renders = results_root / row["model_dir"] / instance / "renders"
            views = [renders / name for name in VIEW_NAMES]
            missing = [str(view) for view in views if not view.exists()]
            description = (
                (bench_root / "data" / instance / "prompt_description.txt")
                .read_text()
                .strip()
            )
            record = {
                "model_dir": row["model_dir"],
                "instance": instance,
                "code_before": row["code"],
                "cd_pca": row["cd_pca"],
                "views": [str(view) for view in views],
                "missing_views": missing,
            }
            if missing:
                record.update({"violated": None, "constraint": "", "parse_ok": False})
                print(
                    f"[judge] [{position}/{len(rows)}] {instance}: no renders",
                    flush=True,
                )
            else:
                reply = describer.describe(
                    views, prompt=JUDGE_PROMPT.format(description=description)
                )
                record["raw_reply"] = reply[:1000]
                record.update(parse_verdict(reply))
                print(
                    f"[judge] [{position}/{len(rows)}] {row['model_dir']}/{instance} "
                    f"violated={record['violated']} "
                    f"constraint={record['constraint'][:60]!r}",
                    flush=True,
                )
            handle.write(json.dumps(record) + "\n")
            judged.append(record)

    violations = [record for record in judged if record.get("violated") is True]
    unparsed = [record for record in judged if not record.get("parse_ok")]
    measured = {
        "eye": arguments.eye,
        "sampled": len(judged),
        "hand_verify_target": JUDGE_HAND_VERIFIED,
        "violated": len(violations),
        "unparsed": len(unparsed),
        "g3_share_of_sample": (len(violations) / len(judged)) if judged else None,
    }
    (WORKING_DIRECTORY / "phase_a_judge.json").write_text(
        json.dumps(measured, indent=2) + "\n"
    )
    print(
        f"[judge] {len(violations)}/{len(judged)} judged G3 "
        f"({len(unparsed)} unparsed); wrote {JUDGE_JSONL}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
