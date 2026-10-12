# Home-Still Corpus Catalog for `blended` — 2026-08-22

**Method:** 10 semantic searches over `distill_search` (bge-m3, 9,481 docs) on the project's
active themes + `catalog_recent` for new arrivals + re-verified the 08-20 evidence doc's
inventory. Home-still healthy: scribe idle 12/12, distill on CUDA (RTX 3090), no in-flight
conversions. Every DOI below was confirmed present in the local corpus this run.

Two classes of item: **[A] actionable this phase** — papers whose results should change
code or prompt before v7 converges; **[B] design grounding** — the evidence base the
existing architecture already rests on.

---

## 1. Directly actionable for the current phase (convergence loop, v7/v8)

### 1.1 Reference-guided visual verification — the golden-snapshot critique pattern
**`10.48550/arXiv.2604.11082`** — RESP: Reference-guided Sequential Prompting for Visual
Glitch Detection in Video Games (Yu et al., 2026; Univ. Alberta + Sony Interactive).

The single most valuable find this run. RESP frames glitch detection as **within-video
comparison against a reference frame**, and measures what supplying a reference does to
VLM judgement on five glitch classes (missing object, clipping, floating, corrupted
texture, lighting):

| Strategy | Acc | F1 | Precision | Recall |
|---|---|---|---|---|
| Oracle reference | 0.73 | **0.74** | 0.72 | **0.76** |
| LastCleanFrame (auto) | 0.70 | 0.69 | 0.70 | 0.69 |
| NoRef (isolated frame) | 0.62 | **0.42** | 0.88 | 0.28 |

Reference guidance is worth **+0.32 F1 / +0.12 accuracy**, mostly by fixing the recall
collapse — a NoRef VLM with high precision and 0.28 recall is exactly the "biased toward
accepting" rubber stamp the convergence plan already names as the eye's failure mode.
Category-wise, reference helps lighting/floating/clipping/missing-object in 5/5 models.

Consequence for `blended`:
- The golden-snapshot half of design commitment 15 ("sign-off stores render, parameter
  snapshot, and regression test; harness detects drift") is not just a regression tool —
  feeding the signed-off golden render as a **reference image paired with the new render**
  in the same vision call is the measured way to make the eye see drift at all.
- Auto-selection matters too: LastCleanFrame ≈ oracle. The harness already appends
  renders to a per-iteration directory; the previous clean contact sheet is the natural
  reference candidate.
- Expected resistances: RESP is video-frame QA (same scene, viewpoint drift), ours is
  static-render regression (identical camera). Should be *easier* — matched reference,
  no viewpoint change. Worth a guard/test rather than a prompt tweak.

### 1.2 Closed-tag vocabulary for the critique prompt

**`10.48550/arXiv.2605.28763`** — CubePart: An Open-Vocabulary Part-Controllable 3D
Generator (Zhu et al., 2026; Roblox). Already in corpus (listed in the 08-20 doc §4.3).

The quality-filtering stage uses a VLM prompt with a **fixed 15-tag vocabulary, explicit
"do not invent or infer new tags", JSON array output, mandatory reasoning field, and a
conservative tie-break rule** ("If borderline, assign the lower score"). That exact
structure is a recipe for the harness's critique instrument: closed answer space prevents
the eye from inventing problems (or rubber-stamping), and forces the reasoning that the
writer needs to act on. Currently `VISION_DESCRIBE_PROMPT` is open-ended — "describe what
you see" — which is right for *reporting* but there is no measured floor that the report
is complete. If a bounded response format is ever layered on, copy this shape.

### 1.3 The critic/verifier split, with the measured failure it fixes

**`10.48550/arXiv.2508.08228`** — LL3M (Lu et al., 2025). Already in corpus, cited in
§1.1/§4.1 of the 08-20 doc.

The section 3.2 "auto-refinement" mechanism is exactly the plan's 1.6 (split critic from
verifier) and worth re-reading against the current code: critic renders m images, VLM
suggests fixes; coding agent edits **the existing script** (their Fig. 17 ablation shows
rewriting from scratch produces a *different* asset — feeding prior code is what makes
edits local); a separate verification agent re-renders, pairs with the critic's images
and critiques, and checks each fix item-by-item (their Fig. 23: "cap attached? Partially
— move down z"). The "Partially" outcome → second coding iteration is the loop's
termination device.
Also: **BlenderRAG** retrieval is error-driven too — the retrieval agent receives the
error message and looks up the fix (e.g. `Specular` → `Specular IOR Level` in 4.x). The
harness's `drift/catalog.py` is the same idea; LL3M shows it working at scale (per-subtask
lookups, not just once).

