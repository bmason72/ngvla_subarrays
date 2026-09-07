# Consult: what to work on while the MFS snapshot campaign runs (astra_seer / gpt-6-astra, 7 Sep 2026)

Question file: `tmp/codex/astra_wishlist_consult.md` (bmason wishlist in `docs/plans/wishlist.md`; constraint: running Slurm stages import the main working tree). Reply verbatim below.

**Work on documentation and bounded design notes now. Keep the campaign’s working tree frozen except for docs.** Use separate worktrees for code, configuration, registry, or data changes; merge only after collect finishes and its outputs are checked.

Ranked by safety first, then value:

1. **Documentation review (6): docs-only, high value.** Clarify samples versus envelopes, curve identities, units, registry relationships, and campaign execution. Document the shared-working-tree hazard prominently. Give workers specific files and questions to resolve.
2. **curveLimits design (2): docs-only now; isolated implementation is a good bounded task.** It has a smaller scope and clearer acceptance criteria than curveRefactor.
3. **ngVLA imaging skill (7): docs-only, high recurring value.** Capture established commands, validation checks, scientific conventions, and campaign safeguards. Reference authoritative documentation rather than duplicating it. Test the instructions against one concrete task.
4. **curveRefactor design note (1): docs-only, worthwhile.** Specify the product contract and compatibility tests now; defer the rewrite.
5. **Parallelism investigation (3): read-only timing analysis and a small spec amendment.** Do nothing to the active campaign.
6. **New combos (4): definitions now; code/data in a worktree.** Resolve membership, metadata, and baseline-selection semantics before assigning implementation.
7. **Remaining RevF MFS runs (5): prepare the manifest now; launch after reviewing this campaign.**
8. **Other data skills (8): defer unless an upcoming task needs them and representative workflows are available.**

For **curveRefactor**, make the durable product a *versioned, evaluated envelope*, with:

- Curve identity: revision, simulation mode, band, subarray, and envelope type.
- Ordered vertices **plus whatever segment/cell connectivity, branch information, and anchor mappings the evaluator needs**. Do not assume an unordered vertex list preserves the current piecewise-linear/bilinear behavior.
- Units, interpolation rules, numerical support, manually allowed range, and build provenance: envelope algorithm version, parameters, source-samples checksum, and archive location.
- Optional PSF attachments indexed by stable anchor IDs, with radius units, normalization, extent, and generation provenance.

Keep samples as a compressed archival input; remove the requirement to load them during routine reporting and selection. That preserves the ability to rebuild with a changed envelope algorithm.

Migrate additively: export products alongside samples, compare old and new evaluations on representative inputs and boundaries, then move selection, reports, and the calculator to the shared contract. Retain the old path until parity is demonstrated. The principal risk is freezing an incomplete representation while Python and JavaScript quietly implement different semantics.

**Design note now, code later.** Measure anchor counts and payload sizes before deciding PSF storage. An inner radial profile can support display and some diagnostics; it cannot preserve full two-dimensional PSF structure or outer sidelobes. Do nothing about retaining full PSFs until the intended analysis and storage budget are explicit.

For **curveLimits**, use a small companion CSV keyed by a stable curve ID, with optional `resolution_min`, `resolution_max`, and a reason. Define the resolution unit centrally. Avoid row-number keys and implicit filename matching.

The usable domain is the intersection of the computed envelope’s support and the manual interval. Apply it through a common evaluation interface used by selection and reports; serialize the same effective limits to the calculator. Reject out-of-range queries clearly rather than silently clamping them. Preserve existing gaps; bounds must not invent support. The report should label the valid interval and visibly distinguish excluded portions. Test exact endpoints, empty intersections, and Python/calculator agreement.

For **parallelism**, design only the missing scheduler boundary now. The eight-job queue limit makes packing more work into each allocation plausible, but does not establish whether pylauncher is the best solution. Use current timing to distinguish long-tail imbalance from startup, I/O, and resource bottlenecks. Compare those findings with the parked wave-runner spec before creating another runner. A bounded follow-up should address multi-node dispatch, resource limits, failure propagation, and restart behavior—not combine scheduling changes with adaptive-sampling changes.

Reframe **new combos** as separate scientific-definition tasks. In particular, make the LONG baseline rule explicit; an ambiguous filter could invalidate comparisons. Drop the goal of discarding samples, and defer generic skill collections without an immediate use case.

- **Do now:** 1) documentation review; 2) curveLimits specification; 3) ngVLA imaging skill; 4) curve-product design note.
- **Do next:** 1) curveLimits in a worktree; 2) prepare validated combo definitions and the RevF MFS manifest; 3) assess timing against the parked runner spec.
- **Wait:** production merges and launches until collect is checked; curveRefactor implementation until its contract is settled; scheduler implementation until timing supports it.
- **Drop/defer:** deleting archival samples; a second competing runner; full-PSF retention without a use case; unrelated data skills for now.