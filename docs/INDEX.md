# Documentation index

Reorganized 2026-09-05: files moved with `git mv`, and `PLAN.md` was split into
fragments carrying `split_from:` provenance frontmatter. Use `git log --follow`
on any path below to see its full history.

| Path | Summary | Status |
| --- | --- | --- |
| [GLOSSARY.md](GLOSSARY.md) | One-line definitions of recurring terms (eta, combo, anchor, canonical taper, etc.), each pointing to its defining document | active |
| [../skills/ngvla-imaging/SKILL.md](../skills/ngvla-imaging/SKILL.md) | Reusable Claude Code skill: essential ngVLA imaging-simulation knowledge (configs/subarrays, CASA `sm` simulation, tclean/PSF measurement, taperability/sculpting curves, sensitivity calculator, HPC hygiene) for use in any repo | draft, awaiting bmason review |
| [../CLAUDE.md](../CLAUDE.md) | Task statement, domain concepts, repo map, environment for coding agents | active |
| [ACTION_ITEMS.md](ACTION_ITEMS.md) | The single list of items needing bmason (decision, review, launch); open and resolved | active, check every session |
| [../README.md](../README.md) | Project overview, layout, environment, commands | active |
| [plans/PLAN.md](plans/PLAN.md) | Living plan core: task table, milestones, decisions and open questions, gotchas log | active |
| [plans/baseline-ranking-plan.md](plans/baseline-ranking-plan.md) | Efficient/performance ranking contract, implementation scope, overlap assessment and validation | implemented and validated 10 Sep 2026; user review pending |
| [plans/PLAN-session-log.md](plans/PLAN-session-log.md) | Dated session deltas and hand-off state, 15 Jul to 4 Sep 2026; new deltas append here (split from PLAN.md lines 483-988) | active |
| [plans/mfs-campaigns-detail.md](plans/mfs-campaigns-detail.md) | Long-form MFS broadband continuum campaign design and implementation status (split from PLAN.md lines 1083-1324) | active, in progress |
| [plans/RELEASE_PLAN.md](plans/RELEASE_PLAN.md) | MVP release plan per WRAPUP: scope, T0-T6 task list, progress notes | active, status blocks stopped 18-19 Aug; see docs/worklog/mfs-campaigns.md for current state |
| [plans/WRAPUP.md](plans/WRAPUP.md) | bmason's 17 Aug 2026 release scope and working guidelines; supersedes PLAN.md on conflicts | active, scope authority |
| [plans/NEXT_AGENT.md](plans/NEXT_AGENT.md) | Hand-off sheet: where things stand, immediate queue, working agreements, sharp edges | active, last updated 6 Sep 2026 |
| [plans/MFS_CAMPAIGN_PLAN.md](plans/MFS_CAMPAIGN_PLAN.md) | Summary plan for Ka-band MFS taperability campaigns: scope, assumptions, pilots, task sequence | active, implementation in progress |
| [plans/mfs-imaging-pilot-spec.md](plans/mfs-imaging-pilot-spec.md) | Worker spec for the Band-4 imaging pilot launcher, points generator and nchan-convergence compare (built 5 Sep 2026) | completed, reference |
| [plans/mfs-v1-replay-spec.md](plans/mfs-v1-replay-spec.md) | Worker spec for the MFS-2d V1 retrospective replay harness (built 5 Sep 2026; gate result in the 5 Sep session delta; investigation findings in `curvegen/reports/v1_replay/INVESTIGATION.md`) | completed, reference |
| [features/MFS2_ADAPTIVE_SAMPLER_SPEC.md](features/MFS2_ADAPTIVE_SAMPLER_SPEC.md) | Spec v2.1 for the MFS-2 adaptive (quadtree) sampler: constants, cell lifecycle, validation gates | parked 6 Sep 2026 |
| [worklog/README.md](worklog/README.md) | Convention for rolling, time-stamped status notes on in-flight features | active, convention |
| [worklog/baseline-ranking.md](worklog/baseline-ranking.md) | Efficient/performance implementation, report builds and validation results | implemented locally 10 Sep 2026 |
| [worklog/mfs-campaigns.md](worklog/mfs-campaigns.md) | Rolling status of the MFS broadband continuum campaigns workstream | active, in progress |
| [archive/worklog/README.md](archive/worklog/README.md) | Where retired worklog files land, with retirement convention | active |
| [architecture/selection-tool-design.md](architecture/selection-tool-design.md) | Original design: objective, definitions, two-phase architecture, frequency scaling, selection algorithm (split from PLAN.md lines 14-208) | reference; scope superseded by WRAPUP |
| [architecture/PSF_DIAGNOSTICS.md](architecture/PSF_DIAGNOSTICS.md) | How reports measure and present PSF quality: captures, Gaussian reference, restoring beam, lookup | active |
| [architecture/ETA_JUMPS.md](architecture/ETA_JUMPS.md) | Why eta curves jump: sampling, skirt crossings, interpolation limits; when jumps are real | active |
| [architecture/mstroh_comparison.md](architecture/mstroh_comparison.md) | Validation against Stroh's taper package; sqrt(2) beam-convention finding; what to adopt | active |
| [architecture/curve-product-design.md](architecture/curve-product-design.md) | curveRefactor design note: versioned evaluated-envelope curve product, PSF attachment sizing, single Python/JS evaluation contract, additive migration | design note, 7 Sep 2026, implementation not started |
| [ops/casaLocation.md](ops/casaLocation.md) | TACC Stampede3 CASA: casapy wrapper, quotas, MS and scratch layout | active |
| [ops/SKILLS_INSTALL.md](ops/SKILLS_INSTALL.md) | How to install the ALMA, radio-analyst, and ngvla-imaging skills into Claude Code and Codex on this machine | active |
| [ops/RUN_CAMPAIGNS.md](ops/RUN_CAMPAIGNS.md) | Slurm campaign copy-paste run sheet with live commands and dated wave history | active |
| [ops/POLISH_AND_STORAGE.md](ops/POLISH_AND_STORAGE.md) | How polish refinement samples; what moved from $SCRATCH to $WORK | active |
| [postmortems/2026-07-06-curve-anomaly.md](postmortems/2026-07-06-curve-anomaly.md) | Post-mortem of eta-curve pop-ups and drop-outs: three mechanisms, census, fix plan | completed; fixes landed in the v3 engine |
| [archive/plans/NEXT_AGENT_old.md](archive/plans/NEXT_AGENT_old.md) | Kickoff prompt from a previous dev iteration | superseded |
| [archive/plans/campaign_proposal_revd_snapshot.md](archive/plans/campaign_proposal_revd_snapshot.md) | Proposal for Rev D and snapshot campaigns, approved 10 Jul 2026 | completed |
| [archive/plans/campaign_revd_snapshot_handoff.md](archive/plans/campaign_revd_snapshot_handoff.md) | Implementation hand-off for the (rev, sim_mode) axis, 12 Jul 2026 | completed |
| [archive/plans/CALCULATOR_FEATURE_PLAN.md](archive/plans/CALCULATOR_FEATURE_PLAN.md) | Five-phase calculator feature plan, implemented 21 Aug 2026 | completed |
| [archive/plans/CALCULATOR_FEATURE_PLAN_REVIEW.md](archive/plans/CALCULATOR_FEATURE_PLAN_REVIEW.md) | Critical review of the calculator feature plan | completed |
| [archive/plans/PSF_PLOT_FIX_HANDOFF.md](archive/plans/PSF_PLOT_FIX_HANDOFF.md) | Evidence and checkpoint state for the PSF plot failures, 4 Sep 2026 | superseded |
| [archive/plans/PSF_REPORT_FIX_PLAN.md](archive/plans/PSF_REPORT_FIX_PLAN.md) | Agreed PSF report fix plan, implemented 4 Sep 2026 (commits a7b17f2, 434b24b) | completed |
| [archive/plans/plan-session-log-2026-07.md](archive/plans/plan-session-log-2026-07.md) | July 2026 build sessions, 6 Jul hand-off, M1/M2 implementation decisions (split from PLAN.md lines 226-482 and 1447-1591) | completed |
| [archive/plans/2026-07-08-next-steps-roadmap.md](archive/plans/2026-07-08-next-steps-roadmap.md) | Seven-workstream roadmap from 8 Jul 2026 (split from PLAN.md lines 1325-1446) | completed; multi-node campaign deferred |
| [archive/features/psf-inspector-plan.md](archive/features/psf-inspector-plan.md) | PSF inspector plan; P1-P4 built Jul 2026 (split from PLAN.md lines 989-1082) | completed |
| [_needs-triage/futureDev.md](_needs-triage/futureDev.md) | bmason's 7 Jul 2026 backlog; mixed completion, no status markers | unclear |

## Root files

`AGENT_WORKFLOW_RECOMMENDATIONS.md` and `BIDIRECTIONAL_AGENT_BRIDGE_SPEC.md` are
untracked working notes about agent tooling. They are left in the repo root and
have not yet been filed into `docs/`.
