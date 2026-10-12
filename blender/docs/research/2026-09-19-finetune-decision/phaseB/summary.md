# Phase B — the five arms, single-shot

## The rule that fired

**Rule 1 fires: F_geom = 98.2% >= 60% -> DO NOT FINE-TUNE. The failures are planning failures; invest in decomposition, reference-image grounding and the multi-angle visual inspection loop instead.**

- Rules 4 and 5 are VOID rather than un-fired-on-the-evidence: Δ_facade and Δ_size are both computed against A2, which passed nothing, so each subtraction measures a floored arm instead of the facade or model size. Neither rule's §3 threshold comparison changes; only what the number is allowed to mean does.
- Δ_tune = 96.2 pp clears rule 2's 15.0 pp bar, and rule 2 STILL CANNOT FIRE, because it is conjoined with F_syntax >= 40% and F_syntax measured 1.8%. The careful statement, not the flattering one: domain SFT fixes the class a 7B fails in, and the archive does not fail in that class BECAUSE IT PAYS A RETRY LOOP TO AVOID IT. The Phase A denominator is multi-turn with error feedback; single-shot A5 — frontier model, raw bpy, no feedback — fails to execute 18.8% of the time against the archive's 1.8%. So the harness HAS a syntactic failure mode and spends tokens and turns instead of score on it. What the arm codes do show is the regime SFT buys: 100.0% of the untuned base's (A3) failures are syntactic (E1, E2, E3, E4, E5, E7, O1, O2), against 97.7% of the fine-tune's (A4) that are geometric (G1, G2, G3).

## Funnel, every completion of every arm

Rates are over all completions attempted for the arm, the spec's denominator being 80 (20 instances x 4 draws).

| arm | model | format | completions | schema | script emitted | executed | non-degenerate | cd_pca pass |
|---|---|---|---|---|---|---|---|---|
| a1 | claude-code:sonnet | ops | 80 | 97.5% | 87.5% | 80.0% | 80.0% | 42.5% |
| a2 | qwen2.5-coder-7b-instruct | ops | 80 | 73.8% | 1.2% | 0.0% | 0.0% | 0.0% |
| a3 | qwen2.5-coder-7b-instruct | raw | 80 | 78.8% | 78.8% | 2.5% | 2.5% | 2.5% |
| a4 | blenderllm | raw | 80 | 100.0% | 100.0% | 98.8% | 98.8% | 45.0% |
| a5 | claude-code:sonnet | raw | 80 | 100.0% | 100.0% | 81.2% | 81.2% | 48.8% |

| arm | pass@1 | pass@3 | greedy | cd_pca median | cd_pca IQR | F@0.05 median | wall p50 | wall p95 |
|---|---|---|---|---|---|---|---|---|
| a1 | 40.0% | 60.0% | 50.0% | 0.0215 | 0.0093-0.0503 | 0.3424 | 173.9s | 346.3s |
| a2 | 0.0% | 0.0% | 0.0% | — | — | — | 85.6s | 1500.0s |
| a3 | 1.7% | 5.0% | 5.0% | 0.0081 | — | 0.8270 | 136.2s | 1500.0s |
| a4 | 45.0% | 55.0% | 45.0% | 0.0304 | 0.0137-0.0884 | 0.2932 | 54.7s | 95.1s |
| a5 | 50.0% | 65.0% | 45.0% | 0.0206 | 0.0087-0.0350 | 0.3461 | 35.2s | 92.3s |

## Failure codes per arm

| arm | codes |
|---|---|
| a1 | {'PASS': 34, 'G2': 25, 'O1': 8, 'E7': 6, 'G1': 5, 'O2': 2} |
| a2 | {'O1': 58, 'E5': 11, 'O2': 10, 'E7': 1} |
| a3 | {'E7': 30, 'E3': 21, 'E5': 15, 'E2': 10, 'PASS': 2, 'E1': 2} |
| a4 | {'PASS': 36, 'G2': 33, 'G1': 10, 'E3': 1} |
| a5 | {'PASS': 39, 'G2': 21, 'E2': 11, 'G1': 5, 'E7': 2, 'E3': 2} |

## The four deltas

| quantity | definition | value | bar |
|---|---|---|---|
| Δ_tune | executability A4 − A3 | 96.2 pp | >= 15.0 pp |
| Δ_facade | executability A2 − A3 | -2.5 pp | >= 25.0 pp |
| Δ_size (k-mean) | cd_pca pass A1 − A2 | 40.0 pp | <= 10.0 pp |
| Δ_size (greedy) | cd_pca pass A1 − A2 | 50.0 pp | <= 10.0 pp |

- hatch rate, archived rolls (Phase A, passing attempts): 90.4%
- hatch rate, archived rolls (Phase A, failing attempts): 70.4%
- hatch rate, arm a1 single-shot: 8.9% (54 baked chunks against 550 baked scene-changing op calls)
- hatch rate, arm a2 single-shot: 0.0% (0 baked chunks against 6 baked scene-changing op calls)

## Cost

| arm | lane | money | GPU seconds | prompt tokens | completion tokens |
|---|---|---|---|---|---|
| a1 | Claude Code CLI | $0 | — | 194 | 1459683 |
| a2 | big llama-swap (q8_0) | $0 | 22545 | 32106 | 15627 |
| a3 | big llama-swap (q8_0) | $0 | 32391 | 20995 | 52105 |
| a4 | big llama-swap (q8_0) | $0 | 4466 | 20679 | 38809 |
| a5 | Claude Code CLI | $0 | — | 160 | 369857 |