### 1.4 BlenderGym's measured verifier facts (and the repeat-vote trick)

**`10.48550/arXiv.2504.01786`** — BlenderGym (Gu et al., 2025). In corpus (08-20 doc).

Verified claims for the eye:
- VLM verifier-human alignment: best (Claude 3.5 Sonnet) 0.66 vs inter-human 0.79.
- Some VLMs develop fixed position bias (Qwen "consistently favors the second edit").
- **Algorithm 1 (Scaled Verification)**: shuffle the candidates, select k times, feed the
  k winners through one final selection. Cheap ensemble against per-call bias — a
  candidate for the eye when it gates.
- Camera views: a "comprehensive view" (elevated, sees all objects) plus detail views,
  with all objects-of-interest guaranteed present in at least one *input* view — the
  contact-sheet layout rationale is evidence-based, not taste.

### 1.5 Self-verification is the biggest single lever — measured

**`10.48550/arXiv.2305.16291`** — Voyager (Wang et al., 2023). In corpus.

Ablation: removing self-verification costs **−73% discovered items** — the largest of all
six components (curriculum −93%, skill library plateau, execution errors, environment
feedback, GPT-3.5 swap). One-line support for the harness's hard-gate philosophy and for
the plan's rubric 3a (never spend visual tokens on a scene that failed bounds). The skill
library, where programs are committed only after a self-verifier confirms task success,
is also the direct antecedent of the in-package ops library + mistake memory.

### 1.6 Survey-grade prompt optimization — for the ADJUST step

In corpus: **`10.48550/arXiv.2406.06608`** (Prompt Report), **`10.48550/arXiv.2310.14735`**
(Unleashing the Potential of Prompt Engineering), **`10.48550/arXiv.2107.13586`**
(Pre-train, Prompt, Predict). The Prompt Report's §2.4 is the taxonomy the convergence
plan's ADJUST step is implicitly doing manually: start state, scoring metric, expansion
method, beam width. The plan edits exactly one contiguous hunk per revision
(`changed_hunks()`); the survey's APE/ProTeGi (textual gradients: "describe the flaw,
generate fixes, bandit-select") is the automated version — the loop is close to being
able to *suggest* the hunk, not just score it. Also the survey's field note:
"prompt engineering is cajoling, not programming" + sensitivity to detail without
obvious reason — which is why the plan is right to gate convergence on 3 clean runs
rather than one.

### 1.7 Mistake-memory and skill-library evidence

In corpus: **`10.48550/arXiv.2404.13501`** (Survey on the Memory Mechanism of LLM agents,
2024) — the cross-trial-memory taxonomy (Reflexion verbal RL, ExpeL failed-vs-successful
trajectory comparison, Voyager) is the theoretical frame for `evaluate/mistake_memory.py`:
what to store (failure → cause → fix → guarding assertion) is the procedural-memory
shape from CoALA **`10.48550/arXiv.2309.02427`** (in corpus): "reflect on experiences to
generate semantic knowledge; gradually create procedural knowledge in the form of a code
library storing useful methods." The harness already does this — the catalog's point is
only that the design is the literature's consensus shape, and that both sources state the
open problem the plan's rubric cares about: **stale memory dominates** (write-policy,
provenance, verification — from `10.48550/arXiv.2601.01743` §7.2, AI Agent Systems
survey, in corpus). The mistake log needs a "last used / confirmed" marker or it will
eventually steer with outdated API fixes.

---

## 2. Design grounding already in the evidence base (verified present)

Existing doc §4 lists these; all verified present via search this run.

**ACI / tool surface:** SWE-agent `2405.15793`, Agentless `2407.01489`, LLM-based Agents
for SE survey `2409.02977` (incl. feedback taxonomy, cascading-error analysis — good for
the harness-critique classification), Live-SWE-agent `2511.13646` (runtime tool creation),
MCP-tools study, AgentBench, Gorilla, Toolformer, OSWorld, WebArena, VisualWebArena,
Design2Code, Sketch2Code, PPTAgent.

