# Editing the report's explanatory prose

For rewording the collapsible "Explanation" text (and the few static notes)
in the HTML report.

## Where it lives

Edit `curvegen/report_template.html` directly — it is the source. No report
prose is generated from Python for the **single-campaign report** (the normal
case): `make_report.py` only fills in the `__DATA__` payload and the
provenance footer (git commit + build time), plus a title-only find/replace
for non-default `title_label` builds (page title, `<h1>`, and the opening
words of the header explanation — not the prose body).

**Exception — the combined (multi-campaign) report only:** when the report
carries the campaign dropdown, the page's `<h1>` and the header explanation
paragraph (`.sub`, ~L211) are replaced at runtime by JS from `combo.h1_html` /
`combo.sub_html` in the data payload (`report_template.html` ~L2540-2546).
Those strings are duplicated in `curvegen/make_report.py`'s `combo_entry()`
(the non-MFS branch, ~L1076-1089, and the MFS branch, ~L1053-1064), plus the
`_SNAPSHOT_NOTE_HTML` and `_SUB_TAIL_HTML` constants (~L1004-1026) used for
`combo-note`. If you reword the header explanation and want the combined
report's dropdown to match, edit both the template **and** these Python
strings. The other 8 explain blocks have no Python-side copy — template-only.

## The prose blocks

| # | Line | Section (`<h2>`) | Opening words |
|---|------|-------------------|---------------|
| 1 | 210 | page header (before "Subarray calculator") | "These plots show sensitivity cost..." |
| 2 | 231 | Subarray calculator | "Use the same tabulated curves as the plots..." |
| 3 | 297 | Subarray calculator (second block, the calc caveat) | "The times use the thermal-noise part..." |
| 4 | 341 | Imaging sensitivity cost by resolution | "At each target resolution, the curve shows..." |
| 5 | 357 | Point-source sensitivity cost by resolution | "These curves include all beams..." |
| 6 | 379 | Valid simulation results | wraps **two** `<p>`s — see below |
| 7 | 400 | Sweep grid in robust and taper space | "Each plot shows the full sweep grid..." |
| 8 | 415 | PSF inspector | "Select a subarray to examine its measured PSF..." |
| 9 | 433 | Subarray summary and native-beam checks | "This table compares the simulated native beam..." |

