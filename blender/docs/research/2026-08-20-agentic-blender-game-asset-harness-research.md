# Agentic 3D Modeling for Game Assets in Blender — Proven Practices

**Date:** 2026-08-20
**For:** `blended` — a Blender-based harness for agentic game-asset modeling
**Method:** home-still corpus first (`distill_search` / `markdown_read` / `catalog_read`), web search only to fill gaps; 57 new PDFs downloaded into the corpus this run.

---

## 0. Read this first — what is actually new

You already have a mature Blender-via-MCP workflow in `scp_characters`, with `docs/literature_review.md` (metamorphic testing for garments) and `docs/references.md` (~90 citations on skinning, cloth, mocap, IK, anthropometry). **This brief does not re-derive any of that.** Everything below sits in the three places your existing docs are thin or silent:

1. **Agentic modeling as a literature.** Your docs cite exactly one paper on it (3DCodeBench). There are now ~20, and they agree on several things.
2. **The generate-vs-program tradeoff.** Neural mesh generation (TRELLIS / Rodin / Hunyuan3D) vs. procedural `bpy` code is a one-sentence policy in your `CLAUDE.md` and nothing more. It is the central architectural decision for `blended`.
3. **Automated validation of *generated* geometry** outside the garment domain — hard-surface props, topology, manifoldness, UVs, export correctness.

`/Users/ladvien/blended` is currently an empty repo (`.git`, `.gitignore`, `LICENSE`). This brief is written as input to its architecture, not as a survey for its own sake.

---

## 1. The eight findings that are actually proven

Each is tagged with how strong the evidence is. I distinguish **[PROVEN]** (multiple independent results, or one large controlled study), **[SINGLE-STUDY]** (one paper, replicable-looking method), and **[DEMO]** (existence proof, small N, no ablation).

### 1.1 Program-as-artifact beats geometry-as-artifact for this use case — [PROVEN]

Every serious system in this space emits *code* — a Blender Python script, a node graph, a CAD feature tree — rather than raw vertices. The reasons converge across papers: deterministic, engine-ready, precisely editable, diffable, reusable, parameterizable.

3DCodeBench states it directly: procedural 3D modeling through code offers *"deterministic, engine-ready, and precisely editable assets that neural 3D generators inherently lack"* (`10.48550_arxiv.2606.01057`).

Infinigen is the scale proof: **182 named procedural generators exposing 1,070 named high-level parameters**, every asset generated from randomized mathematical rules with *no external asset library at all* (`10.48550_arxiv.2306.09310`). Its **Node Transpiler** — which compiles artist-authored Geometry Node graphs into general Python so the graph *structure*, not just its inputs, can be randomized — is the single most transferable engineering idea in that paper for a harness. It also means non-programmers can contribute by authoring node graphs.

DeepCAD makes the representational argument explicitly: a command sequence can be converted to a B-rep but not vice versa, and command sequences stay human-interpretable and directly editable in the real tool (`10.48550_arxiv.2105.09492`).

**Implication for `blended`:** the artifact the agent produces is a Python module in your existing `*Parameters` + `*Builder` shape, not a `.blend` or a mesh. That is already your `scp_characters` convention — the literature backs it.

### 1.2 Execution feedback is the single biggest lever — and agentic autonomy fixes *executability*, not *geometry* — [PROVEN]

This is the most important finding in the whole sweep, and I verified the numbers directly against the paper text rather than trusting a summary.

3DCodeBench (Google DeepMind, 212 Infinigen-derived object categories, 12 VLMs, Blender 5.0):

- A **stateless retry loop** — feed back the previous script plus the truncated Blender traceback, max 2 retries — lifts aggregate executability from **0.702 → 0.974 (+27.2 pp)** across 22 model×track cells. 8 of 22 cells hit 1.000.
- Running the same backbones inside **full coding-agent harnesses** (Claude Code, Codex CLI, Gemini CLI, 600–900 s wall clock, free to write/run/debug/iterate) lifts executability **0.747 → 0.973 (+22.6 pp)** — comparable to the dumb retry loop.
- But on the ST-success ∩ Agent-success intersection, **conditional shape quality barely moves**: SigLIP-2 view similarity **−0.010**, Chamfer **+0.001**, Uni3D 3D↔3D **−0.003**.

Verbatim: *"The harness addresses simple API usage errors. However, it does not yield semantically richer or more shape-accurate geometry once a script compiles."*

Corroborating: thinking-budget scaling gains ~19 executability points for Gemini 3.1 Flash Lite but **<5 points** for Pro-class models. The bottleneck for capable models is not reasoning effort — it is environment feedback.

**Implication:** do not spend harness engineering on making the agent *smarter about geometry*. Spend it on making the environment tell the truth loudly and fast. A cheap traceback loop captures most of the available win. The remaining gap — semantic and structural correctness of the shape — is *not* closed by more agent autonomy, and must be closed by validators and by the human in the loop. This is exactly the doctrine already encoded in your `CLAUDE.md` rules 5–8; it now has a large controlled result behind it.

### 1.3 API version drift is the dominant failure mode — pin the version, ship an API knowledge base — [PROVEN]

3DCodeBench's two dominant failure modes: **(1) API mismatches**, and **(2) once executable, disconnected or floating geometric components** — silhouettes right, structure wrong.

Two models were excluded from the benchmark for falling below a 10% executability floor, and **~85% of their failures were Blender 4.x → 5.0 API drift**, with named examples:

- `KeyError "Specular"` — removed BSDF socket
- `AttributeError 'Mesh'.use_auto_smooth`
- enum `"SUBSURFACE"` not found in `ObjectModifiers.new`
- `TypeError create_cone keyword "diameter1" is invalid`

The paper's diagnosis is precise: these models are *"not modeling-capacity-limited but knowledge-cutoff-limited."*

Your own `CLAUDE.md` already carries the sibling trap — *"Blender 5.x moved Actions to slots/layers; `action.fcurves` is empty, walk `action.layers → strips → channelbags → fcurves`"* — discovered the expensive way. That is the same failure class.

**Implication:** `blended` needs a versioned **API-drift knowledge base** as a first-class artifact, not a comment. 3DCodeBench's curation pipeline built exactly this and called it the *Blender 5.0 API module* of an **Experience Library**: a catalog of syntax changes and migration rules from older versions so agents resolve deprecations preemptively. Pin the Blender version in the repo, assert it at session start, and grow the drift catalog every time a traceback teaches you something.

### 1.4 Retrieval over the DCC API docs measurably helps — [SINGLE-STUDY]

