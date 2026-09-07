# Work logs for features under development

`docs/worklog/` holds one rolling, time-stamped note per feature or workstream
that is **actively being built**.  It answers "where are we with X right now?"
without making the reader reconstruct the state from session deltas, specs,
and job logs.

## What goes here (and what does not)

| Document type | Lives in | Cadence |
| --- | --- | --- |
| Design, scope decisions, task breakdown | `docs/plans/<FEATURE>_PLAN.md`, `docs/features/` | Rarely changes; edited when the design changes |
| Worker specs | `docs/plans/<feature>-<piece>-spec.md` | Written once, marked completed |
| **Rolling status of an in-flight feature** | **`docs/worklog/<feature>.md`** | Every session that touches the feature |
| Cross-workstream session deltas | `docs/plans/PLAN-session-log.md` | Every session; point at the worklog rather than duplicating it |
| Hand-off sheet | `docs/plans/NEXT_AGENT.md` | Points at active worklogs |

## Conventions

- **One file per feature**, named `<feature>.md` (e.g. `mfs-campaigns.md`).
- The file opens with a short **Current status** block (built / run / pending /
  decisions needed / next actions) that is *rewritten* each time, followed by a
  **Log** of dated entries (`### YYYY-MM-DD` headings, newest first).
- Every claim of "done" for a computation names the evidence: Slurm job id,
  output path, or report file.  Distinguish code landed from data landed.
- Each entry records what changed, what was observed, and any decision taken
  or pending, in that order.  Keep entries factual; design rationale belongs in
  the plan documents.
- **Retirement:** when the feature ships (or is abandoned), move the file with
  `git mv` to `docs/archive/worklog/`, add a final dated entry stating the
  outcome, and update `docs/INDEX.md`.
- **Needs bmason:** anything requiring a decision, review, launch or manual step
  from bmason goes in `docs/ACTION_ITEMS.md` (one row, with a pointer back to the
  worklog); the worklog entry links to it rather than restating the ask.
