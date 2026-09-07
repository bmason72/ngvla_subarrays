# Manual curve limits

## Current status

**Built**, not yet merged. Implemented on `feature/curve-limits` in the worktree
`/work2/10240/bmason72/stampede3/ngvla_wt_curvelimits`, per
`docs/plans/curve-limits-spec.md` (copied into this worktree at the same path). No
values have been declared yet — `sa_select/data/curve_limits.csv` ships with the
header and no rows, so this feature is inert until bmason adds a row. Do not merge to
`main` until the running campaign's collect stage has finished and been checked (per
the spec's header).

**Decisions:**
- The single shared evaluation interface is `sa_select.envelope.Envelope.solve()` /
  `solve_interval()` — both `sa_select.curves.CurveLibrary.solve_detailed` (the
  selector) and `Envelope.curve()`'s own per-grid-point loop call it. A manual limit
  is applied there via a new optional `limit=(res_min, res_max, reason)` parameter, and
  a window with **no** overlap raises `OutOfCurveLimitError` (a typed exception), never
  a clamped answer; a partially overlapping window is clipped to the intersection, the
  same treatment the existing `max_res` (heterogeneous beam cap) parameter already
  gets.
- **Deviation from a literal reading of the spec:** `curvegen/make_report.py`'s calls
  to `Envelope.curve()` are deliberately **not** given `limit=`. The report's curve
  arrays serve two purposes — the static chart (which must show the curve's shape past
  a manual limit, dashed/muted, not lose it — spec item 4) and the in-page calculator's
  lookup table (which must refuse to answer there — spec item 4 again). Passing `limit`
  into `curve()`'s internal per-grid-point `solve()` calls would raise
  `OutOfCurveLimitError` mid-loop and either crash the report build or force dropping
  those points outright, which is the wrong outcome for the chart. Instead,
  `make_report.curve_limit_payload()` computes the same `effective_domain()` (coverage
  ∩ limit) once per (subarray, curve kind) via a coverage() call, and
  `tag_excluded_points()` flags the affected points `excluded: true` in place, keeping
  them in the array. The calculator (`report_template.html`'s `limitInfeasibleReason`)
  separately re-derives the same rejection from the serialized effective domain before
  it ever picks a curve point, so it still refuses to evaluate there, matching the
  Python selector's message wording (see the agreement test below). Net effect: the
  selector rejects at the query interface (exception); the report/calculator reject
  and/or visually exclude using the SAME effective-domain numbers, computed by the same
  `effective_domain()` function, just applied at a different point suited to each
  caller's shape (a single query vs. a precomputed table + a static chart).
- `CurveLibrary.__init__` now defaults `rev="revF", sim_mode="track", band=""` (it
  previously carried no combo identity) so a bare `CurveLibrary()` keys the manual
  limits lookup exactly like `for_config("revF", "track")`, matching the existing
  documented equivalence between the two. `CurveLibrary.from_tables` (no registry
  identity) carries no limits (`{}`), since a curve delivered that way is not a
  registered combo the limits CSV can key on.
- The report's `curve_limits` payload key is present (`{}` when empty) even on the
  default, unedited checkout — a new key, not byte-identical JSON, but functionally
  inert (no `excluded` flags anywhere, `curve_limits == {}`); the spec's "byte-identical
  when the CSV has no rows" is read as "behaviorally inert," per the worker brief, and
  is asserted directly (`tests/test_curve_limits_report.py::TestCurveLimitsPayloadInert`).

**Gotchas:**
- No JS execution harness exists in this repo (no `node` on this environment;
  `tests/test_report_calculator.py`'s own docstring calls itself a "static contract
  check" file). The Python↔JS agreement is therefore tested as static string-presence
  checks against `report_template.html`'s source (function names, call ordering, and
  message-wording substrings shared with `sa_select/curves.py`), the same technique the
  pre-existing calculator tests use for every other calculator behavior. See
  `tests/test_curve_limits_report.py::TestCalculatorJsAgreement`.
- A synthetic `Envelope` fixture with res steps much bigger than ~1.3x (e.g. 5→10→18→30
  arcsec) builds **no segments at all** (the lattice-step pruning in
  `build_segments`/`MAX_RES_STEP` rejects it), so `curve()` returns almost nothing. The
  `TestManualCurveLimit` fixture in `tests/test_envelope.py` copies
  `TestBeamCapClipping`'s known-good step sizes (20→24→30) instead of inventing new
  numbers.

**Next actions:**
- Merge to `main` once the running campaign's collect stage is done and checked (per
  the spec).
- When bmason is ready to declare real limits, add rows to
  `sa_select/data/curve_limits.csv`; no code changes needed.

## Log

### 2026-09-07

Implemented the full spec:
- `sa_select/data/curve_limits.csv`: header + leading provenance/units comment, no
  rows.
- `sa_select/curves.py`: `CurveLimit` dataclass, `load_curve_limits()` (comment-line
  tolerant, validates required fields / `curve` enum / numeric bounds / `res_min <=
  res_max` / no duplicate keys, raises `ValueError` naming the file and line number),
  `CurveLibrary.limit_for()`, `CurveLibrary.__init__`/`for_config`/`from_tables` now
  carry `(rev, sim_mode, band)` identity and load limits; `solve_detailed` looks up the
  limit for the query's curve kind (`ptsrc` if `skirt_threshold is None` else
  `imaging`), passes it to `Envelope.solve`, and catches `OutOfCurveLimitError` into the
  existing `(sample=None, message)` contract.
- `sa_select/envelope.py`: `OutOfCurveLimitError`, `_clip_to_limit`,
  `effective_domain()` (module-level and an `Envelope.effective_domain()` convenience
  wrapper), and a `limit=` parameter on `Envelope.solve()`.
- `curvegen/make_report.py`: loads `CURVE_LIMITS` once at import; `curve_limit_payload()`
  and `tag_excluded_points()` compute the effective domain per (subarray, curve kind)
  from the same samples `build_curve()` is given, and tag the built imaging/pointsource
  curve points `excluded: true` in place (every skirt setpoint of the imaging curve
  shares one limit row, since the interval is a property of the resolution axis, not
  of `s0`); `curve_limits` and `curve_limits_source` added to the payload.
- `curvegen/report_template.html`: `curveChart` now splits each series into runs by
  (gap OR excluded-state change) and draws excluded runs dashed/muted rather than
  dropping them; `ttHtml` adds a reason line for excluded points; `legend()` puts the
  valid interval + reason in each chip's hover title (`curveLimitEntry`/
  `fmtLimitInterval` helpers); a per-card provenance note
  (`renderCurveLimitsNote`) states which curves carry a limit, the reason, and the CSV
  path; `lookupCurvePoint` calls a new `limitInfeasibleReason()` before building its
  candidate window, rejecting with the same wording `CurveSolveResult` uses, and the
  window filter also excludes any `p.excluded` point defensively.
- Tests: `tests/test_envelope.py` (`TestEffectiveDomain`, `TestManualCurveLimit`),
  `tests/test_sa_select.py` (`TestCurveLimitsLoader`, `TestManualCurveLimits`), and a
  new `tests/test_curve_limits_report.py` (payload inert / with-a-row / unusable-curve,
  and the static JS-agreement contract).
- Docs: this file, and `docs/architecture/selection-tool-design.md` §10.

Full suite (`casapy -m unittest discover -s tests -t .` from the worktree root): see
the hand-off report for the exact result line; the CASA-free subset
(`test_envelope`, `test_sa_select`, `test_curve_limits_report`, `test_report_release`,
`test_report_standalone`, `test_report_calculator`) is green under both plain
`python3` and the `casaenv` interpreter.