LL3M builds **BlenderRAG** — a RAG database over 1,729 Blender 4.4 documentation PDFs — and reports it **cut total mesh-generation error rate by 26%** (`10.48550_arxiv.2508.08228`).

This is the cheapest structural win available and it composes with 1.3: retrieval covers the API surface the model half-knows; the drift catalog covers what it knows *wrongly*.

### 1.5 VLM visual verification is real, useful, and systematically biased toward accepting — [PROVEN]

The closest rigorous analogue to your render-and-critique loop is the TikZ study (`10.48550_arxiv.2606.15693`): generate visual code → render → VLM verifier scores and gives feedback → regenerate. VTikZ dataset, 8 human annotators, 3,907 distinct annotated items, Krippendorff's α = 0.898.

- Best verifier (Gemini-3, agentic-vision variant) reaches **F1 = 0.815** at detecting "perfectly applied" edits — but with a **systematic false-positive bias**: high recall, low precision, optimal threshold near 1.0. It over-estimates correctness.
- **Verifier reliability degrades as the generator improves.** Correlation with human judgment is 0.765 on Qwen-generated outputs but only **0.456** on Gemini-generated outputs. Better generators produce outputs that are harder to discriminate.
- Feedback helps weak generators a lot (+11 to +20 perfect customizations) and strong generators barely (+5). For strong generators the bottleneck is **verifier precision**, not feedback richness.
- **More elaborate verifiers did not win.** Segmentation-tool-based and property-decomposition verifiers did *not* beat a plain multimodal LLM verifier.
- GPT-4o's outright success rate on visual-code customization: **26%**.

BlenderGym (`10.48550/arXiv.2504.01786`, CVPR 2025) adds a complementary result. **Correction to a claim I initially found in the sweep:** BlenderGym does *not* show verifier-scaling beats generator-scaling. Its abstract says the verifier *"can itself be improved through inference scaling"* and that *"inference compute is not uniformly effective and can be optimized by strategically distributing it between generation and verification."* That is a distribution result, not a ranking. Verify against the full text once it converts.

**Implication:** a VLM screenshot critic belongs in `blended`, but as a *cheap wide net biased toward "looks fine"*, never as an acceptance gate. Stopping policy must be conservative — a false positive terminates refinement early and reads as success. And this is precisely why 1.2's finding matters: the harness closes executability, the VLM catches gross visual wrongness, and neither of them certifies the geometry. Your rule 8 is the correct response and now has external support.

### 1.6 Split the critic from the verifier — check that the fix was actually applied — [SINGLE-STUDY]

LL3M runs six roles: planner → retrieval → coding → **critic** → **verification** → user-feedback. The critic renders 5 adaptive-distance views and lists discrepancies. A *separate verification agent* then re-renders after the fix and diffs new-vs-old renders against the critique list, checking each item was actually addressed — because the coding agent's fix *"may not always resolve all the issues in one attempt."*

The same second-order problem is reported independently by the Planner-Actor-Critic paper (`10.48550_arxiv.2601.05016`), which uses Blender-MCP directly and is architecturally the closest published system to your setup: *"the actor does not always incorporate the critic's feedback."*

**Implication:** the check "did the edit actually land" is a distinct check from "is the result correct," and it catches a real, reported failure mode. It is also cheap.

### 1.7 Iteration saturates around three rounds — [DEMO, but consistent with 1.5]

Planner-Actor-Critic, in their own words: *"after multiple iterations (often three), the modeling quality degrades or converges, making further improvements difficult."*

SWE-agent finds the analogous thing in code: agents that finish early succeed more (median $1.21 / 12 steps for successes vs. $2.52 / 21 steps for failures), and 52.0% of failures are *incorrect implementation*, not localization (`10.48550_arXiv.2405.15793`). More budget ≠ more success.

Reflexion adds the boundary condition: it works when the action space is enumerable and observable (AlfWorld, +22 pp) and *fails outright* on open-ended ambiguous search (WebShop — no improvement after 4 trials, abandoned) (`10.48550_arXiv.2303.11366`).

**Implication:** bound refinement at ~3 iterations, then escalate to the human. That maps cleanly onto the Reflexion boundary: mesh *repair* is enumerable and observable (transfers well); stylistic and art-direction decisions are not (do not transfer) — which is already your `CLAUDE.md` "art direction is the user's" rule.

### 1.8 Agent-computer interface design moves the numbers more than model choice — [PROVEN]

SWE-agent: purpose-built ACI vs. bare shell, **18.0% vs 11.0%** resolve rate on SWE-bench Lite, same model, no weight changes. Ablations worth transferring:

| Ablation | Δ | Blender analogue |
|---|---|---|
| No file editor | −7.7 pp | no structured scene-edit primitive; raw `execute_blender_code` only |
| Window too small (30 lines) | −3.7 pp | screenshot too zoomed-in / scene query returns one object |
| Window too large (whole file) | −5.3 pp | dumping the whole scene graph |
| No edit linting guardrail | −3.0 pp | no post-edit validation before the next step |
| Iterative search | **−6.0 pp (worse than no search)** | agent paging exhaustively through scene objects |

Also: any edit attempt eventually succeeds 90.5% of the time, but **after one failed edit that drops to 57.2%** — failure compounds, so guardrails that prevent a bad edit landing are worth more than recovery.

Agentless (`10.48550_arxiv.2407.01489`) is the counterweight: a three-phase localize→repair→validate pipeline with no agentic loop hit **32.00%** on SWE-bench Lite at **$0.70/instance**, beating costlier agentic tools. Its verifier finding transfers directly: reproduction-test generation was the single biggest lever (77 → 81 → 96 fixes), **but only 94/300 ground-truth patches pass their own generated reproduction test** — the verifier is ~94% reliable even against a known-correct fix.

**Implication:** design the Blender tool surface deliberately. Human UIs are not agent UIs. Prefer a small set of purpose-built query/edit primitives (framed screenshot with rotation assertion, scene-object query with a bounded window, mesh-stats probe, validation runner) over a single `execute_blender_code` firehose — while keeping the firehose for the long tail.

---

## 2. Generate vs. program — the decision your docs haven't made

Two production paths, and the literature is now clear about what each is good for.

### 2.1 Neural generators: fast, wrong topology, no UVs you'd ship

