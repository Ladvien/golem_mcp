# Vetting Scraped Blender Agent Skills Against the Corpus — 2026-08-25

**For:** `blended` — deciding what, if anything, from ~20 publicly scraped
"Blender agent skills" belongs in this harness's prompt modules.
**Method:** home-still corpus first (`distill_search`, `markdown_read`,
`catalog_read`), three parallel vetting sweeps over 28 distinct claims.
Every verdict below carries the DOI or corpus stem it rests on, per the
`CLAUDE.md` re-lookup rule.
**Companion:** `2026-08-20-agentic-blender-game-asset-harness-research.md`
supplies the eight findings this document does not re-derive.

---

## 0. The finding that reframes the exercise

Before any individual skill is judged, one measured result governs how
many skills should exist at all.

**SkillsBench** (`10.48550/arXiv.2602.12670`) — 84 tasks, 11 domains, 7
agent-model configurations, **7,308 trajectories** — is the first
large-N controlled measurement of whether "agent skills" work:

| Condition | Effect on pass rate |
|---|---|
| Curated skills, overall | **+16.2 pp** (78.4% → 61.1% failure) |
| Software-engineering domain specifically | **+4.5 pp** (the weakest domain) |
| **2–3 focused modules loaded** | **+18.6 pp** |
| **4+ modules loaded** | **+5.9 pp** |
| Skill doc written to be "comprehensive" | **−2.9 pp** |
| Skill doc written compact / detailed | **+17.1 / +18.8 pp** |
| **Self-generated skills** | **−1.3 pp** |
| Worst individual task | **−39.3 pp** |

Four consequences for `blended`, all of them uncomfortable:

1. **Loading seven modules at once would forfeit most of the benefit.**
   2–3 focused modules measure at +18.6 pp; 4+ collapse to +5.9 pp. The
   seven modules must therefore be a **library with a selector**, not a
   block that ships whole. This is the same shape as SWE-agent's window
   ablation — full file 12.7% vs 100-line window 18.0%, −5.3 pp
   (`10.48550/arXiv.2405.15793`) — and as the "lost in the middle"
   result, where 20–30 documents drove accuracy *below* the closed-book
   baseline (`10.48550/arxiv.2307.03172`).
2. **Comprehensiveness is a measured negative.** A module that tries to
   cover its subsystem exhaustively scores −2.9 pp against +18.8 pp for
   one that is compact. The scraped skills are almost uniformly the
   former: `atp-asset-optimization` is 180 lines of undifferentiated
   bullets, `atp-texturing` and `atp-rigging` likewise.
3. **Skills an agent writes for itself are worth −1.3 pp.** Human
   curation is the active ingredient. These modules must be reviewed by
   you, not generated and merged.
4. **16 of 84 tasks got *worse* with skills.** A skill is a change with
   a sign, not a free addition. Each module needs the same
   before/after treatment `prompt_versions.py` already gives working-
   agreement revisions.

**Bottom line:** the request was seven discrete skills. The evidence
supports authoring seven and *loading two or three*. Section 5 proposes
the selector that makes that true.

---

## 1. Verdict by source skill

Twenty-one files, of which four pairs are byte-identical duplicates.
Origin prefixes are as supplied.

