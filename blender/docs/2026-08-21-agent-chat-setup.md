# Chatting with the agent inside Blender

> **SUPERSEDED 2026-09-26 (MCP cutover).** The in-Blender chat panel this
> guide sets up (`blender_addon/`, `scripts/package_addon.py`) was deleted;
> the client is now Claude Code over the `blended` MCP server — see
> README.md "Chat (Claude Code over MCP)". The model notes below still
> describe the headless `AgentSession` lanes (`make chat-e2e`, the bench).

## 1. Pick a model

The agent's job is: write `bpy` Python, call tools, read measured gate
reports, and *look* at contact sheets. The analyzer is the hard gate, so
vision is advisory — but a stronger VLM still catches wrong-object
failures the gate cannot (measured here: a planter that passed every
structural check with its drainage hole sealed shut).

**Billing matters, and the model pages tell you which side you're on:**
a *usage-level label* (Low/Medium/High Usage) means the model is covered
by your subscription and draws on session and weekly limits; *per-token
dollar pricing* means it is metered and billed on top.

| Use | Model | Tier | Notes |
|---|---|---|---|
| **Default (writer AND eye)** | `claude-code:sonnet` | **Claude subscription — no API key** | Runs through the signed-in Claude Code CLI, so this harness never handles a token. Natively multimodal, and picking it for BOTH slots means the writer looks at its own renders as real image blocks — no second model call, nothing lost to a prose summary. Qualified on the five-brief suite 2026-09-05 (5/5 deterministic gates, first attempt) and licensed as examiner on the fixture zoo (sensitivity 0.80, control specificity 1.00). Rate-limited by the 5h/7d windows rather than metered. |
| Superseded default | `minimax-m3:cloud` | High Usage — subscription | **Do not use as the eye.** Measured 2026-08-24: it answers in `message.thinking` and returns empty `content`, so every examiner call fails the JSON contract. |
| Snappier | `kimi-k2.7-code:cloud` | High Usage — subscription | Coding-tuned, ~30% fewer thinking tokens. Lighter on your weekly limit, some capability cost. |
| Lightest | `qwen3.5:397b-cloud` | Medium Usage — subscription | Cheapest against your limits. Vision + tools, 256K context. |
| Strongest overall | `kimi-k3:cloud` | **METERED — $3/$15 per 1M** | 2.81T params, text/image/video, the best VLM on the platform. Billed *separately* from your subscription — opt in deliberately. *22|| Local | `qwen3.8-27b` on bmb | — | Writer AND eye on bmb's llama-swap (OpenAI protocol at 192.168.1.233:9292). No cloud usage. |

Ruled out despite strong coding: `glm-5.2`, `deepseek-v4-pro`,
`minimax-m2.7`, `nemotron-3-*`, `gpt-oss` — **no vision**, so the agent
cannot look at its own work.

### Auth

With a subscription the simplest path needs no key handling at all:

```sh
ollama signin      # authenticates the local daemon
ollama serve
```

The local daemon then proxies `:cloud` models, so the addon points at
`http://localhost:11434` and everything works.

`OLLAMA_API_KEY` is read from the environment as a fallback, and the
addon will fall back to `https://ollama.com` directly if the daemon is
unreachable. **macOS trap:** Blender launched from Finder does *not*
inherit your shell environment, so `OLLAMA_API_KEY` is invisible to it
even though `echo $OLLAMA_API_KEY` works in a terminal. Either use
`ollama signin` (recommended), launch Blender from a terminal, or paste
the key into the addon preferences.

## 2. Install the addon

Blender → Edit → Preferences → Add-ons → Install… → pick
`blender_addon/__init__.py`, enable **"blended: Agent Chat"**.

In its preferences set:

- **blended repository** — the repo root (the folder containing `src/`)
- **Model** — pick from the dropdown; it shows the billing tier for each
- **Endpoint** — leave at `http://localhost:11434`
- **API key** — leave empty if you ran `ollama signin`

Click **Test Connection**. It reports which route worked (local daemon
vs direct cloud) and names the failure precisely if not.

## 3. Chat

Press **N** in the 3D viewport, open the **blended** tab. Type and Send.

Try: *"Build me a wooden crate, about 0.8 m, and show me the renders."*

## What you'll see

The transcript shows each step: the agent's thinking, each tool call,
the measured result, then its answer. The tools it has:

| Tool | What it does |
|---|---|
| `run_python` | Runs a chunk, then **gates** the named object. Its primary tool. |
| `inspect_object` | Re-measures an existing object without rebuilding. |
| `render_views` | Four-view contact sheet, returned as an image it can see. X-ray optional. |
| `search_ops` | Finds operations by keyword instead of guessing signatures. |
| `list_scene` | Bounded scene listing. |
| `export_asset` | Exports `.glb` and verifies by re-importing. |

## How it stays responsive

`bpy` is not thread-safe, but model calls block for seconds to minutes.
So the model call runs on a background thread, and **every tool call
that touches `bpy` is marshalled back to the main thread** via
`bpy.app.timers`. Nothing touches Blender off-thread; the UI never
freezes.

## What it will and won't do

It will refuse to call something finished because the render looks
good — the system prompt makes the ordering explicit: executed → passed
the gate → looks right, and all three are required. It reports
measurements rather than impressions, and escalates to you after three
honest failed attempts rather than looping.

The known limit: **the gate certifies structure, not intent.** A mesh
can be perfectly manifold and still be the wrong object — measured
here: a planter that passed every structural check with its drainage
hole sealed shut. That third check is yours and the agent's, from the
renders. Which is exactly why `render_views` exists and why the prompt
insists on it.


---

## Developing the library without restarting Blender

Blender caches every import in `sys.modules`, so editing
`blended/ops/primitives.py` and running again silently gets you the OLD
code. Blender's own "Reload Scripts" does not help — it reloads
registered addons, not a package sitting on `sys.path` — and neither
does disabling and re-enabling the addon, because the submodules
survive in the cache.

### Setup

1. Clone the repo somewhere you'll edit it.
2. Install the addon **either** way — packaged zip or by pointing
   Blender at `blender_addon/__init__.py`.
3. In addon preferences, tick **Developer mode** and set **blended
   repository** to your repo root.
4. Leave **Auto-reload on file change** on.

In developer mode the repository sources are placed *first* on
`sys.path`, so they win over the vendored copy inside a packaged
install. You can develop against a zip-installed plugin without
reinstalling it.

### How it behaves

Save a file → within a second the panel logs
`Reloaded 12 modules; changed: ops/primitives.py`. The next thing the
agent does uses your new code.

- **Your conversation is preserved.** The session object holds
  instances of the old classes so it is rebuilt, but the messages are
  plain dicts and carry across. You can fix an op mid-conversation and
  keep going.
- **The system prompt is regenerated**, so edits to
  `agent/system_prompt.py` or to the manifest take effect on reload
  too.
- **It never fires mid-turn.** Purging modules while the worker thread
  is executing library code would pull the floor out from under it, so
  auto-reload is skipped while the agent is working and resumes after.
- **Manual reload** is the **Reload** button in the panel (developer
  mode only), or turn auto-reload off and use it exclusively.

### What still needs a restart

Only the addon's own `__init__.py` — operators, panels and preferences
are registered Blender classes, and re-registering them live is not
worth the fragility. Everything under `src/blended/` hot-reloads: ops,
builders, the analyzer, capture, the agent loop, the system prompt, the
tool surface, the drift catalog.

So the loop is: edit ops and prompts freely with Blender open; restart
only when you change the panel UI itself.