| System | Output | Cost | Ceiling |
|---|---|---|---|
| TRELLIS (`10.48550_arxiv.2412.01506`) | mesh / 3DGS / radiance field from one shared sparse-voxel latent | ~10 s/asset, 2B params | trained on ~500K curated assets; FlexiCubes mesh decode at 256³ |
| MeshAnything (`10.48550_arxiv.2406.10163`) | artist-style AR mesh, shape-conditioned | — | **avg 318 faces / 172 verts** vs Marching Cubes' 146K faces / 462K verts for the same shape; trained on <800-face meshes |
| MeshGPT (`10.48550_arxiv.2311.15475`) | AR triangle mesh, RQ-VAE tokens | **30–90 s per mesh** | <800 faces |
| EdgeRunner (`10.48550_arxiv.2409.18114`) | AR mesh at 512³ | — | up to **4,000 faces**; success rate falls as sequence length approaches the ceiling |
| SATO / Strips as Tokens (`sig2026_Strips_as_Tokens_...`, `10.1145/3811286`) | triangle-strip tokens with **native UV-island boundaries**; same sequence decodes tri *or* quad | 256×A800 / 3 days to train | the first native-mesh generator that treats UV segmentation as an output, not a post-process |

The honest ceiling: **hundreds to a few thousand faces**, no rig, no LODs, and — except SATO — no usable UVs. Against your fixed `POLY_BUDGET = 13000` tris per body mesh and measured 36–82K tris per exported character, that is a *blocking* stage, not a *character* stage.

### 2.2 What that means concretely

Use neural generation for **blockout, silhouette exploration, and background props you will retopologize**. Use procedural `bpy` programs for **anything that must hit a poly budget, deform, carry a UV layout, or be edited later**.

That is not a hedge — it follows from 1.1 (programs are editable and deterministic; meshes are not) plus the face-count ceilings above plus 1.2 (the agent loop cannot fix geometry once code compiles; it *can* fix a parameter in a program).

### 2.3 Evidence quality warning on the one paper that measures this end-to-end

There is exactly one paper I found that runs the head-to-head comparison you'd want — *"Prompted Props, Human Pipelines: Evaluating AI-Generated 3D Assets for Game-Ready Environments"* (`10.55677/ijhrsss/15-2026-vol03i06`). It reports Hunyuan 3D generating an asset set in 79 min and AI-assisted scene assembly in 238 min vs. 716 min for a hand-authored Blender scene, with AI outputs showing dense over-triangulated geometry, fragmented UVs, clipping, and texture loss under decimation.

**Do not cite those numbers as evidence.** The venue is the *International Journal of Human Research and Social Science Studies* — a self-published social-science journal whose own site states articles publish **within 12 hours of receiving the publication fee**, not in DOAJ, no impact factor, and a severe scope mismatch with computer graphics. Verdict: **likely predatory**. Treat its three-tier viability framing (ideation ✓ / background props conditionally / production assets ✗) as a plausible hypothesis worth testing yourself, and its timings as anecdote.

Two other venues in the sweep are also weak and should be cited with the same caution:

- `10.54254/2755-2721/2026.gu35001` — *Applied and Computational Engineering* (EWA Publishing), flat $450 APC mass conference-proceedings series. **Likely predatory.**
- `10.64509/jdi.11.51` — *Journal of Design Intelligence*, brand new (Jan 2026), Hong Kong, no track record or indexing. **Weak, unproven.**

The rigorous end-to-end comparison for game-ready output **does not exist in the literature yet.** That is a gap you are unusually well positioned to fill, given `scp_characters` already has measured per-character tri/joint/anim counts and a regression suite.

---

## 3. Reference architecture implied by the evidence

3DCodeBench's own data-curation pipeline is the closest thing to a published blueprint, and it decomposes cleanly into two libraries. Mapped onto `blended`:

**Skills Library — tools that give the agent objective feedback**

| Tool | What it does | Backed by |
|---|---|---|
| **Simulator** | executes the script in a sandboxed, version-pinned Blender; returns tracebacks | 1.2 (+27.2 pp), 1.3 |
| **Mesh Analyzer** | non-manifold edges, invalid geometry, zero-area triangles, abnormal vertex counts, disconnected components | 1.3 failure mode #2; Attene mesh-repair taxonomy |
| **Visual Critic** | multi-view render diffed against reference | 1.5 — *advisory only*, never a gate |
| **Code Simplifier** | flattens deeply nested factory code into standalone scripts while preserving the shape | 3DCodeBench curation |
| **Framed capture** | front/right/top/¾ with a rotation assertion before trusting the image | your own smooth-view trap; 1.8 window ablations |

**Experience Library — accumulated knowledge, versioned in-repo**

| Module | Content |
|---|---|
| **API drift catalog** | Blender version → removed/renamed API, with the fix. Grown from every traceback. |
| **Parts Assembly** | structured templates for composing parts into a coherent object — maps onto your `*Builder` composition rule |
| **Code Organization** | the stylistic/architectural contract (your no-magic-numbers, unit-suffixed-names rules) |
| **Class Deduplication** | prevents redundant generators for the same asset class |

Plus **BlenderRAG**-style retrieval over the pinned Blender version's docs (1.4, −26% error rate).

**Loop shape**, from 1.2 / 1.6 / 1.7:

```
plan → retrieve API context → emit small code chunk → execute (traceback → retry ≤2)
     → mesh-analyze (hard gate)  → render + VLM critique (advisory)
     → verify the critique's items were actually applied
     → ≤3 refinement rounds, then escalate to human
     → pin the verified result as a regression test
```

The hard gate is the **Mesh Analyzer**, not the VLM. That inversion is the whole lesson of 1.5.

### 3.1 Automated metrics that actually track human judgment

3DCodeBench correlated six automated metrics against 3DCodeArena human-preference Elo across 12 models:

- **SigLIP-2** multi-view cosine similarity — strongest linear predictor, **Pearson r = 0.964**
- **DINOv3** — highest rank correlation, **Spearman ρ = 0.972**
- Uni3D 3D↔3D — the metric they say most strongly tracks human preference among the 3D-native ones
- Chamfer Distance — weaker

Their conclusion: these *"reliably substitut[e] for costly human-in-the-loop annotations."* If `blended` needs an automated shape-fidelity number against a reference, render four canonical views (45°/135°/225°/315°) and compute SigLIP-2 cosine. This is the one place a cheap automated visual metric is defensible — because it was calibrated against human preference, unlike a VLM's verbal verdict.

GPTEval3D (`10.48550/arxiv.2401.04092`, downloaded this run) is the complementary tool: pairwise Elo with a VLM judge, human-aligned.

### 3.2 Game-ready is a separate gate from "looks right"

