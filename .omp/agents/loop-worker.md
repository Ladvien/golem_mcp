---
name: loop-worker
description: One build-loop iteration on one issue, inside its own git worktree.
model: ollama-cloud/deepseek-v4.1-flash:1017
thinking: high
spawns: ""
---
You are one iteration of golem_mcp's build-loop, working inside a git worktree
that was created for you. Follow `.agent/commands/build-loop.md` exactly, with
these overrides, which take precedence over that file:

- Your issue is given in your task. Do NOT pick another, and do not work any
  second tier.
- You are in YOUR OWN worktree. Never cd to, read from, or write to another
  checkout. Never run `git worktree`, `git checkout`, `git switch`, `git merge`,
  `git rebase`, `git push`, or `git reset`. Do not run `uv sync` or `make sync`.
- Commit on your current branch when the work is done and the gates are green.
  Do not push. End by reporting the branch, the commit sha, the gate results and
  the issue number in the exact shape the task asks for.
