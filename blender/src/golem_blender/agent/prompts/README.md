# Prompts

The tunable text of the harness, one file per artifact, so it can be
read, diffed and reviewed as prose instead of as string surgery inside a
module.

| File | What it is |
|---|---|
| `system_prompt.md.j2` | The outer shell. Takes `blender_series`, `working_agreement`, `skills` (empty when no lane is selected), `conventions`, `gate_and_traps`. The manifest's operations section is not rendered (OT-24); the tool schemas carry the ops. |
| `working_agreement_v{n}.md.j2` | Revision `n` of the working agreement — the part the convergence loop tunes. |
| `examiner.md.j2` | What the EYE is asked when comparing a render against its signed-off golden view. Takes `reference_position` (`"first"`/`"second"`, so the same view is examined in both image orders). Closed tag vocabulary, JSON output contract — `../../evaluate/examiner.py` refuses anything else. Its hash is half of `examiner_identity()`, so editing this file invalidates the calibration that licensed machine verdicts. |
| `gradient.md.j2` | ProTeGi's `LLM∇`: given the working agreement and the MEASURED gate failures, name what the text allowed. Takes `body`, `evidence`. Never sees the examiner's tags. |
| `skills/*.md.j2` | One capability module each — the procedural knowledge a LANE needs, kept out of the working agreement because it is dead weight on every turn in another lane. Registry: `../skill_modules.py`. |
| `revise.md.j2` | ProTeGi's `LLM_δ`: return the whole working agreement with exactly ONE contiguous region changed. Takes `body`, `gradient`. |

## Two registries, two disciplines

The working agreement is ONE text, tuned as a monolith, versioned by
revision. A capability module is one of the texts in `SKILL_MODULES`, selected by lane,
versioned by identity. They are separate because they answer different
questions — the agreement says how to work with the user, a module says
how this lane fails — and because a module must be able to not load.

`../skill_modules.py` enforces `MAXIMUM_MODULES_LOADED = 3` and
`MAXIMUM_MODULE_LINES = 60`. Both numbers are measured, not chosen:
2-3 focused modules scored +18.6 pp where 4+ scored +5.9 pp, and compact
modules scored +18.8 pp where "comprehensive" ones scored -2.9 pp
(`10.48550/arXiv.2602.12670`). A lane wanting a fourth module, or a
module past sixty lines, is a red test.

No lane loads by default. `build_system_prompt()` with no arguments
renders exactly the pinned revision and no skill, so every score already
attributed to that text keeps meaning what it meant. Adding a module to
a default is a change to the prompt and needs a convergence run, not a
commit.

## Adding a module

1. Write `skills/{name}.md.j2`, compact, no Jinja delimiters.
2. Register a `SkillModule` with its `subsystem`, `purpose`,
   `hypothesis` — stated before the run — and the `evidence` DOIs a
   later reader needs to challenge it.
3. Put it in a lane. Lane selections DISPLACE; they do not add. If it
   does not displace anything, it is not needed.
4. Score it, fill `outcome` from the measurement. A module measuring
   negative is removed, not tuned — 16 of 84 SkillsBench tasks got worse
   with skills, worst case -39.3 pp.

## The split

These files hold the **text**. `../prompt_versions.py` holds the
**provenance**: which revisions exist, the one element each changed, the
hypothesis stated before it ran, and the outcome measured after. A file
cannot carry why it exists; the registry cannot be read as prose. Both
are needed, so both exist. `validate_revisions()` checks every registered
revision renders, and `test_every_registered_revision_has_a_template`
checks no template on disk is unregistered.

`../prompt_templates.py` renders them. Nothing else reads these files;
`../prompt_search.py` writes new revisions.

## Adding a revision

1. Copy the current revision to `working_agreement_v{n+1}.md.j2` and
   change **exactly one element**. Surgical edits beat rewrites (LL3M),
   and a rewrite destroys the attribution that makes the next edit
   informed.
2. Add a `PromptRevision` to `PROMPT_REVISIONS` with `changed_element`
   and `hypothesis` — the hypothesis is written **before** the run, in
   the form "changed X because Y; expect Z".
3. Run it: `make converge BRIEF=... REVISION={n+1} ITERATION=...`.
   Fill `outcome` from the measurement, not from impression.
4. Move `PINNED_PROMPT_REVISION` (`ACTIVE_PROMPT_REVISION` follows it) only once the measurement supports it, through `make pin REVISION={n+1}` — the one human act.

`validate_revisions()` enforces the parts of that a reader would
otherwise have to take on trust: revisions consecutive from 1, every
template rendering non-empty, every revision differing from its
predecessor by exactly one contiguous hunk and by *something*, every
revision carrying a hypothesis, and every superseded revision recording
what it measured.

## Constraints

- **No Jinja delimiters in a body.** `{{ }}`, `{% %}` and `{# #}` would
  be interpreted, and the prompt would quietly lose text. Asserted in
  `tests/pure/test_prompt_templates.py`.
- **Whitespace is content.** Bullet indentation, blank lines between
  paragraphs and the trailing newline are all part of the text, and the
  revision's identity is a hash of it. The environment is configured
  with `keep_trailing_newline=True` and no block trimming for exactly
  this reason.
- **Undefined variables raise.** A prompt with a silently blank section
  still runs — the agent just never learns the thing that section
  existed to tell it.