Nothing in the agentic literature checks game-readiness. From the craft and mesh-processing sources in the corpus:

From Vaughan, *Digital Modeling* (`book_digital_modeling_vaughan`, converted and indexed):

- p.175 — *"Animation of an organic object can be like a hurricane to a house if good polygon flow doesn't exist"*; keep clean flow even on static models, in case they deform later.
- p.320 — character poly budgets scale with hardware generation (500 → 30,000 polys across ~15 years).
- p.150–151 — high-poly sculpt → retopologized low-poly base → normal-map bake is the standard game pipeline; topology is irrelevant at sculpt stage and decisive at retopo stage.
- p.327 — worked example: ~6,000 triangles for a quadruped creature in Unity. Rule: *"use as few polygons as possible while still capturing the shape... enough geometry to produce a good silhouette."* And: *"always check with your team [for] the budget... before building anything."*
- p.340 — 1,500–2,000 polys for a real-time weapon prop.
- p.182 — hide UV seams on the inside of limbs and the back of the head; minimize island count; space islands to avoid bleed without wasting space.
- p.336/339 — bake only from the lowest SubD level; ZBrush inverts normal maps, so flip the green channel for non-ZBrush engines. *(A trivially automatable validator check.)*

From Attene, Campen & Kobbelt, *Polygon Mesh Repairing: An Application Perspective* (`10.1145/2431211.2431214`) — this is your defect taxonomy for a Mesh Analyzer:

- Defect origin predicts defect type. **Digitized** meshes → noise, holes, chamfered features. **Designed** meshes (hand-modeled, procedurally generated, or LLM-authored) → **non-manifoldness, gaps, self-intersections, singularities**. That second list is your check list.
- Gap-closing is threshold-bounded: algorithms *"can only guarantee gap-free output if all gaps in the input are narrower than some specified threshold... high thresholds... result in arbitrarily implausible results."* Auto-repair must report its threshold, never blind-fill.
- **T-junctions** are null-area combinatorial holes — coincident geometry with inconsistent connectivity. A distinct failure mode from holes and gaps, needing its own detector.
- **Degenerate (zero-area) triangles** break normal, circumcenter, and barycentric computation used by nearly everything downstream. Gate on near-zero-area triangle count before rigging or simulation.

Facet-orientation correction (`A-Simple-Method-for-Correcting-Facet-Orientations...`, Takayama et al.) defines correctness formally — CCW winding from the viewpoint must correspond to the solid's exterior — and uses ray-intersection parity for occluded cavities. Validated on 3,168 hand-authored meshes (SHREC'10 Generic 3D Warehouse).

---

## 4. Corpus inventory — what home-still already holds

Grouped by cluster. Stems are searchable via `distill_search` / `markdown_read`.

### 4.1 Agentic 3D modeling (the new cluster)

| Stem / DOI | Title |
|---|---|
| `10.48550_arxiv.2508.08228` | LL3M: Large Language 3D Modelers (2025) |
| `10.48550_arxiv.2606.01057` | 3DCodeBench: Benchmarking Agentic Procedural 3D Modeling Via Code (2026) |
| `10.48550_arxiv.2601.05016` | Planner-Actor-Critic Framework for Agent Augmented 3D Modeling (2026) |
| `10.48550_arxiv.2510.17603` | ShapeCraft: LLM Agents for Structured/Textured/Interactive 3D Modeling (2025) |
| `10.48550_arxiv.2412.14203` | BlenderLLM: Training LLMs for CAD with Self-improvement (2024) |
| `10.48550_arxiv.2607.01766` | SimWorlds: Multi-Agent System for Dynamic 3D Scene Creation (2026) |
| `10.48550_arxiv.2410.21909` | SceneGenAgent: Precise Industrial Scene Generation with Coding Agent (2024) |
| `10.48550_arxiv.2401.06437` | 3D-PreMise: Can LLMs Generate 3D Shapes with Sharp Features? (2024) |
| `10.48550_arxiv.2606.15693` | Imperfect Visual Verification for Code Edition: A Case Study on TikZ (2026) |
| `10.48550_arxiv.2606.31252` | Embodied CAD: Solver-Grounded LLM Agents for Parametric B-Rep Assembly (2026) |
| `10.48550_arxiv.2607.02448` | AgentsCAD: Multi-Agent LLM + Geometric Feature Recognition (2026) |
| `10.48550_arXiv.2607.08804` | Programming-by-Example for Batch-Editing Collision Meshes in 3D Software (2026) |
| `10.48550_arxiv.2604.10075` | Hierarchical & Geometry-Aware Graph Representations for Text-to-CAD (2026) |
| `sig2026_B-repLer_...` / `10.1145/3799902.3811166` | B-repLer: Language-guided Editing of CAD Models (2026) |
| `10.48550_arxiv.2405.10255` | When LLMs Step into the 3D World: Survey & Meta-Analysis (2024) |
| `10.48550_arxiv.2505.05474` | 3D Scene Generation: A Survey (2025) |
| `10.48550_arxiv.2604.26509` | 3D Generation for Embodied AI and Robotic Simulation: Survey (2026) |
| `10.64509_jdi.11.51` ⚠ | Language Models as 3D Layout Designers: a Survey (2026) — weak venue |
| `10.54254_2755-2721_2026.gu35001` ⚠ | LLMs in 3D Modeling: Current Workflows (2026) — likely predatory venue |
| `10.55677_ijhrsss_15-2026-vol03i06` ⚠ | Prompted Props, Human Pipelines (2026) — likely predatory venue |

### 4.2 Procedural / program-based modeling

Infinigen (`10.48550_arxiv.2306.09310`), Infinigen Indoors (`10.48550_arxiv.2406.11824`), parameterized terrain library (`10.48550_arxiv.2506.19751`), DeepCAD (`10.48550_arxiv.2105.09492`), ABC CAD dataset (`10.1109_cvpr.2019.00983`), CGA shape / Procedural Modeling of Buildings (`10.1145_1179352.1141931`), Recent Advances in Procedural Generation of Buildings (`10.1109_tg.2023.3262507`), Procedural Urban Forestry (`10.1145_3502220`), Interactive Modeling of Plants (`10.1109_38.736469`), L-py (`10.3389_fpls.2012.00076`), Inverse Procedural Modelling of Trees (`10.1111_cgf.12282`), Model Synthesis (`10.1109_tvcg.2010.112`), Semantic Scene Description Language for Layout Solving (`10.1609_aiide.v6i1.12398`), Probabilistic Reasoning for Assembly-Based 3D Modeling (`10.1145_1964921.1964930`), Component-Based Shape Synthesis (`10.1145_2185520.2185551`), PCGRL (`10.1609_aiide.v16i1.7416`), PCGML survey (`10.1109_tg.2018.2846639`), PCGRLLM (`10.48550_arxiv.2502.10906`), Deep Learning for PCG (`10.48550_arXiv.2010.04548`), PCG-KT (`10.48550_arxiv.2305.00644`), Search-Based PCG survey (`10.48550_arxiv.2311.04710`), Procedural Dungeon Generation survey (`10.5753_jis.2021.999`), PCG-in-Games book chapters (`pcgbook-ch01/ch02/ch05`), *Procedural Content Generation for Games* (Deolikar & Lupiani, Apress 2025 — full book, indexed).