| Skill | Verdict | Why |
|---|---|---|
| `libevm-blender` | **HARVEST — the best of the set** | The only one written for an *agent* rather than transcribed from a manual. Its data-API-over-operators doctrine, mode/context preconditions, depsgraph-vs-original distinction and pre-return checklist are all sound. Mechanism documented in the Apress Blender text; the *ranking* is untested. |
| `dom-blender-scripting` | **HARVEST (partial)** | Correct, runnable `bpy` idioms and the `--background --python` invocation. Version-drift caveat on import/export operator names is exactly right and matches finding 1.3. |
| `dom-blender-3d-modeling` | **HARVEST (partial)** | `from_pydata` vs `bmesh` guidance and the "link to a collection or it will not appear" trap are real. Already superseded in-repo by `blended.ops`. |
| `dom-blender-render-automation` | **HARVEST (partial)** | `prefs.get_devices()` after setting `compute_device_type`, image-sequence-not-video for animation, denoising economics. Practical, correct, untested in the literature. |
| `dom-blender-animation` | **REFERENCE ONLY** | Competent, but animation is out of scope for the current lanes. |
| `dom-blender-compositing` | **REJECT (out of scope)** | Node-graph recipes with no bearing on the asset gates. |
| `csr-3d-modeling` / `maji-3d-modeling` | **STRIP PERSONA, HARVEST 3 CLAIMS** | The persona wrapper is contradicted evidence (§2.1). Three of its "strong opinions" survive as claims; two are false as stated. |
| `atp-modeling` | **HARVEST (thin)** | Correct vocabulary, no procedure. Duplicates the corpus book at lower fidelity. |
| `atp-blender` | **REJECT** | A keyboard-shortcut reference. An agent has no keyboard. Pure context cost. |
| `atp-asset-optimization` | **REJECT — contains unsourced numbers** | The per-platform budget tables appear in **no** corpus document (§2.4). Its LOD/hysteresis/dithering material is correct but is better taken from the primary source. |
| `atp-texturing` | **HARVEST (2 claims)** | Texel-density and seam-placement claims are sourced. The rest is glossary. |
| `atp-rigging` | **REFERENCE ONLY** | Out of scope for current lanes. |
| `atp-animation` | **REFERENCE ONLY** | As above. |
| `atp-unity` / `atp-omniverse` / `atp-vroid` | **REJECT (out of scope)** | No Unity, Omniverse or VRM lane in this harness. |
| `csr-blender` / `csr-creative-blender` | **REJECT** | Auto-generated stub. Contains the literal text "Quick reference patterns will be added as you use the skill." Zero content. |
| `csr-blender-integration` (×2) | **REJECT** | Four bullet points. No procedure. |
| `csr-blender-toolkit` (×4 copies) | **REJECT — architecturally incompatible** | 18 KB dominated by addon-installation troubleshooting for a WebSocket/JSON-RPC control scheme this harness does not use. Its Mixamo bone-mapping heuristics are unsourced and irrelevant to the current lanes. |
| `csr-testing-blender-3d` (×2) | **REFERENCE ONLY (one idea)** | The `orbit_render` multi-angle validation pattern matches `capture/views.py`. Everything else is BlenderMCP socket plumbing. |
| `alpha-3d-modeling` | **REJECT — contains a false instruction** | Tells the agent to `pip install bpy` "if using external editors" *and* to set a `$BLENDER_API_KEY` for "paid APIs" that do not exist. Also `bpy.ops.import_scene.obj`, removed in Blender 4.x. |
| `codebuddy-blenderproc-*` | **REFERENCE ONLY (different problem)** | Synthetic-data generation with exact projected ground truth. Well-engineered, but it renders *training data*, not game assets. Its honesty about physics-vs-grid placement is a good model. |

**Net: 2 skills worth harvesting substantially, 6 worth harvesting in
part, 13 to reject.** Nothing in the set is adoptable as-is.

---

## 2. Claim-level vetting

Verdict scale: **SUPPORTED** (measured), **PARTIALLY-SUPPORTED**,
**UNSUPPORTED-BUT-PLAUSIBLE** (craft consensus nothing tests),
**CONTRADICTED**, **NOT-IN-CORPUS** (no evidence either way).

### 2.1 The persona wrapper — CONTRADICTED

`csr-3d-modeling` and `maji-3d-modeling` open with ~40 lines of
biography: *"battle-hardened 3D artist... Years Experience: 12... Battle
Scars... Strong Opinions... Fight me."*

