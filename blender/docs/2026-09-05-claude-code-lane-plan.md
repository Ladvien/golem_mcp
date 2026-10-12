# Plan — Claude Code headless as a harness connector (writer + eye)

> **PARTLY SUPERSEDED 2026-09-26 (MCP cutover).** Component 3 (the writer and eye dropdowns in `blender_addon/`), verification item 5 (the GUI pass) and fact 8's streaming path were deleted with the in-Blender chat client (`184095f`, `22e1d87`); the lane itself — `claude_code.py`, routing, `provider_smoke.py`, `tests/pure/test_claude_code_lane.py` — remains.

Status: executing. Written before any code, per CLAUDE.md plan-then-execute.

## Why this lane exists

The harness already speaks two wire protocols (Ollama `/api/chat`, OpenAI
`/v1/chat/completions`) over four servers. Claude Code is a *third transport
shape*: a local subprocess that owns its own auth and rate limits. Adding it
buys a strong writer AND a strong native-multimodal eye with no new key and no
new metered balance — which is what makes UI iteration cheap, because the
model side stops being the variable under test.

## Measured facts the design rests on (probed 2026-09-05, CLI 2.1.260)

Every one of these was run against the live binary before the design was fixed.

1. `claude auth status` reports `authMethod: claude.ai`, `apiProvider:
   firstParty`, `subscriptionType: max`. This is the OFFICIAL first-party
   client, not a third-party harness replaying a subscription OAuth token —
   the pattern Anthropic banned for third-party harnesses on 2026-04-04. The
   harness never touches the token; it execs the binary Anthropic ships.
2. `--print --output-format json` answers in 2.4 s; `result` carries the text,
   `is_error` / `subtype` carry the status.
3. `--input-format stream-json` REQUIRES `--output-format stream-json`, which
   in turn REQUIRES `--verbose`. All three or none.
4. Images ride as native Anthropic `image` content blocks inside a stream-json
   user frame. Delivery verified by token accounting, never by a plausible
   reply (the Ollama-lane lesson): 1315 prompt tokens with no image, 1685 with
   one 512-px render, 2068 with two. Two images stay UNFUSED and IN ORDER —
   the qwen-vl `[img]`-placeholder workaround is not needed here.
5. `--json-schema` gives schema-VALIDATED structured output, including `oneOf`
   over per-tool `arguments` schemas. The parsed object arrives in the result
   frame as `structured_output`, so tool calls need no text parsing at all.
   A chat-only turn still answers through the schema with `tool_calls: []`.
6. **Each `{"type":"user"}` frame is one billed turn.** Two user frames in one
   invocation produced two `system init` + two `result` frames. So a stateless
   `chat(messages)` call MUST send exactly one trailing user frame.
7. `{"type":"assistant"}` frames ARE accepted as history: after an injected
   assistant frame naming a fact, the model answered from it.
8. `--include-partial-messages` streams `text_delta` and `thinking_delta`;
   with `--json-schema` the envelope streams as `input_json_delta` on a
   `StructuredOutput` tool_use block.
9. A `rate_limit_event` frame precedes every turn with `five_hour` and
   `seven_day` utilisation and `resetsAt`. Overage is `rejected`
   (`out_of_credits`), so a window hit is a hard stop that must be reported,
   not retried.

## Components

| # | File | Contents |
|---|------|----------|
| 1 | `src/blended/agent/claude_code.py` (new) | `ClaudeCodeTransport` (one class, owns the subprocess) plus pure adapters: binary resolution, message→frame rendering, envelope schema, envelope→assistant dict, rate-limit parsing. |
| 2 | `src/blended/agent/loop.py` | Routing only: `claude-code:` ids imply `CLAUDE_CODE_ENDPOINT`, no API key, own timeout, `chat()`/`check_connection()` delegate to component 1. |
| 3 | `blender_addon/__init__.py` | The ids in the writer and eye dropdowns. |
| 4 | `scripts/provider_smoke.py` | A `claude-code` lane: one text call, one image-in call. |
| 5 | `tests/pure/test_claude_code_lane.py` (new) | Adapters, routing, and a full transport round trip against a FAKE `claude` binary emitting canned stream-json — deterministic, no network, no tokens. |
| 6 | `docs/harness_design.md` | The design decision, DOI-cited, mapped to code. |

## Design decisions

* **Stateless per call, like every other lane.** No `--resume`, no
  `--session-id`. Claude Code's own session store would be a second source of
  truth beside `AgentSession.messages`, which is the canonical record the
  gates, the recorder and the replayer all read. Fact 6 means the whole
  conversation folds into one user frame; fact 7 lets prior assistant turns
  stay assistant turns.
* **The model gets no tools of its own.** `--tools ""` plus `--safe-mode`:
  no Bash, no Read, no CLAUDE.md, no hooks, no MCP. The harness's six tools
  are the only interface, exactly as on every other lane, so a Claude turn
  cannot reach the filesystem behind the builder API.
* **Tool calls are schema-validated, not parsed.** The envelope schema is
  built FROM `TOOL_SCHEMAS`, so a new harness tool needs no lane change —
  descriptions included, because this wire has no `tools` field to carry
  them (see the two findings below).
* **The eye is the same transport.** A `claude-code:` id in `vision_model`
  routes to the same subprocess; images become image blocks. With a
  `claude-code` writer, `vision_model=""` also works — it is natively
  multimodal, so it can look at its own renders.
* **Binary resolution is explicit.** Finder-launched Blender inherits no
  shell `PATH`, the same trap that made `OLLAMA_API_KEY` invisible. Order:
  configured path → `shutil.which` → known install directories → fail loud
  with the install command.

## Verification — results

1. `tests/pure/test_claude_code_lane.py`: 31 passed. Adapters, routing, argv,
   and a full round trip (plus error, timeout, cancel and preflight paths)
   against a stub `claude` binary — no network, no tokens.
2. `scripts/provider_smoke.py --only claude-code`: 2/2. Text `'pong'` in
   1.5 s, image `'Red'` in 1.9 s on `claude-code:haiku`.
3. `make chat-e2e ARGS="--model claude-code:sonnet --vision-model ''"`:
   **6/6 scenarios** in 2 m 53 s — object 1 call, rig 3, weights 5,
   animation 2, material 3, iterative 4. Writer as its own eye.
4. `make test`: pure + in-Blender suites (see the session log).
5. GUI: the ids are in both dropdowns and the binary-path field appears only
   when a `claude-code:` model is selected — awaiting the user's visual pass.

## Two findings that cost a live turn each

Both are recorded in `src/blended/evaluate/mistake_memory.py` with the
assertion that now guards them.

1. **A tool schema without descriptions is a list of names.** The first
   envelope carried each tool's `name` and `parameters` but not its
   `description` — on the HTTP lanes descriptions ride the API's own `tools`
   field, so nothing had ever needed them explicitly. The writer answered
   "I'm unable to create the Crate cube right now" and made zero calls. Fixed
   by carrying `description` into each `oneOf` variant.
2. **An agent CLI reaches for its own tools.** With the schema in place the
   writer still made zero calls, reporting that "every tool call I make
   (run_python, list_scene, search_ops) is being rejected with 'No such tool
   available'": the harness prompt describes the six tools as callable, and
   Claude Code is itself an agent harness, so the model emitted NATIVE
   tool_use blocks that `--tools ""` correctly refused. Fixed by
   `TOOL_PROTOCOL_NOTE`, appended to the system prompt in the same
   `if tools:` branch that adds `--json-schema` — so the schema and the
   instructions for using it can never ship apart.
