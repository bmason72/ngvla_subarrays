# Spec: curveLimits (manually specified valid range per curve)

Status: worker spec, 7 Sep 2026 (Fable orchestrator; design per the astra_seer
consult in `docs/worklog/wishlist-consult-2026-09-07.md`).  Build in the
worktree `/work2/10240/bmason72/stampede3/ngvla_wt_curvelimits` (branch
`feature/curve-limits`); merge to `main` only after the running campaign's
collect stage has finished and been checked.

## Goal

Let bmason declare, per curve, a resolution interval outside which the curve
must not be used, without touching the measured samples.  Selection, the
per-combo and combined reports, and the in-page calculator must all honour
the same effective limits.

## Design

1. **Where limits live.** New CSV `sa_select/data/curve_limits.csv` with
   header `rev,sim_mode,band,subarray,curve,res_min_arcsec,res_max_arcsec,reason`.
   `curve` is `ptsrc` or `imaging`; `band` is blank for mono combos.  Either
   bound may be blank (= unbounded on that side).  Resolution is the curve's
   native angular resolution in arcsec at the combo's reference frequency
   (30 GHz for mono, the band reference for MFS), the same quantity the
   curve CSVs carry; state this in the file's leading comment line if the
   loader tolerates comments, otherwise in a `docs/architecture` note.  Ship
   the file with the header and NO rows (behaviour unchanged until bmason
   adds rows).
2. **Effective domain.** For a curve, the usable domain is the intersection
   of the computed envelope's support (its existing coverage interval,
   including any interior gaps, which are preserved: limits never invent
   support) and the manual interval.  An empty intersection makes the curve
   unusable and must be reported as such, not silently dropped.
3. **Single evaluation interface.** Find the code path the selector
   (`sa_select`, e.g. `CurveLibrary.for_config` / the envelope evaluation
   used by ranking) and the report (`curvegen/collect.py`,
   `curvegen/make_report.py`) share for evaluating a curve at a resolution.
   Apply the limits there, once.  Queries outside the effective domain
   return an explicit "outside valid range" outcome (a flagged result or a
   typed exception the caller handles), never a clamped value.
4. **Report and calculator.** Serialize the effective limits per curve into
   the report payload; the calculator JavaScript must reject out-of-range
   requests with the same message and must not evaluate there.  On the
   curve chart, draw the excluded portions visibly distinct (dashed or
   greyed) and label the valid interval in the legend or a caption, and show
   the `reason` on hover or in the QA table.
5. **Provenance.** The report states that manual limits are in force for a
   curve and where they come from (the CSV path and reason).

## Tests (CASA-free)

- Loader: header-only file gives no limits; a row with one blank bound;
  malformed rows rejected with a clear message.
- Effective domain: exact endpoints inclusive; empty intersection flagged;
  interior gaps preserved; mono and MFS combos both resolvable.
- Selector: a request just inside is accepted, just outside is rejected
  with the explicit outcome; ranking excludes an unusable curve.
- Report payload carries the same limits the Python side used; if the repo
  has a JS test harness (check tests/ for how `report_template.html` logic is
  tested), add the agreement test there; otherwise test the serialized
  payload and document the gap.
- Full suite green.

## Docs

- `docs/architecture/selection-tool-design.md` or `PSF_DIAGNOSTICS.md`
  (whichever documents the curve evaluation): a short "Manual curve limits"
  section.  README table of data files if one exists.
- `docs/worklog/` : add a dated paragraph to `mfs-campaigns.md` is NOT the
  place; create `docs/worklog/curve-limits.md` per `docs/worklog/README.md`.

## Out of scope

Choosing any actual limit values; changing the envelope algorithm.