Zheng et al. tested exactly this pattern at scale: **162 personas × 6
models × 2,410 MMLU questions** against a no-persona control, fitted
with a mixed-effects model. **No persona was statistically better than
control**, several were significantly worse, and automatic best-persona
selection performed *no better than random*. Domain-aligned personas
helped by a coefficient of **0.004** — detectable, meaningless. Larger
models showed *more* negative personas (`10.18653/v1/2024.findings-emnlp.888`).

The counter-evidence is real but narrower and does not license this
pattern: Kong et al. report role-play beating zero-shot on 10 of 12
reasoning benchmarks with gpt-3.5-turbo (AQuA 53.5 → 63.8, Last Letter
23.8 → 84.2), but the winning prompt is a *minimal task-aligned* role
("you are an excellent math teacher"), and their own ablation attributes
the gain to it acting as an **implicit chain-of-thought trigger**, not
to encoded expertise (`10.48550/arxiv.2308.07702`). Reasoning-model
guidance since then notes CoT-trigger boilerplate can *degrade*
performance on models that already reason (`10.1145/3807901`), removing
the one mechanism that made it work.

The "strong opinions / contrarian views" block is worse than inert.
Persona assignment raises measured toxicity up to **6×**, with
negative-valence personas worst (`10.18653/v1/2023.findings-emnlp.88`);
system prompts that elicit a trait reliably induce it (final-token
projection correlates **r = 0.75–0.83** with subsequent expression,
`10.48550/arXiv.2507.21509`); and models displaying **higher**
agreeableness and conscientiousness score **better** on reasoning, with
low-agreeableness output described as projecting "hidden, selfish
motives" that bias interpretation (`10.48550/arXiv.2410.16491`). A
"Fight me" instruction sits on the wrong end of the axis that predicts
reasoning quality.

**Action:** take the claims, discard the character. Where a claim is
true, state it as a rule with its reason. `blended`'s working agreement
already does this and should not acquire a persona.

### 2.2 Topology doctrine — mostly craft, two absolutes false

| Claim | Verdict | Evidence |
|---|---|---|
| "N-gons are never acceptable in final production geometry" | **CONTRADICTED** | Vaughan, the source of the underlying craft rule, licenses the exception in the next sentence: use n-gons and triangles "in areas that won't deform or be in plain sight" (`book_digital_modeling_vaughan` ch. 6 pp. 176–178). PolyGen deliberately outputs n-gon meshes (`10.48550_arxiv.2002.10880`); production remeshers target **quad-dominant**, not pure-quad (`eth-cgl-various-Fru24a`). |
| "Quads are a requirement for anything that deforms" | **UNSUPPORTED-BUT-PLAUSIBLE** as stated; the weaker form is craft consensus | Vaughan asserts quads are "superior for meshes that will deform" and that n-gons cause pinching (same pages) — asserted, never measured. "Requirement" is too strong; "strongly preferred" is defensible. |
| "Triangles are fine for static hard surface if intentionally placed" | **SUPPORTED** | Vaughan p. 178; and engine-side, "a triangle is always planar. Any polygon with four or more vertices need not have this property" (`Game Engine Architecture 3rd`, §11.1.1.2). |
| "Subdivision *requires* quad-dominant topology" | **CONTRADICTED as a requirement, SUPPORTED as a quality claim** | Catmull-Clark is defined on arbitrary topological meshes — that is the title of the 1978 paper. The measured quality claim: subdividing skinny triangles "creates irregularly sized faces... visible as shading artifacts," which quad-dominant output avoids (`eth-cgl-various-Fru24a` §5.3). |
| "Place poles away from deformation areas" | **CONTRADICTED / in tension** | The corpus rule is *curvature*-based: irregular vertices belong "in regions with a strong negative or positive Gaussian curvature" (`10.1111_cgf.12014` §2.3.2). Animation-Aware Quadrangulation cuts directly against the scraped rule — its deformation-aware output carries **more** singularities, concentrated in the deforming region, and argues that is what makes it artist-like (`Animation-Aware-Quadrangulation`). |
| "Edge flow should follow anatomical/muscle structure" | **SUPPORTED — and measured** | "The dynamic shape features of living bodies are aligned to bundles of muscles and Langer's lines"; the method's output "reveals the underlying muscle structure inferred from motion, while static methods just fit a rather artificial straight grid" (`Animation-Aware-Quadrangulation`; corroborated `10.1111_cgf.12014` §2.2.1). |

