"""Executed browser metric contract, using the function in the real template."""

import json
from pathlib import Path
import re
import unittest

try:
    import quickjs
except ImportError as exc:
    raise ImportError(
        "quickjs is required to run tests/test_report_baseline_ranking.py: these "
        "tests execute the real browser calculator functions from "
        "curvegen/report_template.html and must not be silently skipped. Install "
        "it with:\n"
        "    /work2/10240/bmason72/stampede3/casaenv/bin/python3 -m pip install quickjs"
    ) from exc

from sa_select.baselines import DEFAULT_LAS_RATIO, baseline_metrics, load_baseline_geometry


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = (ROOT / "curvegen" / "report_template.html").read_text()


def function_source(name):
    start = TEMPLATE.index("function %s(" % name)
    brace = TEMPLATE.index("{", start)
    depth = 0
    for pos in range(brace, len(TEMPLATE)):
        if TEMPLATE[pos] == "{":
            depth += 1
        elif TEMPLATE[pos] == "}":
            depth -= 1
            if not depth:
                return TEMPLATE[start:pos + 1]
    raise AssertionError("unterminated function %s" % name)


def calculator_context(data, request, *, missing_sensitivity=False,
                       bad_cost_name=None):
    """Run the real calculator functions with only rendering/curve I/O stubbed.

    The ordering, feasibility and baseline metric code remains the template's
    JavaScript; the tiny DOM stand-in only records what it would render.
    """
    context = quickjs.Context()
    context.eval("""
      function fixedMfsWindow() { return DATA.fixed_window || null; }
      function capInfeasibleReason() { return null; }
      function lookupCurvePoint(name, request) {
        return {point: {res: request.resolution * 1000,
          eta: name === BAD_COST_NAME ? Infinity : 1,
          weighting: 'natural', relaxed: name === 'relaxed'}};
      }
      function interpolateSigma(name, freq) {
        if (MISSING_SENSITIVITY) return {reason: 'missing sensitivity table'};
        if (MISSING_MAIN && name === 'main') return {reason: 'missing sensitivity table'};
        return {sigma: 1};
      }
      function psfMetricForPoint() { return null; }
      function confusionForMetric() { return DATA._confusion ?? NaN; }
      function fmtConfusion(x) { return String(x); }
      function fmtS0(x) { return String(x); }
      const RESULT = {};
      const ELEMENTS = {};
      function node() { return {textContent: '', rows: [], firstChild: null}; }
      const document = {getElementById: id => ELEMENTS[id] || (ELEMENTS[id] = node())};
      function renderCalcSummary(el, winner, request, rankingAvailable=true) {
        RESULT.winner = winner || null; RESULT.rankingAvailable = rankingAvailable;
      }
      function renderCalcTable(el, rows, request, rankingAvailable=true) {
        RESULT.tableRankingAvailable = rankingAvailable;
        RESULT.rows = rows.map(row => ({
        name: row.name, feasible: row.feasible, tHours: row.tHours,
        antennaHours: row.antennaHours, cost_error: row.cost_error || '',
        baseline: row.baseline || null})); }
      function renderInfeasible(a, b, rows) { RESULT.infeasible = rows.map(row => row.name); }
      function readCalcRequest() { return {request: REQUEST}; }
    """)
    context.eval(function_source("finitePositive"))
    for name in ("CALC_CORRELATOR_DUMP_SECONDS", "CALC_VISIBILITY_CHANNELS",
                 "DEFAULT_LAS_RATIO"):
        context.eval(re.search(r"const " + name + r" = [^;]+;", TEMPLATE).group())
    context.eval("DATA = " + json.dumps(data) + ";")
    context.eval("REQUEST = " + json.dumps(request) + ";")
    context.eval("MISSING_SENSITIVITY = %s; MISSING_MAIN = %s; BAD_COST_NAME = %s;" %
                 (str(missing_sensitivity).lower(),
                  str(data.get("_missing_main", False)).lower(),
                  json.dumps(bad_cost_name)))
    context.eval(function_source("baselineMetric"))
    context.eval(function_source("evaluateSubarray"))
    context.eval(function_source("runSubarrayCalculator"))
    return context