The Apress book is worth a targeted read when building the tool surface. Its eight workshops are directly reusable technique inventory: parametric weapon generator with proportion maintenance (Ch.2–3), Shader/Geometry Nodes with bump-array→normal-map baking and auto-UV-unwrap (Ch.4), Geometry Nodes **Repeat blocks** (loop equivalent) and **Topology nodes** (Ch.5), value noise / fBm / diamond-square / hybrid multifractal terrain in `bpy` (Ch.6), L-system turtle interpreters 2D→3D (Ch.7), GIS-driven building generation (Ch.8), and a Blender→UE5 export pipeline with the exact postprocess order — triangulate, apply transforms/modifiers, set origin, join, scale, move to world origin → glTF/FBX.

### 4.3 Generative 3D (geometry, texture, datasets, eval)

**Native mesh generation:** MeshGPT, MeshAnything, MeshAnything V2 (`2408.02555`), EdgeRunner, SATO/Strips-as-Tokens, plus newly downloaded BPT (`2411.07025`), Nautilus (`2501.14317`), MeshXL (`2405.20853`), PivotMesh (`2405.16890`), LLaMA-Mesh (`2411.09595`).

**Feed-forward / native 3D diffusion:** TRELLIS (`2412.01506`), LHM (`2503.10625`), GET3D (`2209.11163`), DMTet (`2111.04276`), IM-NET (`1812.02822`), plus newly downloaded Michelangelo (`2306.17115`), Hunyuan3D 2.0 (`2501.12202`), TripoSG (`2502.06608`), Direct3D (`2405.14832`), LRM (`2311.04400`), InstantMesh (`2404.07191`), CraftsMan3D (`2405.14979`), Cube/Roblox (`2503.15475`), CubePart (`2605.28763`).

**SDS lineage:** Advances in 3D Generation survey (`2401.17807`), plus DreamFusion (`2209.14988`) and ProlificDreamer (`2305.16213`).

**Texture / PBR:** DreamMat, TexSliders (SIGGRAPH 2024 stems), plus Paint3D (`2312.13913`), TEXTure (`2302.01721`), Text2Tex (`2303.11396`), SyncMVD (`2311.12891`).

**Datasets:** Objaverse (`2212.08051`), Objaverse-XL (`2307.05663`), GSO (`2204.11918`), OmniObject3D (`2301.07525`).

**Evaluation:** GPTEval3D (`2401.04092`), Evaluation Metrics for Intelligent Generation of Graphical Game Assets (`10.1109_tpami.2024.3398998`), Intelligent Generation of Graphical Game Assets systematic review (`10.1145_3708499`).

### 4.4 Game-asset production algorithms

Instant Field-Aligned Meshes (`Instant-Field-Aligned-Meshes`), QEx (`10.1145_2508363.2508372`), Quad-Mesh Generation survey (`10.1111_cgf.12014`), Mixed-Integer Quadrangulation (`10.1145_1531326.1531383`), QuadCover (`10.1111_j.1467-8659.2007.01060.x`), Hex-Mesh survey (`10.48550_arXiv.2202.12670`), Autocuts (`Autocuts-...`), Boundary First Flattening (`10.1145_3132705`, downloaded this run), Hoppe's appearance-preserving QEM (`10.1109_visual.1999.809869`), Simplifying Textured Triangle Meshes in the Wild (`10.48550_arxiv.2409.15458`), *Level of Detail for 3D Graphics* (`book_level_of_detail_3d_graphics_luebke`), Polygon Mesh Repairing (`10.1145_2431211.2431214`), Facet Orientation Correction, Nooruddin & Turk volumetric repair (`10.1109_tvcg.2003.1196006`), Pinocchio (see §6 — DOI defect), HumanRig (`2412.02317`), Neural Blend Shapes (`2105.02451`), SkinCells (`10.1111_cgf.70381`), auto-rigging dissertation (`10.5821_dissertation-2117-96275`), procedural rigging design principles (`10.5121_ijcga.2015.5104`), *Digital Modeling* (Vaughan), *Real-Time Rendering 4th* (`book_real_time_rendering_4th_akenine`), PBR Guide Part 2, Beginning PBR Texturing, SIGGRAPH Advances real-time-rendering course notes (`s2008-advances-*`).

### 4.5 Harness engineering (already strong)

SWE-agent, Agentless, OpenHands, Live-SWE-agent, SWE-Gym, Kimi-Dev, ReAct, Reflexion, Cognitive Architectures for Language Agents, ToolSandbox, MCP-tools usage study (`2603.23802`), Judging LLM-as-a-Judge, LLM-as-a-judge survey, Who Validates the Validators (criteria drift), Let's Verify Step by Step, AI Agents That Matter, Rigorous Agentic Benchmarks, BigCodeBench, LiveCodeBench, BaxBench, τ-bench / τ²-bench, LoCoBench-Agent, TheAgentCompany, CANVAS, RESP (visual glitch detection in games), Human-in-the-Loop SWE Agents, Magentic-UI, Collaborative Gym.

Newly downloaded: LLMs Cannot Self-Correct Reasoning Yet (`2310.01798`), Self-Refine (`2303.17651`), CodeAct (`2402.01030`), OSWorld (`2404.07972`), WebArena (`2307.13854`), VisualWebArena (`10.18653/v1/2024.acl-long.50`), Design2Code (`2403.03163`), Sketch2Code (`2410.16232`), PPTAgent (`2501.03936`), AgentBench (`2308.03688`), Gorilla (`2305.15334`), Toolformer (`2302.04761`).

---

## 5. Downloaded this run