**Action:** the harness has no deformation lane yet, so none of this is
load-bearing today. When the retopo lane lands, encode the *conditional*
forms, never the absolutes. An agent told "n-gons are never acceptable"
will burn calls cleaning geometry that was fine.

### 2.3 Mesh validity and repair

| Claim | Verdict | Evidence |
|---|---|---|
| Non-manifoldness / gaps / self-intersections characterise **designed** meshes; noise and holes characterise **digitized** ones | **SUPPORTED** | Attene et al. state the contrast verbatim (`10.1145_2431211.2431214` §4.1, Tables I–II). This is the correct grounding for the analyzer gate. |
| Zero-area triangles are characteristic of designed meshes | **PARTIALLY-SUPPORTED — misattributed** | In Attene's Table I degeneracies are *sporadic* for designed meshes and typical only for tessellation and implicit-contouring pipelines. Still worth gating on (they break normal, circumcenter and barycentric computation) — just do not cite Attene for the attribution. |
| "Disconnected components" is a designed-mesh defect class | **NOT-IN-CORPUS as stated** | Not a category in Attene's taxonomy. The nearest entry, "isolated & dangling elements" (§3.1.1–3.1.2), is described as trivially fixable. The harness's one-component check remains a legitimate *brief* requirement; it is not an Attene defect. |
| Automatic mesh repair can be trusted on generated geometry | **CONTRADICTED** | "Although a fully automatic repairing of mesh models is highly desirable, this goal is thus hard to achieve"; repair algorithms "may newly introduce other flaws"; the realistic remedy "is to incorporate a human observer" (`10.1145_2431211.2431214` §2.1, §6.2). Attene's own tool paper: "The algorithms discussed in this article are not guaranteed to terminate with success" (`10.1007_s00371-010-0416-3` §5.2). |

**Action:** this is the strongest-grounded material in the whole sweep
and it already matches the harness design — the analyzer is the gate,
and `ingest/cleanup.py` must report its thresholds rather than silently
fixing. Reinforce, do not change.

### 2.4 Game-ready numbers — the dangerous section