def fixture_data(geometry, order=("main", "main+long"), **extra):
    data = {
        "order": list(order), "fixed_window": None,
        "las": {name: {"coeff": .8, "n_ant": item["n_ant"], "mas": 1e9}
                for name, item in geometry.items()},
        "baseline_geometry": {
            name: dict(item, status="ok",
                       n_pairs=item.get("n_pairs", len(item["lengths_m"])))
            for name, item in geometry.items()},
    }
    data.update(extra)
    return data


def fixture_request(rank="performance", **extra):
    request = {"freq": 30.0, "resolution": 7.0, "las": None,
               "bandwidth": 1000.0, "sensitivity": 1.0,
               "goalMode": "explicit", "obs": "pointsource", "rank": rank,
               "sensUnit": "Jy", "beamMargin": .05, "skirtThreshold": .1}
    request.update(extra)
    return request


def use_real_renderers(context):
    """Exercise real summary/table rendering with a minimal DOM implementation."""
    context.eval("""
      class TestNode {
        constructor() { this.children = []; this.style = {}; this._text = ''; }
        append(...items) { this.children.push(...items); }
        get firstChild() { return this.children[0] || null; }
        removeChild(child) { this.children.splice(this.children.indexOf(child), 1); }
        set textContent(text) { this._text = String(text); this.children = []; }
        get textContent() {
          return this._text + this.children.map(c => typeof c === 'string' ? c : c.textContent).join('');
        }
        addEventListener() {}
      }
      const DOM = {};
      document.getElementById = id => DOM[id] || (DOM[id] = new TestNode());
      document.createElement = () => new TestNode();
      document.createTextNode = text => String(text);
      function css() { return '#000'; }
      let currentS0 = '0.10';
    """)
    for name in ("trimZeros", "fmtSig", "fmtDuration", "fmtVisibilityCount",
                 "fmtConfusion", "fmtS0", "tcleanText", "flagInfo", "rowHasBadFlag",
                 "clearNode", "addCell", "addSubarrayCell", "renderCalcSummary",
                 "renderCalcTable"):
        context.eval(function_source(name))


