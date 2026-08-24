# RELEASE_PLAN — MVP release per WRAPUP.md (drafted 17 Aug 2026)

> **Progress (18 Aug 2026):** T0 DONE (6332362).  **T1 DONE** — retrofit
> wave 2 (tracks) + backfills completed 18 Aug, exit 0; revF/track 6/14
> maps converged, revD/track 2/9, the rest still at the audit cap; all
> step features again classified genuine.  **Wave 3 = bmason decision**
> (launch lines in RUN_CAMPAIGNS.md).  **T2 DONE** (code 66a5e7c; the
> campaign ran 17-18 Aug, 9 subarrays, all curves + PSF payloads in; NO
> combo-4 backfill needed — dry-run audit shows every anchor cut-bearing).
> T3 DONE (437d083; release page rebuilt 18 Aug WITH revC).  T4 DONE
> (35ddd23).  T5 DONE (6a97b95).  T6 in progress: bmason's review comments
> (memo/myComments.tex, through §4 ¶1) applied 18 Aug with gpt-5.6-sol
> consult+review — restructured §§1–3 (beam-cap/uv-filter/lattice
> subsections, Development-history appendix, core+mid row dropped,
> overlap factors & cap semantics corrected from code); comments beyond
> the stop marker still pending bmason.  253 tests green (1 skipped).
> **Page fixes (18 Aug pm, bmason review):** calculator PSF button now
> renders the PSF inline under the clicked row; missing-payload message
> now says when the psf/ dir is not next to the HTML (psf_exported
> manifest); composite-beam explainer + Caveats&status cards removed
> (sample table kept).  gpt-5.6-sol guard review: one finding, verified
> false positive (manifest is per-payload), waived.
> **Standalone release page (18 Aug pm, bmason request):** the --release
> build now embeds all PSF payloads gzip+base64 (inflated in-browser via
> DecompressionStream on first use) — ONE ~17 MB file to scp, no psf/
> dir.  Internal report keeps the lazy sibling-dir design (15 Jul
> decision).  Implemented by a Sonnet subagent to Claude's spec (codex
> build sandbox bwrap-broken 18 Aug); gpt-5.6-sol consult review: 4
> findings, all 4 fixed (hang-guard try/catch, per-id missing message,
> strict-JSON build guard, escaped-id guard).
> **PSF capture range 3 -> 10 FWHM (18 Aug pm, bmason request):** new
> `measure.CAPTURE_RMAX_FWHM=10` at the same sampling density; each cut
> line records `cut_rmax_fwhm` and backfill treats shorter-range or
> unusable cut lines as stale, so the queued wave-3 backfills (combos
> 0, 2) refresh EVERY anchor automatically; combo 4 (revC) needs its own
> `--array=4` backfill (line in RUN_CAMPAIGNS).  Chart: per-entry range,
> sqrt-r x scale keeps the core legible; null (out-of-bounds) cut samples
> no longer render as fake zeros.  bmason's avg-above-cuts observation
> was verified GENUINE, not a bug: radius is geo-mean-normalized in all
> three curves; the worst cases are fitted-beam bmaj overestimation on
> messy LONG cores (cut half-power at 0.49x fitted) plus real angular
> sidelobe structure.  Codex review round 1 (gpt-5.5 xhigh, model-default
> slip): 4 findings, all fixed; round 2 on gpt-5.6-sol.  271 tests green.
> **(19 Aug) Wave-3 in flight; release page STALE for PSF range:** the
> 19-Aug 11:32 release rebuild predates the still-running wave-3
> backfills that refresh anchors to 10 FWHM (page verified mostly
> 3-FWHM: revF 0/2839 cuts at 10, revD 451/2852, revC 0/1935).  revC's
> range-refresh backfill was subsequently launched as 3421939_4.  Rebuild
> + re-verify
> after all backfills drain; harvest checklist in PLAN.md 19-Aug delta.

Scope authority: `WRAPUP.md` (17 Aug) supersedes PLAN.md / NEXT_AGENT.md where
they conflict.  Release = calculator **web page** (the in-report client-side
calculator + curves) and **python prototype** (`sa_select/`) for:

| campaign | curves released |
|---|---|
| revF / 4h track | point-source AND imaging |
| revD / 4h track | point-source only (imaging section marked "Omitted/Intentionally blank") |
| revC / 4h track | point-source only (NEW campaign — must be run) |

Snapshot campaigns are NOT in the release.  The released page contains only
the three track campaigns; the full internal all-campaigns report stays
buildable as before.

Decisions confirmed by bmason (17 Aug):
1. Retrofit: ONE more adaptive-retrofit wave, tracks only (combos 0 and 2),
   then reassess — not necessarily to full convergence.
2. revD imaging: mark "Omitted" on the released page even though data exists.
3. Released page = 3 track campaigns only; internal report keeps everything.
4. MStroh support = BOTH formats: per-subarray `.cfg` inputs AND
   `subarray_data.json`/spline interchange for the calculator.

## Status at plan time (17 Aug)

- The 21-24 Jul canary + adaptive retrofit chain COMPLETED (sacct): canary
  sweep/collect, retrofit array 0-3, all four PSF backfills exit 0.  Logs
  archived in `/work2/10240/bmason72/stampede3/oldNgvlaLogs/`.