| Claim | Verdict | Evidence |
|---|---|---|
| Mobile 1K–10K tris/object, console 10K–50K, PC 50K–100K; draw calls <100 / <500 / <1000 | **NOT-IN-CORPUS** | Not one of these six numbers appears in any corpus document. Vaughan is asked this exact question and refuses to answer it: "how many polygons should be used is probably the most asked question. What's the answer? Well, it depends" (p. 172) — then gives a datum that already **exceeds the claim's console ceiling** (30,000+ polys for a console character, p. 320). Draw-call tiers are contradicted by measured mobile work rendering >80M triangles at 60 FPS with 89–190 draw calls after cluster culling (`s2024-advances-pdf-2-6-mb` pp. 3, 28, 31). Real-Time Rendering pre-emptively disowns tables of this kind: "please imagine the phrase 'your mileage may vary' stamped in large red letters over every page of this section" (`book_real_time_rendering_4th_akenine` p. 815). |
| VR targets 90+ FPS | **SUPPORTED** | "A display rate of 90 FPS is common among VR systems, which gives a frame time of 11.1 ms... A lag of more than 20 ms can definitely be perceived" (`book_real_time_rendering_4th_akenine` p. 941). |
| LOD chains via decimation; hysteresis and dithering to prevent popping | **SUPPORTED** | Hysteresis with worked example: switch L1→L2 at 110 m, back at 90 m (`book_level_of_detail_3d_graphics_luebke` p. 120); "This can be solved by introducing some hysteresis" (`book_real_time_rendering_4th_akenine` §19.9.1 p. 882); screen-door/dissolve transitions (ibid. pp. 877–879). |
| "Decimation preserves silhouette well enough for LOD" | **PARTIALLY-SUPPORTED — the subtlest hazard here** | QEM is structurally biased toward keeping sharp features, but on open boundaries the unmodified algorithm produces results the authors call "clearly unacceptable" — a 7,960-face cylinder "quickly degenerates" at 2,460 faces without an explicit boundary penalty (`10.1109/visual.1998.745312` §4, Fig. 3). Budget-based simplification "does not guarantee visual fidelity" (`book_level_of_detail_3d_graphics_luebke` p. 46), and baked normals cannot rescue a lost silhouette because they "will not change the surface's silhouette" (`10.1145/280814.280832`). Safe form: *decimation preserves silhouette on clean manifold input with boundary and attribute constraints enabled, verified per asset.* |
| Consistent texel density matters | **SUPPORTED** (the "mark of amateur work" rhetoric is not) | "it is important for objects to be texture mapped with a reasonably consistent world-space texel density... Many game studios provide their art teams with guidelines and in-engine texel density visualization tools" (`Game Engine Architecture 3rd` §11.1.2.5). Note the corpus distinguishes **world-space** texel density (hold constant) from **screen-space** (necessarily varies with distance) — the scraped skills collapse the two. |
| Seams in hidden areas; minimize islands; pack efficiently | **SUPPORTED as craft, but one side of a measured trade-off** | Vaughan p. 182 states all three. The omitted caveat: fewer charts means more distortion — "there exists a trade-off between texture stretch and deviation" (`10.1145/383259.383307`); Autocuts frames good UV work as "balancing the number of seams and the distortion of the map" (`10.1145/3130800.3130845`). |
| High-poly → retopo → normal-map bake is the standard pipeline | **SUPPORTED** — best-grounded claim in the set | Documented independently as pipeline (`book_digital_modeling_vaughan` pp. 150–151, 321–327), as algorithm (`GPU Gems` ch. 35 pp. 607–615), and as theory (`10.1145/280814.280832`). |
| "ZBrush inverts normal maps — flip the green channel" | **PARTIALLY-SUPPORTED, and the prescribed fix is wrong** | The corpus says **flip vertically**: "ZBrush inverts all its maps, and other programs won't read them correctly unless you invert vertically" (`book_digital_modeling_vaughan` p. 339). A vertical image flip and a green-channel inversion are *different corrections for different defects*; applying one where the other is needed leaves the asset wrong. Green-channel prescription: **NOT-IN-CORPUS**. The source is also ~2011 ZBrush behaviour. |
| Unity export scale 1.0 / −Z forward; Unreal 0.01 / −X forward | **PARTIALLY-SUPPORTED — half of it contradicted** | Unreal's −X forward, Z up is corroborated (`Procedural Content Generation for Games`, Deolikar & Lupiani, pp. 459, 462, 478). The Unreal **0.01 scale is contradicted** by that same source, which sets unit scale to 1 and metres and scales by intended object size (pp. 455, 470). Unity's figures are **NOT-IN-CORPUS**. Also format-dependent: for glTF the same source finds **+Y up** correct (p. 476), so a single hardcoded axis rule is wrong across formats. |
| Neural generators need retopo/UV before game-ready | **SUPPORTED in direction, weak in source** | The one end-to-end measurement (Hunyuan 3D scene at 32.8M triangles vs 293K hand-authored, ~111×; decimation attempt "producing holes and damaging texture alignment") is `10.55677/ijhrsss/15-2026-vol03i06` — **which the 2026-08-20 brief assessed as likely predatory** (publishes within 12 hours of fee payment, not in DOAJ, severe scope mismatch). **Do not cite these numbers.** The claim's *direction* is independently supported by the face-count ceilings in §2.1 of that brief (MeshAnything avg 318 faces; EdgeRunner ~4,000). Treat the timings as anecdote. |