class TestReportBaselineRanking(unittest.TestCase):
    def test_controls_and_metric_columns_are_present(self):
        self.assertIn('<option value="efficient">', TEMPLATE)
        self.assertIn('<option value="performance">', TEMPLATE)
        self.assertIn("'science baselines'", TEMPLATE)
        self.assertIn("'efficiency'", TEMPLATE)
        self.assertIn("Baseline ranking is unavailable", TEMPLATE)

    def test_executed_template_metric_matches_python(self):
        geometry = {"n_ant": 3, "n_pairs": 3, "lengths_m": [1.0, 2.0, 3.0],
                    "provenance": {"source": "test"}}
        request = {"freq": .299792458,
                   "resolution": 206264.8 * 1.02 / 2,
                   "las": 206264.8 * .8 / 1.02}
        expected = baseline_metrics(geometry, request["freq"], request["resolution"],
                                    request["las"], .8)
        context = quickjs.Context()
        context.eval("function finitePositive(x) { return Number.isFinite(x) && x > 0; }")
        context.eval(re.search(r"const DEFAULT_LAS_RATIO = [^;]+;", TEMPLATE).group())
        context.eval(function_source("baselineMetric"))
        context.eval("DATA = " + json.dumps({"las": {"test": {"coeff": .8, "n_ant": 3}},
            "baseline_geometry": {"test": dict(geometry, status="ok")}}) + ";")
        actual = json.loads(context.eval("JSON.stringify(baselineMetric('test', %s))"
                                        % json.dumps(request)))
        for key in ("baseline_min_m", "baseline_max_m", "baseline_efficiency"):
            self.assertAlmostEqual(actual[key], expected[key])
        self.assertEqual(actual["baselines_in_range"], expected["baselines_in_range"])
        self.assertEqual(actual["baselines_total"], expected["baselines_total"])

    def test_python_browser_metric_parity_boundaries_frequency_and_coefficients(self):
        geometry = {"n_ant": 3, "n_pairs": 3, "lengths_m": [1.0, 2.0, 3.0],
                    "provenance": {"source": "test"}}
        for frequency, coeff, las, resolution in [
                (.299792458, .8, 206264.8 * .8 / 1, 206264.8 * 1.02 / 3),
                (.599584916, .4, 206264.8 * .4 / 2, 206264.8 * 1.02 / 2),
                (1.0, .9, None, 206264.8 * 1.02 / 1)]:
            with self.subTest(frequency=frequency, coeff=coeff, las=las):
                request = {"freq": frequency, "resolution": resolution, "las": las}
                expected = baseline_metrics(geometry, frequency, resolution, las, coeff)
                context = quickjs.Context()
                context.eval("function finitePositive(x) { return Number.isFinite(x) && x > 0; }")
                context.eval(re.search(r"const DEFAULT_LAS_RATIO = [^;]+;", TEMPLATE).group())
                context.eval(function_source("baselineMetric"))
                context.eval("DATA = " + json.dumps({"las": {"x": {"coeff": coeff, "n_ant": 3}},
                    "baseline_geometry": {"x": dict(geometry, status="ok")}}) + ";")
                actual = json.loads(context.eval("JSON.stringify(baselineMetric('x', %s))" %
                                                 json.dumps(request)))
                self.assertEqual(actual["baselines_in_range"], expected["baselines_in_range"])
                self.assertAlmostEqual(actual["baseline_efficiency"], expected["baseline_efficiency"])

    def test_run_calculator_orders_baseline_modes_and_respects_strict_first(self):
        geometry = {
            "main": {"n_ant": 3, "lengths_m": [100., 200., 600.], "provenance": {}},
            "main+long": {"n_ant": 4, "lengths_m": [100., 200., 300., 400., 500., 600.], "provenance": {}},
        }
        for rank, expected in (("efficient", "main"), ("performance", "main+long")):
            context = calculator_context(fixture_data(geometry), fixture_request(rank))
            context.eval("runSubarrayCalculator()")
            result = json.loads(context.eval("JSON.stringify(RESULT)"))
            self.assertEqual(result["winner"]["name"], expected)
        # The scores tie here, but imaging strict-first still precedes the
        # relaxed row; in a mixed point-source request DATA.order is stable.
        tied = fixture_data(geometry, order=("relaxed", "strict"))
        tied["las"] = {"strict": {"coeff": .8, "n_ant": 3, "mas": 1e9},
                       "relaxed": {"coeff": .8, "n_ant": 3, "mas": 1e9}}
        tied["baseline_geometry"] = {
            "strict": dict(geometry["main"], status="ok", n_pairs=3),
            "relaxed": dict(geometry["main"], status="ok", n_pairs=3)}
        context = calculator_context(tied, fixture_request("performance", obs="imaging"))
        context.eval("runSubarrayCalculator()")
        self.assertEqual(json.loads(context.eval("JSON.stringify(RESULT.winner.name)")), "strict")

    def test_time_ties_keep_data_order_and_unavailable_metrics_have_no_winner(self):
        geometry = {"main": {"n_ant": 3, "lengths_m": [100., 200., 600.], "provenance": {}},
                    "main+long": {"n_ant": 3, "lengths_m": [100., 200., 600.], "provenance": {}}}
        for rank in ("time", "antenna_hours"):
            context = calculator_context(fixture_data(geometry, order=("main+long", "main")),
                                         fixture_request(rank))
            context.eval("runSubarrayCalculator()")
            result = json.loads(context.eval("JSON.stringify(RESULT)"))
            self.assertEqual([row["name"] for row in result["rows"]], ["main+long", "main"])
        data = fixture_data(geometry)
        del data["baseline_geometry"]["main+long"]
        context = calculator_context(data, fixture_request("efficient"))
        context.eval("runSubarrayCalculator()")
        result = json.loads(context.eval("JSON.stringify(RESULT)"))
        self.assertIsNone(result["winner"])
        self.assertFalse(result["rankingAvailable"])
        self.assertFalse(result["tableRankingAvailable"])
        self.assertEqual([row["name"] for row in result["rows"]], ["main", "main+long"])

    def test_cost_and_mfs_failure_policy_executes_in_calculator(self):
        geometry = {"main": {"n_ant": 3, "lengths_m": [100., 200., 600.], "provenance": {}},
                    "main+long": {"n_ant": 4, "lengths_m": [100., 200., 300., 400., 500., 600.], "provenance": {}}}
        # Explicit sensitivity still rejects missing cost inputs.
        context = calculator_context(fixture_data(geometry), fixture_request("performance"),
                                     missing_sensitivity=True)
        context.eval("runSubarrayCalculator()")
        self.assertEqual(json.loads(context.eval("JSON.stringify(RESULT.rows)")), [])
        # Mono fiducial baseline ranking keeps geometry-ranked rows with blank costs.
        context = calculator_context(fixture_data(geometry), fixture_request(
            "performance", sensitivity=None, goalMode="fiducial"), missing_sensitivity=True)
        context.eval("runSubarrayCalculator()")
        result = json.loads(context.eval("JSON.stringify(RESULT)"))
        self.assertEqual(result["winner"]["name"], "main+long")
        self.assertTrue(all(row["tHours"] is None for row in result["rows"]))
        # A missing MAIN fiducial has the same mono baseline behavior.
        data = fixture_data(geometry, _missing_main=True)
        context = calculator_context(data, fixture_request("efficient", sensitivity=None, goalMode="fiducial"))
        context.eval("runSubarrayCalculator()")
        self.assertIsNotNone(json.loads(context.eval("JSON.stringify(RESULT.winner)")))
        # MFS cannot use this mono exception.
        data = fixture_data(geometry, fixed_window={"lo_ghz": 26, "hi_ghz": 30})
        context = calculator_context(data, fixture_request("performance", sensitivity=None, goalMode="fiducial"),
                                     missing_sensitivity=True)
        context.eval("runSubarrayCalculator()")
        self.assertEqual(json.loads(context.eval("JSON.stringify(RESULT.rows)")), [])
        # A non-finite calculated cost rejects just that candidate.
        context = calculator_context(fixture_data(geometry), fixture_request("performance"),
                                     bad_cost_name="main+long")
        context.eval("runSubarrayCalculator()")
        result = json.loads(context.eval("JSON.stringify(RESULT)"))
        self.assertEqual([row["name"] for row in result["rows"]], ["main"])

        # Implicit costs may fail without removing the baseline-ranked row.
        context = calculator_context(fixture_data(geometry), fixture_request(
            "performance", sensitivity=None, goalMode="fiducial"), bad_cost_name="main+long")
        context.eval("runSubarrayCalculator()")
        result = json.loads(context.eval("JSON.stringify(RESULT)"))
        self.assertEqual(result["winner"]["name"], "main+long")
        self.assertIsNone(result["rows"][0]["tHours"])
        self.assertIn("failed", result["rows"][0]["cost_error"])

        # Even with valid sensitivity data MFS requires a known confusion floor.
        for confusion, expected_rows in ((None, 0), (2., 0), (.1, 2)):
            data = fixture_data(geometry, fixed_window={"lo_ghz": 26, "hi_ghz": 30},
                                _confusion=confusion)
            context = calculator_context(data, fixture_request("performance"))
            context.eval("runSubarrayCalculator()")
            result = json.loads(context.eval("JSON.stringify(RESULT)"))
            self.assertEqual(len(result["rows"]), expected_rows)

    def test_zero_counts_and_exact_ties_are_ranked_but_inverted_bounds_are_not(self):
        geometry = {name: {"n_ant": 3, "lengths_m": [500., 600., 700.], "provenance": {}}
                    for name in ("main", "main+long")}
        for rank in ("efficient", "performance"):
            context = calculator_context(fixture_data(geometry, order=("main+long", "main")),
                                         fixture_request(rank))
            context.eval("runSubarrayCalculator()")
            result = json.loads(context.eval("JSON.stringify(RESULT)"))
            self.assertEqual(result["winner"]["name"], "main")
            self.assertEqual(result["winner"]["baseline"]["baselines_in_range"], 0)
            self.assertTrue(result["rankingAvailable"])
        context = calculator_context(fixture_data(geometry), fixture_request(las=.001))
        context.eval("runSubarrayCalculator()")
        result = json.loads(context.eval("JSON.stringify(RESULT)"))
        self.assertEqual(len(result["rows"]), 2)
        self.assertIsNone(result["winner"])
        self.assertFalse(result["rankingAvailable"])

    def test_real_renderers_show_counts_missing_costs_and_unavailable_rank(self):
        geometry = {"main": {"n_ant": 3, "lengths_m": [100., 200., 600.], "provenance": {}}}
        data = fixture_data(geometry, order=("main",))
        context = calculator_context(data, fixture_request(
            "performance", sensitivity=None, goalMode="fiducial"), missing_sensitivity=True)
        use_real_renderers(context)
        context.eval("runSubarrayCalculator()")
        summary = context.eval("DOM['calc-summary'].textContent")
        cells = json.loads(context.eval(
            "JSON.stringify(DOM['calc-table'].children[1].children.map(c => c.textContent))"))
        self.assertIn("performance 2 baselines", summary)
        self.assertEqual(cells[2], "—")
        self.assertEqual(cells[3], "— h")
        self.assertEqual(cells[5], "2/3")
        context.eval("delete DATA.baseline_geometry.main; runSubarrayCalculator()")
        self.assertEqual(context.eval("DOM['calc-summary'].textContent"), "Ranking unavailable.")
        self.assertEqual(context.eval("DOM['calc-table'].children[1].children[0].textContent"), "—")
        context.eval("DATA.order = []; runSubarrayCalculator()")
        self.assertEqual(context.eval("DOM['calc-summary'].textContent"),
                         "No subarray meets these requirements.")

    def test_flagged_rows_get_the_light_red_css_class(self):
        # 'relaxed' triggers p.relaxed = True in calculator_context's
        # lookupCurvePoint stub, which is exactly the flagInfo() "skirt limit
        # not met" case; 'clean' does not.
        geometry = {"clean": {"n_ant": 3, "lengths_m": [100., 200., 600.], "provenance": {}},
                    "relaxed": {"n_ant": 3, "lengths_m": [100., 200., 600.], "provenance": {}}}
        data = fixture_data(geometry, order=("clean", "relaxed"))
        context = calculator_context(data, fixture_request("performance", obs="imaging"))
        use_real_renderers(context)
        context.eval("runSubarrayCalculator()")
        rows = json.loads(context.eval(
            "JSON.stringify(DOM['calc-table'].children.slice(1).map("
            "tr => ({name: tr.children[1].textContent, className: tr.className || ''})))"))
        by_name = {row["name"]: row["className"] for row in rows}
        self.assertEqual(by_name["clean"], "")
        self.assertEqual(by_name["relaxed"], "calc-row-flagged")

    def test_css_class_applies_the_flag_row_tint_variable(self):
        self.assertIn("#calc-table tr.calc-row-flagged td { background: var(--flag-row); }",
                     TEMPLATE)
        self.assertIn("--flag-row:", TEMPLATE)

    def test_template_metric_marks_missing_and_inverted_geometry_unavailable(self):
        self.assertIn("status: 'unavailable'", function_source("baselineMetric"))
        self.assertIn("bMin > bMax", function_source("baselineMetric"))

    def test_real_packaged_geometry_parity_including_long_and_mid_long(self):
        """Close the parity gap: the earlier synthetic-geometry parity tests
        always had len(lengths) == n_ant*(n_ant-1)/2, so they never exercised
        a subarray filtered by MIN_UVRANGE_M and did not catch the W2.1 bug
        (validating against nAnt instead of the payload's own n_pairs), which
        made `long` and `mid+long` report {status:'unavailable', error:
        'invalid baseline geometry'} in the browser with real packaged
        geometry.  Run the real revF payload for long, mid+long, core and
        main through both engines and assert identical results, including
        status -- with and without a requested LAS.

        NOTE (11 Sep 2026 reversal): the MIN_UVRANGE_M cut this test
        originally guarded against is no longer applied to packaged geometry
        at all (see sa_select/baselines.py docstring), so len(lengths) ==
        n_ant*(n_ant-1)/2 again for every subarray including long and
        mid+long. The parity assertions below remain valid and worth
        keeping regardless of whether a cut is ever applied again.
        """
        geometry = load_baseline_geometry("revF")
        names = ["long", "mid+long", "core", "main"]
        for name in names:
            self.assertIn(name, geometry)
            entry = geometry[name]
            n_ant = entry["n_ant"]
            self.assertLessEqual(entry["n_pairs"], n_ant * (n_ant - 1) // 2)

        for las in (None, 5.0):
            for name in names:
                entry = geometry[name]
                with self.subTest(name=name, las=las):
                    expected = baseline_metrics(entry, 30.0, 0.01, las, 0.8)
                    context = quickjs.Context()
                    context.eval("function finitePositive(x) "
                                "{ return Number.isFinite(x) && x > 0; }")
                    context.eval(re.search(r"const DEFAULT_LAS_RATIO = [^;]+;",
                                          TEMPLATE).group())
                    context.eval(function_source("baselineMetric"))
                    context.eval("DATA = " + json.dumps({
                        "las": {name: {"coeff": .8, "n_ant": entry["n_ant"]}},
                        "baseline_geometry": {name: dict(entry, status="ok")}}) + ";")
                    request = {"freq": 30.0, "resolution": 0.01, "las": las}
                    actual = json.loads(context.eval(
                        "JSON.stringify(baselineMetric(%s, %s))"
                        % (json.dumps(name), json.dumps(request))))
                    self.assertEqual(actual["status"], "ok")
                    self.assertEqual(actual["baselines_in_range"],
                                     expected["baselines_in_range"])
                    self.assertEqual(actual["baselines_total"],
                                     expected["baselines_total"])
                    self.assertAlmostEqual(actual["baseline_efficiency"],
                                           expected["baseline_efficiency"])
                    self.assertEqual(actual["baseline_las_defaulted"],
                                     expected["baseline_las_defaulted"])
                    self.assertAlmostEqual(actual["baseline_las_arcsec"],
                                           expected["baseline_las_arcsec"])

    def test_default_las_note_only_for_efficient_and_performance(self):
        geometry = {"main": {"n_ant": 3, "lengths_m": [100., 200., 600.],
                             "provenance": {}}}
        for rank, expect_note in (("efficient", True), ("performance", True),
                                  ("antenna_hours", False), ("time", False)):
            data = fixture_data(geometry, order=("main",))
            context = calculator_context(data, fixture_request(rank))
            use_real_renderers(context)
            context.eval("runSubarrayCalculator()")
            summary = context.eval("DOM['calc-summary'].textContent")
            if expect_note:
                self.assertIn("No LAS was requested", summary, rank)
            else:
                self.assertNotIn("No LAS was requested", summary, rank)

    def test_las_input_is_never_assigned_a_value(self):
        """Ghost-value guard (bmason's hard constraint): the LAS input box
        must stay visibly blank -- the default is an assumption of the
        metric, not a user input, and must never look like one."""
        occurrences = [m.start() for m in re.finditer(r"calc-las", TEMPLATE)]
        # Exactly the <input id="calc-las" ...> tag and the single
        # readCalcNumber('calc-las', ...) read call -- nothing writes to it.
        self.assertEqual(len(occurrences), 2, occurrences)
        self.assertIn('id="calc-las"', TEMPLATE)
        self.assertIn("readCalcNumber('calc-las'", TEMPLATE)
        self.assertNotIn("calc-las').value =", TEMPLATE)
        self.assertNotIn('calc-las").value =', TEMPLATE)
        self.assertNotIn("calc-las').placeholder =", TEMPLATE)
        self.assertNotIn("calc-las\"].value =", TEMPLATE)

        # Functional guard: the real read path (readCalcNumber via
        # readCalcRequest) never writes back to the element it reads from.
        context = quickjs.Context()
        context.eval(re.search(r"const CALC_RECEIVER_BANDS = [^;]+;", TEMPLATE).group())
        context.eval("""
          const ELEMENTS = {
            'calc-las': {value: '', placeholder: 'optional'},
            'calc-freq': {value: '30'}, 'calc-res': {value: '0.01'},
            'calc-bandwidth': {value: '1000'}, 'calc-sens': {value: ''},
            'calc-obs': {value: 'imaging'}, 'calc-rank': {value: 'efficient'},
            'calc-sens-unit': {value: 'uJy'}, 'calc-beam-margin': {value: '0.05'},
            'calc-s0': {value: '0.10'},
          };
          const document = {getElementById: id => ELEMENTS[id]};
        """)
        context.eval(function_source("finitePositive"))
        context.eval(function_source("inReceiverBand"))
        context.eval(function_source("readCalcNumber"))
        context.eval(function_source("readCalcRequest"))
        result = json.loads(context.eval("JSON.stringify(readCalcRequest())"))
        self.assertIsNone(result["request"]["las"])
        self.assertEqual(context.eval("ELEMENTS['calc-las'].value"), "")
        self.assertEqual(context.eval("ELEMENTS['calc-las'].placeholder"), "optional")


class TestReportCollapsibleSections(unittest.TestCase):
    """UX pass (Sep 2026): static explanatory prose collapses behind
    <details class="explain"><summary>Explanation</summary>. The four
    diagnostic cards are NOT collapsed -- they stay fully visible, set off
    by a DIAGNOSTICS section heading and rule (scope change: bmason wants
    layout separation here, not a collapse)."""

    EXPECTED_EXPLANATIONS = [
        "These plots show sensitivity cost",           # header .sub, ~L201
        "Use the same tabulated curves as the plots",   # subarray calculator, ~L220
        "The times use the thermal-noise part",         # calc-caveat, ~L284
        "At each target resolution, the curve shows",   # imaging card, ~L327
        "These curves include all beams",               # point-source card, ~L341
        'id="samples-resolution-note"',                 # ~L358
        'id="samples-parameters-note"',                 # ~L363
        "Each plot shows the full sweep grid",           # ~L376
        "Select a subarray to examine its measured PSF", # ~L389
        "This table compares the simulated native beam", # ~L404
    ]

    EXCLUDED_FROM_EXPLANATIONS = [
        'id="combo-note"',
        'id="imaging-omitted-note"',
        'id="psf-params"',
    ]

    def _explain_blocks(self):
        return re.findall(r'<details class="explain">.*?</details>', TEMPLATE, re.S)

    def test_listed_prose_blocks_are_wrapped_in_explanation_details(self):
        blocks = self._explain_blocks()
        self.assertTrue(blocks, "no <details class=\"explain\"> blocks found")
        for marker in self.EXPECTED_EXPLANATIONS:
            self.assertTrue(any(marker in b for b in blocks),
                             "%r not found inside any Explanation details" % marker)

    def test_dynamic_and_warning_notes_are_not_wrapped(self):
        blocks = self._explain_blocks()
        for marker in self.EXCLUDED_FROM_EXPLANATIONS:
            self.assertFalse(any(marker in b for b in blocks),
                              "%r must stay outside any Explanation details" % marker)
        # Also confirm they're still present in the page at all (not deleted).
        for marker in self.EXCLUDED_FROM_EXPLANATIONS:
            self.assertIn(marker, TEMPLATE)

    def test_samples_notes_share_one_explanation_details(self):
        # Both notes must live in the SAME <details class="explain"> block
        # (one Explanation covering both dropdown views), per the design
        # decision to keep the display:none toggle logic untouched.
        blocks = self._explain_blocks()
        shared = [b for b in blocks
                  if 'id="samples-resolution-note"' in b
                  and 'id="samples-parameters-note"' in b]
        self.assertEqual(len(shared), 1,
                          "expected exactly one Explanation details containing both samples notes")

    def test_diagnostics_heading_and_rule_precede_the_four_sections(self):
        # A visual divider (rule + heading), not a collapse: find the four
        # section markers and confirm a "DIAGNOSTICS" heading with a
        # preceding <hr> sits right before the first of them ("Valid
        # simulation results"), in document order.
        markers = ["Valid simulation results",
                   "Sweep grid in robust and taper space",
                   'id="psf-inspector"',
                   "Subarray summary and native-beam checks"]
        positions = [TEMPLATE.index(m) for m in markers]
        self.assertEqual(positions, sorted(positions),
                          "diagnostic sections are not in the expected order")

        heading_pos = TEMPLATE.index('id="diagnostics-heading"')
        self.assertLess(heading_pos, positions[0],
                         "DIAGNOSTICS heading must precede the diagnostic sections")
        between = TEMPLATE[heading_pos:positions[0]]
        self.assertIn("DIAGNOSTICS", between)

        rule_pos = TEMPLATE.rfind("<hr", 0, heading_pos)
        self.assertNotEqual(rule_pos, -1, "expected an <hr> before the DIAGNOSTICS heading")
        # Nothing but whitespace/markup between the rule and the heading --
        # i.e. the rule directly introduces this section, not some earlier one.
        gap = TEMPLATE[rule_pos:heading_pos]
        self.assertNotIn("<div", gap)
        self.assertNotIn("</div>", gap[:gap.index('<h2')] if '<h2' in gap else gap)

    def test_four_diagnostic_sections_are_not_collapsed(self):
        # None of the four section headings/ids may be nested inside a
        # <details> element (the earlier "collapse into Diagnostics" design
        # was replaced with plain layout separation).
        for marker in ("<h2>Valid simulation results</h2>",
                       "<h2>Sweep grid in robust and taper space</h2>",
                       '<div class="card" id="psf-inspector">',
                       "<h2>Subarray summary and native-beam checks</h2>"):
            pos = TEMPLATE.index(marker)
            # Nearest preceding <details ...> (opening, not closing) must not
            # remain unclosed by the time we reach this marker.
            preceding = TEMPLATE[:pos]
            opens = len(re.findall(r"<details\b", preceding))
            closes = len(re.findall(r"</details>", preceding))
            self.assertEqual(opens, closes,
                              "%r appears to be nested inside an open <details>" % marker)
        self.assertNotIn('<details id="diagnostics">', TEMPLATE)


class TestSamplesViewToggleInsideExplanation(unittest.TestCase):
    """The #samples-view-select dropdown swaps which of the two samples
    notes is visible via style.display; wrapping both in one collapsed
    <details> must not disturb that. Executes the real renderMultiples()
    (with chart-building helpers stubbed out -- only the note-visibility
    lines at its top are under test) via quickjs."""

    def _context(self):
        context = quickjs.Context()
        context.eval("""
          const ELEMENTS = {
            'samples-resolution-note': {style: {display: ''}},
            'samples-parameters-note': {style: {display: ''}},
            'multiples': {innerHTML: ''},
          };
          const document = {getElementById: id => ELEMENTS[id]};
          function clearNode(el) {}
          function resolutionEtaMultiple() {}
          function parameterMultiple() {}
          let ACTIVE = ['main'];
        """)
        context.eval(function_source("renderMultiples"))
        return context

    def test_resolution_view_shows_resolution_note_only(self):
        context = self._context()
        context.eval("currentSamplesView = 'resolution'; renderMultiples();")
        self.assertEqual(context.eval("ELEMENTS['samples-resolution-note'].style.display"), "")
        self.assertEqual(context.eval("ELEMENTS['samples-parameters-note'].style.display"), "none")

    def test_parameters_view_shows_parameters_note_only(self):
        context = self._context()
        context.eval("currentSamplesView = 'parameters'; renderMultiples();")
        self.assertEqual(context.eval("ELEMENTS['samples-resolution-note'].style.display"), "none")
        self.assertEqual(context.eval("ELEMENTS['samples-parameters-note'].style.display"), "")


if __name__ == "__main__":
    unittest.main()
