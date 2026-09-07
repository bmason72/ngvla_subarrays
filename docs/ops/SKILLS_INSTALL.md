# Installing the ALMA, radio-analyst, and ngvla-imaging skills

This is a reference for bmason to install three things into Claude Code and
Codex on this machine: the `working-with-alma-data` knowledge skill at
`~/Code/skills/alma-data-skill/`, the `radio-analyst` Claude Code plugin (MCP
servers plus skills) at `~/Code/skills/radio-analyst/`, and this repo's own
`ngvla-imaging` skill, currently drafted at `skills/ngvla-imaging/` in this
repository. Nothing here has been installed by an agent; every command below
is meant to be pasted and run by bmason himself. Re-check the paths below with
`ls` before trusting them, since they were verified on 7 Sep 2026.

## Claude Code

### ALMA and ngvla-imaging skills (personal scope)

Both are pure knowledge skills with no MCP servers, and both are useful across
projects, not just this repo, so personal scope (`~/.claude/skills/`) fits
better than project scope. `~/.claude/skills/` does not exist yet on this
machine. Symlinking rather than copying means a `git pull` in `~/Code/skills`
or in this repo updates the installed skill immediately. The ALMA skill's
`review/` directory and its own local `.git` come along harmlessly inside the
symlinked directory; they do not interfere with skill loading.

```bash
mkdir -p ~/.claude/skills
ln -s ~/Code/skills/alma-data-skill ~/.claude/skills/working-with-alma-data
ln -s ~/Code/ngvla_subarrays/skills/ngvla-imaging ~/.claude/skills/ngvla-imaging
```

To verify, start `claude` in any directory, type `/` and look for the skill
in the list, or just ask Claude "which skills are available" and check that
both names appear.

### radio-analyst (plugin)

This one is a full Claude Code plugin: three stdio MCP servers
(`ms-inspect`, `ms-modify`, `ms-create`, launched via `bin/serve*.sh`) plus
two skills and several slash commands. The servers need a Python 3.12
environment with `casatools`/`casatasks` on the path; the project's own dev
workflow assumes `pixi`, which is not installed on this machine yet.

The marketplace route, exactly as given in the project's own README:

```bash
# Register the marketplace (once per machine)
claude plugin marketplace add https://github.com/skunkworks-ra/radio-analyst

# Install the plugin
claude plugin install radio-analyst@radio-analyst
```

The README documents casatools installing automatically on first use
(about 500 MB) when installed this way; where that first-use install lands
on disk is unverified, so watch quota if it lands under `$HOME`.

For a local install instead of pulling from GitHub, the same subcommand
takes a local path:

```bash
claude plugin marketplace add ~/Code/skills/radio-analyst
claude plugin install radio-analyst@radio-analyst
```

If that local marketplace route does not resolve the plugin, the fallback is
a session-scoped flag rather than a persistent install:

```bash
claude --plugin-dir ~/Code/skills/radio-analyst
```

The README's own local-development path uses `pixi` directly and bypasses
the plugin system entirely (`pixi install`, `pixi run pip install casatools
casatasks`, `pixi run install-mcp`, which calls `bin/install-local.sh` to
register the three MCP servers directly). That path is documented here for
completeness but is a `pixi`-based alternative to the plugin route above, not
something to run alongside it.

Verify with:

```bash
claude plugin list
claude mcp list
```

## Codex

### ALMA and ngvla-imaging skills

Codex CLI 0.153.4 has native skill support at `~/.codex/skills/<name>/SKILL.md`
(system skills already live under `~/.codex/skills/.system/`, including
`skill-installer` and `skill-creator`, and `codex features list` shows
`skill_search` as stable). The ALMA skill ships an `agents/openai.yaml` with
Codex-facing display metadata, so it was written with Codex in mind.

```bash
mkdir -p ~/.codex/skills
ln -s ~/Code/skills/alma-data-skill ~/.codex/skills/working-with-alma-data
ln -s ~/Code/ngvla_subarrays/skills/ngvla-imaging ~/.codex/skills/ngvla-imaging
```

Verification: unverified. There is no confirmed CLI command observed on this
machine that lists installed native skills by name; the most direct check is
to start a Codex session and ask it to use the `working-with-alma-data` skill
(or `ngvla-imaging`) and see whether it picks it up, or to look for a
skill-listing surface once one is confirmed to exist.

### radio-analyst

`codex plugin marketplace add` accepts a local path, an `owner/repo[@ref]`,
or a Git URL, and `codex plugin add <plugin@marketplace>` installs from it.
Whether the project's `marketplace.json` (written for Claude Code's schema)
is also compatible with Codex's plugin format is unverified; try it first:

```bash
codex plugin marketplace add ~/Code/skills/radio-analyst
codex plugin add radio-analyst@radio-analyst
```

If that fails, register the three MCP servers directly with `codex mcp add`.
Based on `codex mcp add --help`, the syntax is `codex mcp add <NAME> -- <COMMAND>...`:

```bash
codex mcp add ms-inspect -- bash ~/Code/skills/radio-analyst/bin/serve.sh
codex mcp add ms-modify -- bash ~/Code/skills/radio-analyst/bin/serve-modify.sh
codex mcp add ms-create -- bash ~/Code/skills/radio-analyst/bin/serve-create.sh
```

`~/.codex/config.toml` has no `[mcp_servers]` section today, so this would be
a fresh registration. The plugin's two skills (`radio-interferometry` and
`ms-simulator`) can also be symlinked into Codex's native skill directory
independent of the MCP registration:

```bash
ln -s ~/Code/skills/radio-analyst/.claude/skills/radio-interferometry ~/.codex/skills/radio-interferometry
ln -s ~/Code/skills/radio-analyst/.claude/skills/ms-simulator ~/.codex/skills/ms-simulator
```

## Uninstall / update

```bash
# Claude Code personal skills (ALMA, ngvla-imaging)
rm ~/.claude/skills/working-with-alma-data ~/.claude/skills/ngvla-imaging

# Claude Code plugin
claude plugin uninstall radio-analyst@radio-analyst

# Codex native skills
rm ~/.codex/skills/working-with-alma-data ~/.codex/skills/ngvla-imaging
rm ~/.codex/skills/radio-interferometry ~/.codex/skills/ms-simulator

# Codex MCP servers (if registered via codex mcp add)
codex mcp remove ms-inspect
codex mcp remove ms-modify
codex mcp remove ms-create

# Codex plugin (if the marketplace route worked)
codex plugin remove radio-analyst@radio-analyst
```

Because the skills are symlinks, updating either source repo
(`~/Code/skills/alma-data-skill`, `~/Code/skills/radio-analyst`, or this
repo's `skills/ngvla-imaging`) with `git pull` updates the installed skill
automatically; no reinstall step is needed for content changes.

## What is intentionally not done here

- No agent installed anything in this pass; every command above is meant to
  be run by bmason directly, and none of the state-changing commands above
  were executed while writing this document.
- The choice of Python environment for `casatools`/`casatasks` (plugin
  auto-install vs. `pixi` vs. reusing the existing
  `/work2/10240/bmason72/stampede3/casaenv` CASA install) is left to bmason;
  none of the three MCP servers were started or tested here. Where a fresh
  `pixi` environment would be created by default, and how to redirect it off
  `$HOME` (which has a 14 GB quota) onto `$WORK`, is unverified without
  `pixi` on PATH to check against its own documentation.
- The stray empty directory `~/Code/skills/mkdir` was not touched; it looks
  like a leftover from a copy-paste error and is safe to remove
  (`rmdir ~/Code/skills/mkdir`) whenever convenient.