**Special case (block 6, line 379-393):** one `<details>` wraps **both**
`#samples-resolution-note` (L380, shown by default — the "resolution and
sensitivity cost" view) and `#samples-parameters-note` (L384, `style="display:
none"` — the "taper and robust" view). The view dropdown (`#samples-view-
select`) toggles which `<p>` is visible via JS. Keep both `<p>` elements and
both `id`s — reword the text inside each, but do not merge, delete, or
re-tag either one.

**Not collapsed, still editable, still prose:**

| id | Line | Notes |
|----|------|-------|
| `#combo-note` | 226 | Empty in the template; filled at runtime from `combo.note_html` (combined report only — see above). Static text has nothing to edit here directly. |
| `#imaging-omitted-note` | 338 | Static text: "This campaign contains only point-source results. Imaging curves are not available." Free to reword. |
| `#psf-params` | 427 | Empty `<p>`; filled by JS (`psf-*` controls), not static prose. |

## How to edit

Change the paragraph text between `<p class="...">...</p>`. Leave the
`<details class="explain"><summary>Explanation</summary>` wrapper, the
`<p>` `id`/`class` attributes, and any inline HTML entities (`&thinsp;`,
`&eta;`, etc.) or embedded `<code>`/`<a>`/`<sub>` tags intact unless you mean
to change what they render.

## Phrases asserted by tests

`tests/test_report_baseline_ranking.py`'s `TestReportCollapsibleSections`
(L466-524) is the authoritative structural check: it asserts every explain
block's **opening phrase** is present, that the three dynamic notes stay
*outside* any `<details class="explain">`, and that the samples block wraps
both `<p>` ids together. Beyond that, four more specific sentence fragments
are pinned in `tests/test_report_calculator.py` and `tests/test_report_
release.py`.

| Phrase | Template location | Test | Rewording |
|--------|-------------------|------|-----------|
| "These plots show sensitivity cost" | L211, page header | `test_report_baseline_ranking.py:474`, `test_listed_prose_blocks_are_wrapped_in_explanation_details` | Safe — only the opening words are pinned; reword the rest freely, or change the opening words and update the list entry (L474). |
| "Use the same tabulated curves as the plots" | L232, Subarray calculator | `test_report_baseline_ranking.py:475`, same test | Safe, same rule. |
| "The times use the thermal-noise part" | L298, Subarray calculator (caveat) | `test_report_baseline_ranking.py:476`, same test | Safe, same rule. |
| "At each target resolution, the curve shows" | L342, Imaging card | `test_report_baseline_ranking.py:477`, same test | Safe, same rule. |
| "These curves include all beams" | L358, Point-source card | `test_report_baseline_ranking.py:478`, same test | Safe, same rule. |
| `id="samples-resolution-note"` / `id="samples-parameters-note"` | L380 / L384 | `test_report_baseline_ranking.py:479-480`, same test, and `test_samples_notes_share_one_explanation_details` (L512-520) | Keep both ids — the text itself is unconstrained. |
| "Each plot shows the full sweep grid" | L401, Sweep grid card | `test_report_baseline_ranking.py:481`, same test | Safe, same rule. |
| "Select a subarray to examine its measured PSF" | L416, PSF inspector | `test_report_baseline_ranking.py:482`, same test | Safe, same rule. |
| "This table compares the simulated native beam" | L434, Subarray summary | `test_report_baseline_ranking.py:483`, same test | Safe, same rule. |
| `id="combo-note"` / `id="imaging-omitted-note"` / `id="psf-params"` | L226, 338, 427 | `test_report_baseline_ranking.py:487-489`, `test_dynamic_and_warning_notes_are_not_wrapped` | Checks these stay *outside* `<details class="explain">` and still exist — not a text check. |
| "adaptive refinement where needed" | L216-217 (inside the L210 header block) | `test_report_calculator.py:54`, `test_report_header_copy_and_stats_location`; **also** `test_report_release.py:57`, `test_combo_header_includes_refinement_and_ngect_context` (checks `make_report.combo_entry("revD","track")["sub_html"]`, i.e. the Python-duplicated copy, not the template) | If you drop or reword this exact fragment, update **both** the template line and the two-line string literal in `make_report.py` (~L1086-1087, the non-MFS `combo_entry` branch) — plus both tests. |
| "every adaptive cell touching the point passed" | L388, `#samples-parameters-note` | `test_report_calculator.py:60`, `test_adaptive_validation_is_explained_and_drawn` | Safe to reword if you also update the test string (no Python duplicate). |
| "never added" | L301, calc caveat (first paragraph) | `test_report_calculator.py:86`, `test_confusion_is_separate_and_blocks_only_mfs` | Safe to reword if you also update the test string. |
| "no autocorrelations" | L319, calc caveat (third paragraph) | `test_report_calculator.py:102`, `test_single_channel_visibility_estimate_is_in_ranked_listing` | Safe to reword if you also update the test string. |

Everything else `assertIn`/`assertNotIn`/`assertRegex` hits in `tests/`
(checked across all 26 files, not just the two obvious ones — `test_adaptive
.py`, `test_export_ngect.py`, `test_mfs_campaign.py`, `test_cli.py`,
`test_sa_select.py`, `test_psf_report_metrics.py`, `test_report_provenance
.py`, etc.) match JS source, CSS rules, HTML tags/ids/attributes, or CLI/
Python error-message constants — not the human-readable `.note`/`.sub`
paragraph text. You will not touch those while rewording prose.

## Two traps

**A pinned phrase must stay on ONE source line.** The tests match literal
substrings including their single spaces, so reflowing a paragraph can break a
pin even when you changed no words. This happened during the 11 Sep 2026 prose
pass: rewrapping put a newline inside "every adaptive cell touching the point
passed" and the test failed on wording that was never touched. If a pin fails
after an edit you believe was cosmetic, check the line breaks first.

**The calculator caveat is now three `<p>` elements**, split on 11 Sep 2026
into the sensitivity/confusion model, the baseline ranks, and the standing
caveats. Only the first carries `class="note calc-caveat"`; the other two are
plain `class="note"`, because `.calc-caveat` sets a `margin-top` that should
not repeat. `details.explain > p.note` handles the spacing between them.

## Rebuild to check one page

```bash
cd curvegen && python3 make_report.py reports/revf-curves.html
```

(No `--combined` needed — that gathers every registered campaign, which is
slower and unnecessary for eyeballing wording changes. Add the `casapy`
wrapper prefix if you are not already inside an activated CASA/casaenv
Python.) The full nine-report rebuild sequence used before a checkpoint
commit is narrated in `docs/worklog/baseline-ranking.md` (2026-09-11 entry).

## Run the tests

```bash
casapy -m unittest discover -s tests -t .
```

Current baseline: **468 tests, OK, 1 skip.** If you changed one of the
pinned fragments above without also updating its test, expect exactly that
test to fail — the failure message names the missing string.