- BUT: nearly every revF/track and revD/track map stopped at the 80-eval
  audit cap ("wave 1 of ~2-3").  Snapshot maps mostly converged
  ("no proposals").  So the release-critical track curves are improved but
  not certified-converged — hence decision 1.
- 55 files of retrofit results sit UNCOMMITTED (results CSVs + routed
  sa_select curve tables).  The post-backfill combined-report rebuild
  (RUN_CAMPAIGNS final step) was never run.
- PSF axis-cut payloads exist for all four campaigns (backfills done), so
  WRAPUP item 3 (PSF cuts on the page) needs NO new sims beyond revC's own
  runs — the report JS already renders cuts when present.
- The in-page "Subarray calculator" (client-side, same tabulated curves)
  already exists in `report_template.html` — it IS the web prototype.
- Rev C.01 component cfgs exist (`ngvla-configurations/Rev C.01/CASA Files/`:
  core 94, spiral 74, mid 46, lba 31, main, sba) — same component style as
  revD, so `curvegen/config.py` extends by pattern.

## Tasks (in order; compute overlaps build work)

### T0. Recover + commit the July results  [no compute; Sonnet/gpt-5.6 low]
- Verify tests green (`casapy -m unittest discover -s tests -t .`; 225 expected).
- Rebuild the combined report (final run-sheet step), eyeball: sawtooth fixed,
  honest classified cliffs, revD/snapshot long ~2.6 mas step classification
  (check `adaptive_retrofit_3335064_3.log`), PSF cuts render at anchors.
- Data milestone commit: the 55 modified CSVs + a short PLAN delta.

### T1. Retrofit wave 2, tracks only  [compute ~1 day; launch FIRST]
```
RID=$(sbatch --parsable --array=0,2 curvegen/adaptive_retrofit.sbatch | tail -1)
for K in 0 2; do sbatch --array=$K --dependency=afterok:${RID}_$K curvegen/backfill_psf.sbatch; done
```
Resumable; each task tails its own collect+report+export.  QA per
RUN_CAMPAIGNS ("Adaptive retrofit wave").  Reassess cap-hits after; bmason
call on a third wave.  Commit data milestone when it drains.

### T2. revC/track campaign  [build: Sonnet/gpt-5.6 medium; compute ~1-2 days]
- Extend `curvegen/config.py`: revC component dir/cfg map (lba→long, like
  revD), offered subarray set mirroring revD's, imsize map, beam caps.
- Add `config_registry.csv` row (APPEND — combo indices 0-3 must not move),
  `subarrays_revc.csv` builder, sbatch plumbing for the 5th combo.
- ptsrc-only scope: run the standard campaign (skirt rides along free from
  the same PSFs); skip imaging-targeted refine effort if a config knob is
  cheap, otherwise just don't display imaging.  4h track only.
- Chain: submit_campaign revC track → inspect → backfill_psf for the new
  combo (fresh points carry cuts natively; grid anchors may still need it).
- Tests for the new registry/config paths.

### T3. Release web page  [Sonnet/gpt-5.6 medium]
- `make_report.py --release` (or similar): campaign dropdown = 3 tracks;
  imaging sections for revD + revC render "Omitted / Intentionally blank";
  remove the core+mid caveat (`report_template.html` ~line 343) per WRAPUP.
- Verify PSF cut display + calculator behave for all three campaigns.
- Internal `--combined` report unchanged (all campaigns incl. snapshots).

### T4. Python calculator release surface  [Sonnet/gpt-5.6 medium]
- Route revC curves through the sa_select registry; imaging-mode queries
  clearly scoped (revF only in release terms — warn or document for others).
- Sanity target: able to reproduce the current EOP
  (https://ngvla.nrao.edu/download/MediaFile/260/original) for revF ptsrc +
  imaging — bmason's near-term use.  Make batch/case-list input convenient.

### T5. MStroh format support  [stretch — do NOT descope core for it]
- Input: accept a per-subarray monolithic `.cfg` (his
  `ngvla-revF.<sa>.cfg` style) as a subarray definition alongside component
  composition.
- Interchange: read (convert √2 beam convention! see mstroh_comparison.md)
  and optionally write `subarray_data.json`/splines for the calculator.

### T6. Documentation sweep  [Fable/gpt-5.6-sol high — editorial]
- README, PLAN (mark superseded scope), NEXT_AGENT, RUN_CAMPAIGNS refreshed
  to the release scope; stale docs marked.
- LaTeX memo: add (a) concise campaign/report run instructions, (b) the
  python calculator interface, (c) the still-undocumented machinery
  (escalation ladder, display smoothing, adaptive sampler, PSF cuts).
  Editorial pass: ASD-STE100 + Zinsser (simplicity, brevity, clarity,
  humanity).  Must compile clean.
- Final release commit + tag.

## Working agreements (WRAPUP)
- Subagents of equal/lower capability for well-specified tasks.
- codex bridge (gpt-5.6-sol) for consults/reviews; probe its sandbox first.
- Local HTML only — never the Artifact tool.
