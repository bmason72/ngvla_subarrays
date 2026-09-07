# Items that need bmason's attention

The one place agents put anything that needs a decision, a review, a launch,
or a manual step from bmason.  Convention: an agent that hits such an item
adds a row here (date raised, what is needed, where the context is) and points
at it from the relevant worklog; when bmason acts, the row moves to "Resolved"
with the decision id used in the worklogs.  Keep rows to two lines.  Newest
open items at the top of each table.

## Open

| # | Raised | Needs from bmason | Context |
| --- | --- | --- | --- |
| A12 | 7 Sep 2026 | Read the open questions in the curve-product design note and answer them before any refactor work is scheduled. | `docs/architecture/curve-product-design.md` "Open questions for bmason" |
| A11 | 7 Sep 2026 | Decide whether to pursue more sweep parallelism (pylauncher) once this run's timing is known. Optional. | wishlist item 3; `docs/worklog/wishlist-consult-2026-09-07.md` |
| A10 | 7 Sep 2026 | Delete (or explain) the stray empty directory `~/Code/skills/mkdir`. | `docs/worklog/mfs-campaigns.md` 7 Sep |
| A9 | 7 Sep 2026 | Two optional pilots proposed by the tclean consult: paired Briggs+taper points at fixed vs grown FOV; a small MT-MFS nterms=2 tt0 subset. Say yes, no, or later. | `docs/worklog/mfs-tclean-consult-2026-09-07.md`; D9 in `docs/worklog/mfs-campaigns.md` |
| A8 | 7 Sep 2026 | Define the LONG combos rule (which short baselines involving LONG are filtered; the old utilities cut at ~150 m). Needed before any LONG subarray is added. | wishlist item 4; `artifacts/saUtil.py` `filter_spurious_shorts` |
| A7 | 7 Sep 2026 | Decide which further campaigns to run after reviewing this one: remaining Rev F MFS subarrays; spiral+5/+10 (mono and/or MFS). | wishlist item 5; `docs/worklog/spiral-plus.md` |
| A6 | 7 Sep 2026 | Review the ngVLA imaging skill draft when it lands (`skills/ngvla-imaging/SKILL.md`). | wishlist item 7 |
| A5 | 7 Sep 2026 | Choose install scope for the ALMA and radio-analyst skills (Claude Code personal vs project; Codex) and run the install commands agents may not run. Instructions: `docs/ops/SKILLS_INSTALL.md` (being written). | wishlist item 8; `~/Code/skills/` |
| A4 | 7 Sep 2026 | Approve merging `feature/curve-limits` then `feature/spiral-plus` into main after the harvest commit. | `docs/plans/NEXT_AGENT.md` "Pending merges" |
| A3 | 7 Sep 2026 | When collect 3475089 finishes: run or delegate the harvest checklist, review the "Rev F — MFS snapshot" report view and the robust-axis behaviour, approve the data commit. Look at the marginal-sampling warning at the coarsest natural taper. | `docs/ops/RUN_CAMPAIGNS.md` top section; `docs/worklog/mfs-campaigns.md` |
| A2 | 18 Aug 2026 | Memo T6: review comments beyond the section 4 paragraph 1 stop marker in `memo/myComments.tex`; then the final editorial pass and release tag. | `docs/plans/RELEASE_PLAN.md` T6 |
| A1 | 7 Sep 2026 | Add rows to `sa_select/data/curve_limits.csv` only when a curve needs a manual valid range (none yet). | `docs/worklog/curve-limits.md` (branch `feature/curve-limits`) |

## Resolved

| # | Raised | Resolved | Decision |
| --- | --- | --- | --- |
| R11 | 7 Sep 2026 | 7 Sep 2026 | spiral+5/+10 antenna selection confirmed as built (D11): nearest core antenna in the tangent plane to each arm's tip, iterated inward. `docs/worklog/spiral-plus.md` |
| R10 | 7 Sep 2026 | 7 Sep 2026 | 27-vs-54 channel confirmation pilot not needed (D10). |
| R9 | 7 Sep 2026 | 7 Sep 2026 | Keep the fixed-imsize image-geometry convention; document it precisely (D9). |
| R8 | 6 Sep 2026 | 7 Sep 2026 | Launcher interface `--mode mfs|1chan`; band key internal. |
| R7 | 6 Sep 2026 | 6 Sep 2026 | Both curves, 7 subarrays, "MFS snapshot" report view, chain with refine, robust step 0.2 (D5 to D8). |
| R6 | 5 Sep 2026 | 6 Sep 2026 | Adaptive sampler parked; Band 4 snapshot only on the full grid; no track run or timing benchmark (D3, D4). |
| R5 | 5 Sep 2026 | 6 Sep 2026 | nchan 32; Band 4 only, other bands scaled (D1, D2). |