**57 new PDFs** landed in the corpus (8,228 → 8,285). Conversion is queued, not forced — `pipeline_drift` went 71 → 128. Note: at the time of writing, scribe reported **idle with 12/12 slots free** while 128 documents sat unconverted. If they haven't converted in a few hours, the auto-sweeper on `big` may need a nudge; I deliberately did not call `scribe_convert`.

<details>
<summary>Full list by cluster (57 DOIs)</summary>

**Agentic 3D modeling (14)**
`10.48550/arXiv.2403.01248` SceneCraft (Blender code) ·
`10.48550/arxiv.2310.12945` 3D-GPT ·
`10.48550/arxiv.2404.17672` BlenderAlchemy ·
`10.48550/arxiv.2309.12276` LLMR ·
`10.48550/arxiv.2312.09067` Holodeck ·
`10.1109/iccv51701.2025.00684` CAD-Assistant ·
`10.48550/arXiv.2502.15601` WorldCraft ·
`10.18653/v1/2025.naacl-demo.37` L3GO ·
`10.48550/arXiv.2605.18451` Code-as-Room ·
`10.48550/arXiv.2606.02580` Thinking in Blender (SEIG) ·
`10.48550/arxiv.2503.15475` Cube (Roblox) ·
`10.48550/arxiv.2501.00912` AutoPresent ·
`10.48550/arXiv.2504.01786` BlenderGym ·
`10.48550/arxiv.2410.05340` CADCodeVerify

**Procedural / program synthesis (8)**
`10.48550/arxiv.2406.00144` Query2CAD ·
`10.48550/arxiv.2009.08026` ShapeAssembly ·
`10.48550/arxiv.1901.02875` Learning to Infer and Execute 3D Shape Programs ·
`10.48550/arxiv.1707.09627` Learning to Infer Graphics Programs from Hand-Drawn Images ·
`10.1109/cvpr.2018.00578` CSGNet ·
`10.48550/arxiv.2206.06994` ProcTHOR ·
`10.48550/arXiv.2505.10755` Infinigen-Sim ·
`10.1145/3132705` Boundary First Flattening

**Mesh generation & tokenization (5)**
`10.48550/arxiv.2411.07025` BPT ·
`10.48550/arxiv.2501.14317` Nautilus ·
`10.48550/arxiv.2405.20853` MeshXL ·
`10.48550/arxiv.2405.16890` PivotMesh ·
`10.48550/arxiv.2411.09595` LLaMA-Mesh

**Native 3D / feed-forward generation (7)**
`10.48550/arxiv.2306.17115` Michelangelo ·
`10.48550/arxiv.2501.12202` Hunyuan3D 2.0 ·
`10.48550/arxiv.2502.06608` TripoSG ·
`10.48550/arxiv.2405.14832` Direct3D ·
`10.48550/arxiv.2311.04400` LRM ·
`10.48550/arxiv.2404.07191` InstantMesh ·
`10.48550/arxiv.2405.14979` CraftsMan3D

**Texture / PBR (4)**
`10.48550/arxiv.2312.13913` Paint3D ·
`10.48550/arxiv.2302.01721` TEXTure ·
`10.48550/arxiv.2303.11396` Text2Tex ·
`10.48550/arxiv.2311.12891` SyncMVD

**SDS lineage (2)**
`10.48550/arxiv.2209.14988` DreamFusion ·
`10.48550/arxiv.2305.16213` ProlificDreamer

**Datasets & evaluation (5)**
`10.48550/arxiv.2212.08051` Objaverse ·
`10.48550/arxiv.2307.05663` Objaverse-XL ·
`10.48550/arXiv.2204.11918` Google Scanned Objects ·
`10.48550/arxiv.2301.07525` OmniObject3D ·
`10.48550/arxiv.2401.04092` GPTEval3D

**Harness engineering (12)**
`10.48550/arXiv.2310.01798` LLMs Cannot Self-Correct Reasoning Yet ·
`10.48550/arxiv.2303.17651` Self-Refine ·
`10.48550/arxiv.2402.01030` CodeAct ·
`10.48550/arxiv.2404.07972` OSWorld ·
`10.48550/arxiv.2307.13854` WebArena ·
`10.18653/v1/2024.acl-long.50` VisualWebArena ·
`10.48550/arxiv.2403.03163` Design2Code ·
`10.48550/arxiv.2410.16232` Sketch2Code ·
`10.48550/arxiv.2501.03936` PPTAgent ·
`10.48550/arxiv.2308.03688` AgentBench ·
`10.48550/arxiv.2305.15334` Gorilla ·
`10.48550/arxiv.2302.04761` Toolformer

</details>

---

## 6. Acquisition list

### 6.1 Paywalled DOIs — no open-access PDF found

| Priority | DOI | Title | Venue | Why it matters here |
|---|---|---|---|---|
| **High** | `10.1145/3450626.3459818` | Fusion 360 Gallery Dataset | ACM SIGGRAPH Asia / TOG 2021 | 8,625 human design sequences; the reference dataset under most CAD program-synthesis follow-ups |
| **High** | `10.1145/258734.258849` | Surface Simplification Using Quadric Error Metrics (Garland & Heckbert 1997) | ACM SIGGRAPH | the LOD/decimation algorithm every tool implements; you need the original for tolerance semantics |
| **High** | `10.1111/cgf.13498` | QuadriFlow: Scalable and Robust Quadrangulation | Computer Graphics Forum (Wiley) 2018 | the practical auto-retopology algorithm; the retopo gate depends on knowing its failure modes |
| **High** | `10.1145/3658146` | CLAY: Controllable Large-scale Generative Model for High-quality 3D Assets | ACM TOG / SIGGRAPH 2024 | 1.5B vecset diffusion + 2K PBR textures; the industry-grade reference point, no arXiv mirror |
| **Med** | `10.52202/079017-0242` | Text2CAD: Sequential CAD Designs from Beginner-to-Expert Text Prompts | NeurIPS D&B 2024 | canonical text-to-CAD-sequence benchmark, referenced by nearly every 2025–26 text-to-CAD paper |
| **Med** | `10.1115/detc2025-169758` | CAD-Coder: Open-Source VLM for CAD Code Generation | ASME IDETC-CIE 2025 | 100% valid-syntax-rate image→CadQuery; GenCAD-Code dataset (163k pairs) |
| **Med** | `10.1145/566654.566590` | Least Squares Conformal Maps for Automatic Texture Atlas Generation (Lévy 2002) | ACM SIGGRAPH | foundational UV unwrapping; alt DOI `10.1145/566570.566590` not yet tried |
| **Med** | `10.1109/ICCV51701.2025.02440` | MaterialMVP: Illumination-Invariant Material Generation via Multi-View PBR Diffusion | ICCV 2025 | the PBR-material half of the generative pipeline; no arXiv preprint located |
| **Low** | `10.1145/3197517.3201337` | Fast Winding Numbers for Soups and Clouds (Barill 2018) | ACM TOG | already flagged in your `scp_characters` references as paywalled — same request, worth bundling |