**Action:** never let a per-platform budget table into a prompt module.
Budgets are a project input, not a fact — `Parameters` already carries
`POLY_BUDGET` and that is the correct home. The green-channel and
Unreal-scale items are the two places a scraped skill would have put a
wrong operation into an asset.

### 2.5 API and interface doctrine

| Claim | Verdict | Evidence |
|---|---|---|
| Prefer `bpy.data`/`bmesh` over `bpy.ops` in generated code | **PARTIALLY-SUPPORTED** | The mechanism is documented — operators "act upon an existing selection" and "perform tasks based on the current context," needing `temp_override` (`Procedural Content Generation for Games`, ch. 2) — but the *ranking* is untested, and that source's own answer is context override, not avoidance, using "both `bpy.ops.mesh` and bmesh operators extensively." Nothing measures headless failure rates. The harness's `blended.ops` mandate is justified by drift-resistance and idempotence, which is a stronger argument than the one the scraped skill makes. |
| Purpose-built agent interfaces beat a raw shell | **SUPPORTED** | SWE-agent ACI 18.0% vs shell-only 11.0%, same model (`10.48550/arXiv.2405.15793`). Component deltas: no search −2.3, human-style iterative search **−6.0 (worse than no search)**, full-file viewer −5.3, full history −3.0. |
| ...but narrow predefined tools beat code execution | **CONTRADICTED** | Executable Python actions beat pre-defined JSON/text tool schemas by **up to 20 pp** with ~30% fewer actions on M³ToolEval (`10.48550/arxiv.2402.01030`). The `run_python` + curated-ops shape this harness already uses is the correct reading of both results. |
| Too much context degrades performance | **SUPPORTED** | U-shaped curve; mid-context accuracy in the 20–30 document setting falls **below the closed-book baseline** (`10.48550/arxiv.2307.03172`). Agentless found full file contents both costlier and *less* accurate than a compressed skeleton (`10.48550/arxiv.2407.01489`). |
| RAG over API docs cuts code-generation error | **SUPPORTED** | API-call accuracy **31.5% → 36.8%**, CoNaLa BLEU 27.20 → 30.69 (`10.18653/v1/2020.acl-main.538`); LL3M's BlenderRAG cut mesh-generation errors 3.29 → 2.43 avg, −26% (`10.48550/arXiv.2508.08228`). Caveat measured in the same table: API docs **without** retrieval-based re-sampling *hurt* (27.84 vs 28.14). |
| Closed tag vocabulary improves critic reliability | **SUPPORTED for the verdict, CONTRADICTED for the reasoning** | CheckEval raises inter-evaluator agreement to **α/κ = 0.67** across 12 evaluator LLMs, near human κ ≈ 0.7 (`10.48550/arXiv.2403.18771`). But hard format restriction degrades reasoning: under JSON mode **100% of GPT-3.5-Turbo responses put `answer` before `reason`**, collapsing CoT; LLaMA-3-8B showed a 0.148% parse-error rate yet a **38.15% performance gap** vs free text (`10.18653/v1/2024.emnlp-industry.91`). **`examiner.md.j2` already emits `reasoning` before `tags` — that ordering is validated, keep it.** |
| ~3 refinement rounds, then stop | **SUPPORTED, with a hard condition** | Self-Refine: most gain in iteration 1, non-monotonic thereafter (`10.48550/arxiv.2303.17651`). Without an external correctness signal accuracy **falls monotonically**: GPT-4 GSM8K 95.5 → 91.5 → 89.0; GPT-3.5 CommonSenseQA 75.8 → 38.1 (`10.48550/arXiv.2310.01798`). Iterate only behind a verifier — which is precisely what the analyzer gate is. |

