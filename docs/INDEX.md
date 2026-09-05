# Documentation index

Reorganized 2026-09-05: files moved with `git mv`, and `PLAN.md` was split into
fragments carrying `split_from:` provenance frontmatter — use `git log --follow`
on any path below to see its full history.

| Path | Category | Description |
| --- | --- | --- |
| [../CLAUDE.md](../CLAUDE.md) | root | Task statement and repo map for coding agents. |
| [../README.md](../README.md) | root | Project overview, release scope, and start-here pointers. |
| [ops/casaLocation.md](ops/casaLocation.md) | ops | CASA environment on TACC Stampede3 (the `casapy` wrapper). |
| [ops/RUN_CAMPAIGNS.md](ops/RUN_CAMPAIGNS.md) | ops | Slurm campaign run sheet (copy-paste commands). |
| [ops/POLISH_AND_STORAGE.md](ops/POLISH_AND_STORAGE.md) | ops | Polish sampling and `$SCRATCH`/`$WORK` storage conventions. |
| [plans/RELEASE_PLAN.md](plans/RELEASE_PLAN.md) | plans | Current MVP release plan (live). |
| [plans/WRAPUP.md](plans/WRAPUP.md) | plans | bmason's high-level release-scope instructions. |
| [plans/NEXT_AGENT.md](plans/NEXT_AGENT.md) | plans | Hand-off sheet for whoever picks this up next. |
| [plans/PLAN.md](plans/PLAN.md) | plans | Living plan: status, decisions, gotchas; now split into fragments. |
| [plans/PLAN-session-log.md](plans/PLAN-session-log.md) | plans | Session log fragment split from `PLAN.md` (lines 483-988). |
| [plans/MFS_CAMPAIGN_PLAN.md](plans/MFS_CAMPAIGN_PLAN.md) | plans | MFS broadband continuum campaigns — plan summary. |
| [plans/mfs-campaigns-detail.md](plans/mfs-campaigns-detail.md) | plans | MFS campaign detail fragment split from `PLAN.md` (lines 1083-1324). |
| [features/MFS2_ADAPTIVE_SAMPLER_SPEC.md](features/MFS2_ADAPTIVE_SAMPLER_SPEC.md) | features | MFS-2 adaptive sampler design spec (build contract). |
| [architecture/PSF_DIAGNOSTICS.md](architecture/PSF_DIAGNOSTICS.md) | architecture | How the curve reports measure and present PSF quality. |
| [architecture/ETA_JUMPS.md](architecture/ETA_JUMPS.md) | architecture | Why large eta jumps occur in the curves. |
| [architecture/mstroh_comparison.md](architecture/mstroh_comparison.md) | architecture | Comparison of the Stroh taper-simulation package vs. `curvegen`. |
| [architecture/selection-tool-design.md](architecture/selection-tool-design.md) | architecture | Selection-tool design fragment split from `PLAN.md` (lines 14-208). |
| [postmortems/2026-07-06-curve-anomaly.md](postmortems/2026-07-06-curve-anomaly.md) | postmortems | Diagnosis of pop-ups/drop-outs in the taperability/sculptability curves. |
| [archive/plans/plan-session-log-2026-07.md](archive/plans/plan-session-log-2026-07.md) | archive/plans | Session-log fragment split from `PLAN.md` (lines 226-482, 1447-1591). |
| [archive/plans/2026-07-08-next-steps-roadmap.md](archive/plans/2026-07-08-next-steps-roadmap.md) | archive/plans | Roadmap fragment split from `PLAN.md` (lines 1325-1446). |
| [archive/plans/CALCULATOR_FEATURE_PLAN.md](archive/plans/CALCULATOR_FEATURE_PLAN.md) | archive/plans | Calculator ranking, controls, and portability plan (implemented). |
| [archive/plans/CALCULATOR_FEATURE_PLAN_REVIEW.md](archive/plans/CALCULATOR_FEATURE_PLAN_REVIEW.md) | archive/plans | Review of `CALCULATOR_FEATURE_PLAN.md`. |
| [archive/plans/campaign_proposal_revd_snapshot.md](archive/plans/campaign_proposal_revd_snapshot.md) | archive/plans | Rev D subarrays + snapshot sims campaign proposal. |
| [archive/plans/campaign_revd_snapshot_handoff.md](archive/plans/campaign_revd_snapshot_handoff.md) | archive/plans | Rev D + snapshot campaign implementation hand-off. |
| [archive/plans/NEXT_AGENT_old.md](archive/plans/NEXT_AGENT_old.md) | archive/plans | Superseded kickoff prompt; not current. |
| [archive/plans/PSF_PLOT_FIX_HANDOFF.md](archive/plans/PSF_PLOT_FIX_HANDOFF.md) | archive/plans | PSF plot repair hand-off and completion spec. |
| [archive/plans/PSF_REPORT_FIX_PLAN.md](archive/plans/PSF_REPORT_FIX_PLAN.md) | archive/plans | Agreed PSF report fix plan (completed). |
| [archive/features/psf-inspector-plan.md](archive/features/psf-inspector-plan.md) | archive/features | PSF inspector feature plan fragment split from `PLAN.md` (lines 989-1082). |
| [_needs-triage/futureDev.md](_needs-triage/futureDev.md) | needs-triage | Work plan and feature backlog notes, not yet filed. |

## Root files

`AGENT_WORKFLOW_RECOMMENDATIONS.md` and `BIDIRECTIONAL_AGENT_BRIDGE_SPEC.md` are
untracked working notes about agent tooling. They are left in the repo root and
have not yet been filed into `docs/`.