**Executability / drift:** LLMs Cannot Self-Correct Reasoning Yet `2310.01798`,
Self-Refine `2303.17651`, CodeAct `2402.01030`, BlenderLLM `2412.14203` (domain-tuned,
drift-immune), CADCodeVerify, the drift-catalog/BlenderRAG mechanism (§1.3).

**The gate / analyzer:** Polygon Mesh Repairing `10.1145/2431211.2431214` (the defect
taxonomy — designed meshes → non-manifoldness/gaps/self-intersections; the current check
list), Garland-Heckbert QEM `10.1145/258734.258849` (acquisition), QuadriFlow
`10.1111/cgf.13498` (acquisition), Attene — plus in-corpus metrics framework
**`10.1109/TPAMI.2024.3398998`** (Fukaya et al.) which organizes artifact-validity vs
artifact-quality vs operation metrics and notes exactly the harness's hardest case
("automatic characteristic metrics are context-specific; use them alongside human
judgement").

**Procedural / program synthesis antecedents:** Infinigen, DeepCAD, ABC, ShapeAssembly,
CSGNet, ProcTHOR, model synthesis, the two L-systems papers — the vocabulary
`ops/` generalizes from.

**Generation side (context, not this harness):** TRELLIS, MeshAnything, SATO, etc. — the
doc's §2 "generate vs. program" decision.

**Agentic 3D cluster:** 3DCodeBench `2606.01057`, Planner-Actor-Critic `2601.05016`,
ShapeCraft `2510.17603`, BlenderGym, LL3M, SimWorlds, Embodied CAD, AgentsCAD,
B-repLer, Thinking in Blender, plus the three low-credibility-venue items already flagged
in §2.3/§7 of the 08-20 doc.

---

## 3. Gaps — present in the corpus but not yet turned into design

- **RESP (1.1)** is the only reference-guidance paper found; no golden-render literature
  in corpus. The golden-contact-sheet design has no direct precedent — don't over-cite,
  build it on RESP + the plan's own.
- **No paper measures an agentic DCC harness end-to-end for game-ready output** (the
  predacious-venue gap, doc §2.3). Nothing new landed this run to fill it.
- **ProTeGi / APE (1.6)** are in corpus only as surveys; the *methods* themselves
  (textual gradients) are not downloaded. If Phase 2's ADJUST ever goes automated,
  `paper_download` those two.
- **`10.1145/3450626.3459818` Fusion 360 Gallery, `10.1145/258734.258849` QEM,
  `10.1111/cgf.13498` QuadriFlow, `10.1145/3197517.3201337` Fast Winding Numbers** still
  paywalled (doc §6.1) — the retopo/LOD gate's tolerance semantics rest on these.
- **Two corpus defects still open** (doc §7): Pinocchio under the wrong DOI
  (`10.1145/1276377.1276467` vs correct `10.1145/1275808.1276467`); duplicate
  Real-Time_Rendering books. Pipeline drift is 73 vs threshold 3 — the 08-20 run left
  ~70 conversions queued; scribe has since caught up (idle, in-flight 0), drift is
  likely stale metadata rather than stuck conversions, but nothing has reconciled it.

---

## 4. Acquisition recommendations (this phase)

1. `paper_download 10.1145/3708499` — Intelligent Generation of Graphical Game Assets
   systematic review, the companion to TPAMI.3398998. Listed in the 08-20 doc §4.3 but
   unverified this run; download to confirm and convert.
2. If ADJUST automates: ProTeGi — the survey (`2406.06608`) cites it but only the survey
   is in the corpus. Resolve the exact DOI via `paper_get` at download time.
3. Fast Winding Numbers is needed for the winding-count half of `mesh_checks` — the
   volumetric-probe implementation (3 surface crossings) is a poor man's substitution;
   the real algorithm is paywalled.

---

## 5. Bottom line

The corpus already covers every cluster the harness touches. The two items to actually
**read before the next convergence run** are RESP (golden reference is the measured fix
for the eye's blind-spot) and LL3M's §3.2 (the critic/verifier loop with existing-code
reuse — the plan's refinement gate is a close reimplementation of it). Everything else is
grounding the 08-20 doc already carries.