---

## 3. What survives, and where it goes

Seven capability modules, each mapped to a real `src/blended` subsystem
and carrying only claims that survived §2. Written **compact, not
comprehensive** — SkillsBench measures that difference at +18.8 pp vs
−2.9 pp.

| Module | Subsystem | Load for | Survives from |
|---|---|---|---|
| `builder_authoring` | `builders/`, `ops/` | every build lane | `libevm-blender` (preconditions, explicit state), `dom-blender-3d-modeling` (link-or-it-does-not-exist) |
| `api_drift` | `drift/`, `version.py` | every lane | `dom-blender-scripting` (version-dependent operator names); finding 1.3/1.4 |
| `mesh_validity` | `analyze/` | every lane | Attene taxonomy; *nothing* from the scraped set, which had no defect vocabulary |
| `visual_critique` | `capture/`, `evaluate/examiner.py` | inspection turns | `csr-testing-blender-3d` (orbit render only) |
| `generated_mesh_ingest` | `ingest/` | the GLB lane only | `codebuddy-blenderproc` (honesty about placement), face-count ceilings |
| `game_ready_export` | `export/` | export turns only | `atp-texturing` (texel density, seams), Deolikar axis data |
| `iteration_and_memory` | `run/retry.py`, `evaluate/mistake_memory.py` | every lane | nothing scraped; Self-Refine + Huang et al. |

**Nothing from the persona skills, the toolkit skills, the engine
skills, or the stubs makes it in.** Thirteen of twenty-one files
contribute zero text.

### 3.1 The selector is the load-bearing part

Seven modules exist; **at most three load**. This is not a style
preference — it is the difference between +18.6 pp and +5.9 pp
(`10.48550/arXiv.2602.12670`), and it is the same shape as SWE-agent's
window ablations (`10.48550/arXiv.2405.15793`) and "lost in the middle"
(`10.48550/arxiv.2307.03172`).

Proposed rule, enforced by assertion rather than convention:

- `builder_authoring`, `api_drift`, `mesh_validity` are the **standing
  three** for a construction turn.
- Lane modules **displace** rather than add: an ingest turn swaps
  `generated_mesh_ingest` in for `builder_authoring`; an export turn
  swaps `game_ready_export` in for whichever standing module the turn
  does not exercise.
- `MAXIMUM_MODULES_LOADED = 3`, asserted in `validate_modules()`. A
  fourth module is a design error surfaced as a failing test, exactly
  as `MAXIMUM_CHANGED_HUNKS_PER_REVISION = 1` already works.

### 3.2 Each module is a change with a sign

16 of 84 SkillsBench tasks got **worse** with skills (worst −39.3 pp).
So modules carry the same provenance discipline the working agreement
already has: `hypothesis` stated before the convergence run, `outcome`
filled from measurement. A module whose measured effect is negative gets
removed, not tuned into the corner.

The one asymmetry worth stating: **self-generated skills measured
−1.3 pp**. These seven were drafted by an agent and are therefore
suspect by default. They are proposals for your review, and the
+16.2 pp result only applies to the curated arm.

---

## 4. Corrections this sweep produced for existing harness text

1. **`examiner.md.j2` is validated as written.** Closed tag vocabulary
   raises inter-evaluator agreement to α/κ ≈ 0.67, near human
   (`10.48550/arXiv.2403.18771`), and the template already emits
   `reasoning` before `tags`, which is the ordering that avoids the
   38.15% degradation measured under answer-first JSON constraint
   (`10.18653/v1/2024.emnlp-industry.91`). Do not reorder those keys.
2. **The one-component gate should not be attributed to Attene.**
   "Disconnected components" is not a category in that taxonomy. Keep
   the check — it is a legitimate brief requirement — but cite it as a
   brief conformance rule, not a mesh-repair defect.