### 6.2 Books and specifications

| Priority | Title | Author / Publisher | Status | Why |
|---|---|---|---|---|
| **High** | *Polygon Mesh Processing* | Botsch, Kobbelt, Pauly, Alliez, Lévy — AK Peters 2010 | **in corpus but CORRUPTED** — 20 conversion attempts failed, no markdown | the one textbook covering remeshing, parameterization, simplification and repair as one toolchain. Re-acquire a clean PDF. |
| **High** | *Procedural Content Generation in Games* | Shaker, Togelius, Nelson — Springer 2016, `10.1007/978-3-319-42716-4` | only scattered chapters locally (`pcgbook-ch01/ch02/ch05`) | the standard PCG textbook; you're missing the constraint-based and ML chapters |
| **High** | Blender Manual (pinned version) | Blender Foundation | not in corpus | ground truth for the exact operators and tolerances the agent calls (Merge by Distance, Select Non-Manifold, UV Pack). Mirror the version you pin — this is also the BlenderRAG corpus per §1.4 |
| **High** | glTF 2.0 Specification | Khronos Group | not in corpus | export-correctness reference; also the source of the 4-influence joint cap you already enforce |
| **Med** | *Physically Based Rendering* | Pharr, Jakob, Humphreys | `Physically_Based_Rendering_3rd` **CORRUPTED** | the 4th edition is free online at pbr-book.org — grab that instead of re-buying the 3rd |
| **Med** | *Computational Geometry: Algorithms and Applications* | de Berg et al. | `book_computational_geometry_de_berg` **CORRUPTED** | underlies the mesh-analyzer predicates |
| **Med** | *ZBrush Character Creation* | Spencer | `book_zbrush_character_creation_spencer` **CORRUPTED** | high→low sculpt/retopo/bake workflow |
| **Med** | *Sculpting the Blender Way* | — | `book_sculpting_blender_way` **CORRUPTED** | Blender-native sculpt→retopo |
| **Med** | *Anatomy for Sculptors* | Zeravcic & Bakalar | `book_anatomy_for_sculptors` **CORRUPTED** | already load-bearing for `scp_characters` characters |
| **Med** | *GPU Gems 2* | NVIDIA | `book_gpu_gems_2` **CORRUPTED** | free online at NVIDIA developer — re-fetch rather than re-buy |
| **Med** | MaterialX Specification | Academy Software Foundation | not in corpus | node-graph material interchange |
| **Med** | OpenPBR Surface Specification | Adobe / Autodesk | not in corpus | successor PBR shading model |
| **Low** | "A Deep Dive into Nanite Virtualized Geometry" | Brian Karis, Epic — SIGGRAPH 2021 Advances course | no DOI, conference talk | the actual reference for cluster-LOD; the course notes PDF is free from Epic |
| **Low** | RigNet: Neural Rigging for Articulated Characters | Xu et al., SIGGRAPH 2020 | not confirmed in corpus | comparison point for Pinocchio / HumanRig / UniRig |

---

## 7. Corpus defects found — worth fixing before citing

These surfaced during verification and would each produce a wrong citation if trusted.

1. **Pinocchio is stored under the wrong DOI. [CONFIRMED]**
   Stem `10.1145_1276377.1276467` contains the genuine full text of Baran & Popović, *Automatic Rigging and Animation of 3D Characters* (verified by reading page 1). But that DOI resolves via Crossref/OpenAlex to an **unrelated Spanish-language surgical-VR thesis**. The real DOI is **`10.1145/1275808.1276467`** (confirmed via `paper_get`: Baran & Popović, MIT, 2007-07-29, 823 citations). Anyone citing the stem's stored DOI cites the wrong paper. Run `catalog_repair` / `distill_reconcile` on this stem.

2. **`Real-Time_Rendering_4th` and `book_real_time_rendering_4th_akenine` are duplicates; the first is dead.**
   `Real-Time_Rendering_4th` failed conversion (`unsupported_content_type:binary`), no markdown. `book_real_time_rendering_4th_akenine` is fully converted and embedded (1,183 chunks, 1,199 pages). Delete or ignore the former.

3. **67 corrupted PDFs corpus-wide; 7 of 9 checked reference books have zero usable markdown.**
   Confirmed dead: `book_polygon_mesh_processing_botsch`, `Physically_Based_Rendering_3rd`, `book_sculpting_blender_way`, `book_zbrush_character_creation_spencer`, `book_computational_geometry_de_berg`, `book_gpu_gems_2`, `book_anatomy_for_sculptors`, `Real-Time_Rendering_4th`, `Lengyel_Transvoxel_Algorithm_Reference`. Any brief that cites page numbers from these is citing content that does not exist locally.

4. **`Instant-Field-Aligned-Meshes` and `Autocuts-...` have no DOI in the catalog.**
   Correct values: `10.1145/2816795.2818078` and `10.1145/3130800.3130845`. Backfill with `catalog_backfill_title` / `catalog_repair`.

5. **Three of the agentic-3D papers sit in low-credibility venues** — see §2.3. Flag them in-corpus if you have a mechanism for it.

6. **`10.48550_arXiv.2504.01786` (BlenderGym) was already in `papers/` but never converted or indexed** — it never surfaced in 20+ `distill_search` queries across two independent sweeps. It is arguably the single most on-point paper for this project (Blender + VLM verifier + inference scaling). Worth confirming it converts in the current batch.

7. **Nine of your existing `scp_characters` citations were already flagged by your own docs** as unverified, metadata-only, or (in one case) nonexistent — the "Weber 2000" episode. Nothing new here, but the same class of defect as (1): a plausible citation that no tool result ever produced.

---

## 8. Where the evidence runs out

Honest gaps. Do not fill these from memory.

