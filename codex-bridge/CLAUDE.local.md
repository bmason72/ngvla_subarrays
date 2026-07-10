## Claude ↔ Codex collaboration

Never use `codex_bridge.sh --full`.

# CLAUDE.md — local working agreement (untracked, local-only)

> This file is intentionally **untracked** (git-ignored). It is build-time guidance
> for Claude Code. do not commit it.

## Claude ↔ Codex collaboration

This repo uses the local **`codex-bridge/`** kit to make Claude and Codex
pressure-test each other's work. **Read and follow `codex-bridge/PROTOCOL.md`**
for all non-trivial work: get an independent second opinion from Codex before
and/or during the work, and have the *other* model review the diff. Drive Codex
hands-off — never make the user copy-paste.

Mode keywords the user appends to a request (Claude maps → `codex_loop.sh`):

| Keyword | Mode |
|---|---|
| `@cx-build` | `--mode build` — Codex implements; Claude reviews the diff |
| `@cx-guard` | `--mode guard` — Claude implements; Codex reviews over threaded rounds |
| `@cx-duel`  | `--mode duel`  — mutual-critique DEBATE loop; both answer + critique each round, converge. Read-only by default; me-driven (default) or `--auto` (needs `--seed`); `--code` to edit (Codex writes in a worktree, Claude reviews) |

Append model / effort / speed after the keyword, e.g.
`@cx-build gpt5.5 xhigh fast` → `--model gpt-5.5 --effort xhigh --fast`
(normalize `gpt5.5`→`gpt-5.5`; effort ∈ low|medium|high|xhigh; `fast` = priority
service tier). No keyword → Claude picks (build for non-trivial, inline for
trivial) and says which. Persist Codex findings; fix or explicitly waive each.

Duel tail words: `auto`→`--auto`, `code`→`--code`, bare integer `N`→`--rounds N`
(default 4 rounds). `@cx-duel` defaults to me-driven + read-only and works for a
plain question (no code needed). `--auto` REQUIRES `--seed <file>` (a context
bundle you write first) so the headless side never starts blind. In `--code`
exactly one model writes (Codex in a worktree); Claude reviews read-only and the
script never auto-merges to main. Effort applies to Codex as given; the Claude
side has no `xhigh` and is clamped to `high`.

```bash
bash codex-bridge/codex_loop.sh --mode build  --test 'cmd' < spec.md
bash codex-bridge/codex_loop.sh --mode guard  --base beta
bash codex-bridge/codex_loop.sh --mode duel   --step init < question.md   # me-driven: then --step codex per round, --step finalize
bash codex-bridge/codex_loop.sh --mode duel   --auto --seed seed.md < question.md   # unattended debate; --teardown cleans up --code runs
```

Artifacts: `tmp/codex/tasks/<id>/`. NEVER let Codex read/print generated files
(`.next/`, compiled CSS) — reason on source only.

## Git

- Default working branch: **`main`**.
- Only commit/push when the user has asked.
- `codex-bridge/`, `tmp/codex/`, and this `CLAUDE.md` are git-ignored — local tooling only.