3. **Zero-area triangles: keep the gate, fix the citation.** Attene
   marks degeneracies *sporadic* for designed meshes. The justification
   is downstream breakage (normals, circumcenters, barycentrics), not
   defect frequency.
4. **`ingest/cleanup.py` must report its threshold.** Gap-closing "can
   only guarantee gap-free output if all gaps in the input are narrower
   than some specified threshold," and high thresholds "result in
   arbitrarily implausible results" (`10.1145_2431211.2431214`). A
   cleanup that does not print what it assumed is a cleanup you cannot
   audit.
5. **Do not cite `10.55677/ijhrsss/15-2026-vol03i06` anywhere.** The
   2026-08-20 brief assessed it as likely predatory; this sweep
   surfaced it again as the only end-to-end measurement of neural-
   generator cleanup cost. The direction it reports is corroborated by
   the face-count ceilings; its numbers are not evidence.

---

## 5. Acquisition list from this sweep

Nothing in this sweep required a download — every claim resolved against
material already in the corpus. Two gaps are worth noting as absent
rather than unresolved:

- **No corpus source states Unity's import scale or forward axis.** If
  a Unity lane is ever added, this is an acquisition, not an inference.
- **No paper tests persona prompting on 3D/DCC or agentic modeling
  work.** The MMLU-scale null result (`10.18653/v1/2024.findings-emnlp.888`)
  is the closest available and is what §2.1 rests on.

---

## Sources

Corpus stems and DOIs cited above, for re-lookup via `distill_search` /
`catalog_read`:

`10.48550/arXiv.2602.12670` (SkillsBench) ·
`10.18653/v1/2024.findings-emnlp.888` (persona null result) ·
`10.48550/arxiv.2308.07702` (role-play prompting) ·
`10.18653/v1/2023.findings-emnlp.88` (persona toxicity) ·
`10.48550/arXiv.2507.21509` (persona vectors) ·
`10.48550/arXiv.2410.16491` (traits and reasoning) ·
`10.1145/3807901` (reasoning-model prompting) ·
`10.1145_2431211.2431214` (Attene mesh repair) ·
`10.1007_s00371-010-0416-3` (Attene repair tool) ·
`book_digital_modeling_vaughan` · `book_real_time_rendering_4th_akenine` ·
`book_level_of_detail_3d_graphics_luebke` ·
`Game Engine Architecture, Third Edition` (Gregory) ·
`10.1109/visual.1998.745312` (QEM) · `10.1145/280814.280832` (appearance-preserving simplification) ·
`10.1145/383259.383307` (texture stretch/deviation) · `10.1145/3130800.3130845` (Autocuts) ·
`10.1111_cgf.12014` (quad meshing survey) · `Animation-Aware-Quadrangulation` ·
`eth-cgl-various-Fru24a` (QUADify) · `10.48550_arxiv.2002.10880` (PolyGen) ·
`10.48550/arXiv.2405.15793` (SWE-agent) · `10.48550/arxiv.2402.01030` (executable actions) ·
`10.48550/arxiv.2307.03172` (lost in the middle) · `10.48550/arxiv.2407.01489` (Agentless) ·
`10.18653/v1/2020.acl-main.538` (API-doc retrieval) · `10.48550/arXiv.2508.08228` (LL3M) ·
`10.48550/arXiv.2403.18771` (CheckEval) · `10.18653/v1/2024.emnlp-industry.91` (format restriction) ·
`10.48550/arxiv.2303.17651` (Self-Refine) · `10.48550/arXiv.2310.01798` (self-correction without oracle) ·
`10.48550/arXiv.2305.16291` (Voyager) · `10.48550_arXiv.2606.01057` (3DCodeBench) ·
`s2024-advances-pdf-2-6-mb` · `Procedural Content Generation for Games` (Deolikar & Lupiani) ·
`GPU Gems` ch. 35 · `10.55677/ijhrsss/15-2026-vol03i06` (**likely predatory — do not cite**)