- **No rigorous head-to-head on game-readiness.** The one paper attempting it is in a likely-predatory venue (§2.3). Nobody has published a controlled comparison of neural-generated vs. procedurally-authored assets against real engine-import metrics. Your `scp_characters` regression suite and measured per-character tri/joint counts are unusually good raw material for filling this.
- **No metamorphic-testing literature for geometry.** Your own `literature_review.md` already flags this: *"There is no MT-for-geometry, MT-for-CAD, or MT-for-simulation entry in the corpus."* The three references Segura's survey points to (Sim 2005, Donaldson & Lascau 2016, Just & Schweiggert) are not held. Your garment relation library remains, as far as I can tell, original work with no direct precedent.
- **No published validator for "game-ready."** Everything in §3.2 is assembled from craft books and mesh-repair surveys; nobody has published the checklist as such. The closest published gesture is the engine-readiness instrumentation list (import errors, draw calls, frame rate, memory, file size, tri/vertex counts, collision-generation time, LOD needs, manual-correction time) — from the likely-predatory paper, so treat it as a suggestion rather than a result.
- **VLM verification of *3D* specifically is unmeasured.** The TikZ study is 2D vector graphics. LL3M's own limitation note — *"VLMs may still struggle to accurately identify spatial artifacts"* — is an assertion, not a measurement. Whether a VLM can reliably spot a flipped normal, a poke-through, or a non-manifold seam from a viewport screenshot is, as far as this sweep found, **not established**. Given how central that is to your loop, it may be worth measuring yourself against your existing golden outcomes.
- **Nobody has published on long-horizon *stateful* DCC sessions.** Every agentic-3D paper runs one-shot or few-shot script generation into a fresh scene. Your workflow keeps a live Blender session with accumulated state across hours. The closest analogues are stateful-tool-use benchmarks (ToolSandbox, τ²-bench) and OS-level agents (OSWorld) — none of them about creative software with a persistent complex document. This is genuinely uncharted.

---

## 9. Suggested next actions

1. **Wait for conversion, then re-run `distill_search`** on this cluster — 57 new papers will be searchable and several deserve a proper read: SceneCraft, BlenderAlchemy, Thinking-in-Blender, Code-as-Room, BlenderGym.
2. **Fix corpus defect #1 (Pinocchio DOI)** before anything cites it.
3. **Decide the generate-vs-program boundary explicitly** in `blended`'s README, using §2 — the tri-count ceilings make it a fairly mechanical decision.
4. **Build the Mesh Analyzer first**, from the Attene defect taxonomy in §3.2. It is the hard gate, and it is the thing the agentic literature says the agent loop cannot substitute for.
5. **Start the API drift catalog on day one** and pin the Blender version in the repo. §1.3 says this is where most failures live.
6. **Consider measuring VLM verification reliability on 3D** against your existing golden outcomes — §8 says nobody has, and you have the fixtures.

---

## Sources

Primary evidence read in full or in relevant part from the local corpus:

- 3DCodeBench — [10.48550/arXiv.2606.01057](https://doi.org/10.48550/arXiv.2606.01057)
- LL3M: Large Language 3D Modelers — [10.48550/arXiv.2508.08228](https://doi.org/10.48550/arXiv.2508.08228)
- Imperfect Visual Verification for Code Edition (TikZ) — [10.48550/arXiv.2606.15693](https://doi.org/10.48550/arXiv.2606.15693)
- Planner-Actor-Critic for Agent Augmented 3D Modeling — [10.48550/arXiv.2601.05016](https://doi.org/10.48550/arXiv.2601.05016)
- ShapeCraft — [10.48550/arXiv.2510.17603](https://doi.org/10.48550/arXiv.2510.17603)
- BlenderLLM — [10.48550/arXiv.2412.14203](https://doi.org/10.48550/arXiv.2412.14203)
- Infinigen — [10.48550/arXiv.2306.09310](https://doi.org/10.48550/arXiv.2306.09310)
- DeepCAD — [10.48550/arXiv.2105.09492](https://doi.org/10.48550/arXiv.2105.09492)
- TRELLIS / Structured 3D Latents — [10.48550/arXiv.2412.01506](https://doi.org/10.48550/arXiv.2412.01506)
- MeshAnything — [10.48550/arXiv.2406.10163](https://doi.org/10.48550/arXiv.2406.10163) · MeshGPT — [10.48550/arXiv.2311.15475](https://doi.org/10.48550/arXiv.2311.15475) · EdgeRunner — [10.48550/arXiv.2409.18114](https://doi.org/10.48550/arXiv.2409.18114)
- SWE-agent — [10.48550/arXiv.2405.15793](https://doi.org/10.48550/arXiv.2405.15793) · Agentless — [10.48550/arXiv.2407.01489](https://doi.org/10.48550/arXiv.2407.01489) · Reflexion — [10.48550/arXiv.2303.11366](https://doi.org/10.48550/arXiv.2303.11366)
- Polygon Mesh Repairing — [10.1145/2431211.2431214](https://doi.org/10.1145/2431211.2431214)
- Pinocchio (correct DOI) — [10.1145/1275808.1276467](https://doi.org/10.1145/1275808.1276467)
- Vaughan, *Digital Modeling* — local stem `book_digital_modeling_vaughan`
- Deolikar & Lupiani, *Procedural Content Generation for Games* (Apress 2025) — local

Web sources used to augment or verify:

- [BlenderGym project page](https://blendergym.github.io/) · [arXiv:2504.01786](https://arxiv.org/abs/2504.01786) · [CVPR 2025 Open Access](https://openaccess.thecvf.com/content/CVPR2025/html/Gu_BlenderGym_Benchmarking_Foundational_Model_Systems_for_Graphics_Editing_CVPR_2025_paper.html)
- [3DCodeBench arXiv](https://arxiv.org/abs/2606.01057) · [GitHub](https://github.com/gaoypeng/3dcodebench)
- [Blender 5.0 Python API release notes](https://developer.blender.org/docs/release_notes/5.0/python_api/) · [Blender Python API change log](https://docs.blender.org/api/current/change_log.html)
- [Blender releases](https://www.blender.org/releases/)
- [IJHRSSS journal site](https://ijhrsss.com/) (venue-credibility check)

Project files consulted:

- [computer:///Users/ladvien/mnt/codex_fs/game_assets/projects/scp_characters/CLAUDE.md](computer:///Users/ladvien/mnt/codex_fs/game_assets/projects/scp_characters/CLAUDE.md)
- [computer:///Users/ladvien/mnt/codex_fs/game_assets/projects/scp_characters/docs/literature_review.md](computer:///Users/ladvien/mnt/codex_fs/game_assets/projects/scp_characters/docs/literature_review.md)
- [computer:///Users/ladvien/mnt/codex_fs/game_assets/projects/scp_characters/docs/references.md](computer:///Users/ladvien/mnt/codex_fs/game_assets/projects/scp_characters/docs/references.md)
