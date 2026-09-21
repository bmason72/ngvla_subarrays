"""CASA-free contracts for campaign_tasks.py's job topology, the
NGVLA_SUBARRAYS opt-in subset flag (D14), and the fail-closed offered-set
preflight (S3) -- see docs/plans/spiral-plus-campaign-plan.md.

campaign_tasks.py only imports config (not CASA), so these run under plain
python (sys.executable), matching the precedent in
tests.test_mfs_campaign.TestSubmitCampaignModeSwitch.
"""

import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CURVEGEN = ROOT / "curvegen"


def run_ct(cmd, subarrays=None, subarrays_n=None, rev="revF", sim_mode="track"):
    env = dict(os.environ, NGVLA_REV=rev, NGVLA_SIM_MODE=sim_mode,
              NGVLA_BAND="")
    if subarrays is None:
        env.pop("NGVLA_SUBARRAYS", None)
    else:
        env["NGVLA_SUBARRAYS"] = subarrays
    if subarrays_n is None:
        env.pop("NGVLA_SUBARRAYS_N", None)
    else:
        env["NGVLA_SUBARRAYS_N"] = str(subarrays_n)
    return subprocess.run(
        [sys.executable, "campaign_tasks.py", cmd], cwd=str(CURVEGEN),
        text=True, capture_output=True, env=env)


class TestSubarraySubsetFlag(unittest.TestCase):

    def test_unset_groups_unchanged_for_revF_track(self):
        proc = run_ct("groups")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        lines = proc.stdout.strip("\n").split("\n")
        # baseline layout: 5 heavy (long-containing) subarrays get their own
        # task, then one grouped task for everything else offered
        self.assertEqual(lines[:5], ["long", "mid+long", "spiral+mid+long",
                                     "main+long",
                                     "long+mid+spiral+core-outer"])
        light = lines[5].split()
        for name in ("core-inner", "core", "spiral", "mid", "core+spiral",
                    "spiral+mid", "main", "spiral+core-outer",
                    "mid+spiral+core-outer"):
            self.assertIn(name, light)
        self.assertEqual(len(lines), 6)

    def test_unset_narray_unchanged(self):
        proc = run_ct("narray")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), "6")

    def test_two_name_subset_narrows_groups_narray_seeds(self):
        proc = run_ct("groups", subarrays="spiral+5,spiral+10")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        lines = proc.stdout.strip("\n").split("\n")
        # both light (b_max well under the heavy threshold) -> one grouped task
        self.assertEqual(lines, ["spiral+5 spiral+10"])

        proc = run_ct("narray", subarrays="spiral+5,spiral+10")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), "1")

        proc = run_ct("seeds", subarrays="spiral+5,spiral+10")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        seeds = proc.stdout.strip().split()
        self.assertEqual(set(seeds), {"spiral+5", "spiral+10"})

    def test_subset_with_a_heavy_name_puts_it_in_its_own_task(self):
        proc = run_ct("groups", subarrays="spiral+5 long")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        lines = proc.stdout.strip("\n").split("\n")
        self.assertEqual(lines, ["long", "spiral+5"])

    def test_comma_and_space_separated_forms_both_work(self):
        comma = run_ct("groups", subarrays="spiral+5,spiral+10")
        space = run_ct("groups", subarrays="spiral+5 spiral+10")
        mixed = run_ct("groups", subarrays="spiral+5, spiral+10")
        self.assertEqual(comma.returncode, space.returncode, 0)
        self.assertEqual(comma.stdout, space.stdout)
        self.assertEqual(comma.stdout, mixed.stdout)

    def test_colon_separated_form_also_works_and_matches(self):
        # this is what submit_campaign.sh actually exports (S2 hardening):
        # a single colon-joined token, safe inside Slurm's comma-delimited
        # --export string
        colon = run_ct("groups", subarrays="spiral+5:spiral+10")
        comma = run_ct("groups", subarrays="spiral+5,spiral+10")
        self.assertEqual(colon.returncode, 0, colon.stderr)
        self.assertEqual(colon.stdout, comma.stdout)

    def test_colon_comma_space_mixed_form_works(self):
        mixed = run_ct("groups", subarrays="spiral+5: spiral+10,mid+spiral+5")
        self.assertEqual(mixed.returncode, 0, mixed.stderr)
        lines = mixed.stdout.strip("\n").split("\n")
        self.assertEqual(set(lines[-1].split()) | (set(lines[:-1])),
                          {"spiral+5", "spiral+10", "mid+spiral+5"})

    def test_unknown_name_fails_closed_with_valid_name_list(self):
        proc = run_ct("groups", subarrays="not_a_real_subarray")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("not_a_real_subarray", proc.stderr)
        self.assertIn("valid names are:", proc.stderr)
        self.assertIn("spiral", proc.stderr)   # a real offered name is listed

    def test_unknown_name_among_known_ones_still_fails_closed(self):
        # a silent drop of just the bad name would produce a smaller job
        # array than the operator asked for -- the whole request must fail
        proc = run_ct("groups", subarrays="spiral+5,not_a_real_subarray")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("not_a_real_subarray", proc.stderr)
        self.assertNotIn("spiral+5", proc.stdout)

    def test_row_order_preserved_for_kept_names(self):
        # request out of CSV order; the kept names must come back in the
        # CSV's order, not the request's order
        proc = run_ct("seeds", subarrays="mid+spiral+10,spiral+5")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        seeds = proc.stdout.strip().split()
        self.assertEqual(seeds, ["spiral+5", "mid+spiral+10"])


class TestSubsetPropagationFailsClosed(unittest.TestCase):
    """S2 hardening: NGVLA_SUBARRAYS_N is a companion count that lets
    _requested_subarrays detect a propagation failure (NGVLA_SUBARRAYS
    arriving empty or truncated at a stage) and abort instead of silently
    falling back to "no restriction"."""

    def test_matching_count_works_normally(self):
        proc = run_ct("groups", subarrays="spiral+5,spiral+10", subarrays_n=2)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip("\n").split("\n"),
                         ["spiral+5 spiral+10"])

    def test_zero_count_with_empty_list_is_unrestricted(self):
        # this is what submit_campaign.sh exports by default (no --subarrays
        # given): NGVLA_SUBARRAYS="" and NGVLA_SUBARRAYS_N="0" -- must behave
        # exactly like both being unset
        restricted = run_ct("groups", subarrays="", subarrays_n=0)
        unset = run_ct("groups")
        self.assertEqual(restricted.returncode, 0, restricted.stderr)
        self.assertEqual(restricted.stdout, unset.stdout)

    def test_nonzero_count_with_empty_list_aborts(self):
        # the exact failure this hardening targets: the restriction was
        # requested (N=2) but NGVLA_SUBARRAYS never arrived at this stage
        proc = run_ct("groups", subarrays="", subarrays_n=2)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("failed to propagate", proc.stderr)
        self.assertIn("NGVLA_SUBARRAYS_N", proc.stderr)

    def test_nonzero_count_disagreeing_with_list_length_aborts(self):
        # truncation: only one of the two requested names survived
        proc = run_ct("groups", subarrays="spiral+5", subarrays_n=2)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("failed to propagate", proc.stderr)

    def test_neither_set_is_byte_identical_to_todays_revF_track_output(self):
        # both NGVLA_SUBARRAYS and NGVLA_SUBARRAYS_N unset must reproduce
        # exactly the same baseline the pre-S2 tests assert (D14: no change
        # in behaviour when the flag is not used)
        groups = run_ct("groups")
        narray = run_ct("narray")
        seeds = run_ct("seeds")
        for proc in (groups, narray, seeds):
            self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(groups.stdout.strip("\n").split("\n")[:5],
                         ["long", "mid+long", "spiral+mid+long", "main+long",
                          "long+mid+spiral+core-outer"])
        self.assertEqual(len(groups.stdout.strip("\n").split("\n")), 6)
        self.assertEqual(narray.stdout.strip(), "6")
        self.assertIn("core-outer", seeds.stdout.split())


class TestCollectIgnoresSubsetFlag(unittest.TestCase):

    def test_offered_subarrays_ignores_NGVLA_SUBARRAYS(self):
        code = (
            "import os\n"
            "os.environ['NGVLA_SUBARRAYS'] = 'spiral+5'\n"
            "import collect\n"
            "offered = collect.offered_subarrays()\n"
            "assert 'spiral+5' in offered\n"
            "assert 'main' in offered, offered\n"
            "assert 'long' in offered, offered\n"
            "print(len(offered))\n"
        )
        env = dict(os.environ, NGVLA_REV="revF", NGVLA_SIM_MODE="track",
                  NGVLA_BAND="", NGVLA_SUBARRAYS="spiral+5")
        proc = subprocess.run([sys.executable, "-c", code], cwd=str(CURVEGEN),
                              text=True, capture_output=True, env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        # the full offered set, not just the one name in NGVLA_SUBARRAYS
        self.assertGreater(int(proc.stdout.strip()), 1)

    def test_collect_module_never_reads_the_env_var(self):
        text = (CURVEGEN / "collect.py").read_text()
        # the flag may only appear in prose (the deliberate-omission comment),
        # never as something collect.py actually reads
        self.assertNotIn("os.environ[\"NGVLA_SUBARRAYS\"]", text)
        self.assertNotIn("os.environ.get(\"NGVLA_SUBARRAYS\"", text)
        self.assertNotIn("os.environ['NGVLA_SUBARRAYS']", text)
        self.assertNotIn("os.environ.get('NGVLA_SUBARRAYS'", text)
        # the comment documenting the deliberate omission must be present
        self.assertIn("NGVLA_SUBARRAYS", text)
        self.assertIn("D14", text)


def _extract_normalization_block():
    """Pull the exact --subarrays-normalization-through-EXP lines out of
    submit_campaign.sh, so this test proves the *real* script logic (not a
    reimplementation of it) never lets a space or comma from the operator's
    --subarrays value reach the comma-delimited --export string."""
    text = (CURVEGEN / "submit_campaign.sh").read_text()
    start = text.index('SUBARRAYS_TOKEN=""')
    end = text.index('EXP="ALL,')
    end = text.index("\n", end) + 1
    return text[start:end]


def _run_normalization(subarrays):
    """Dry-run just the extracted block under bash, with the other EXP
    ingredients pinned to fixed values, and echo EXP."""
    script = (
        "set -euo pipefail\n"
        "REV=revF; MODE=track; BAND=\"\"\n"
        "RBUDGET=60; RROUNDS=3; RSCAN=8\n"
        "SUBARRAYS=%s\n"
        "NGVLA_SCRATCH=/dummy/scratch\n"
        "NGVLA_MS_BASE=/dummy/ms\n"
        "%s"
        "echo \"EXP=$EXP\"\n"
    ) % (subarrays, _extract_normalization_block())
    return subprocess.run(["bash", "-c", script], text=True,
                          capture_output=True)


class TestSubmitCampaignShellNormalization(unittest.TestCase):
    """Shell-level proof (S2 hardening) that a space or comma typed after
    --subarrays cannot survive into the comma-delimited --export string."""

    def test_space_form_produces_a_space_free_colon_joined_EXP(self):
        proc = _run_normalization('"spiral+5 spiral+10"')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        exp_line = [l for l in proc.stdout.splitlines() if l.startswith("EXP=")][0]
        self.assertIn("NGVLA_SUBARRAYS=spiral+5:spiral+10", exp_line)
        self.assertIn("NGVLA_SUBARRAYS_N=2", exp_line)
        self.assertNotIn(" ", exp_line)

    def test_comma_form_also_produces_a_space_free_colon_joined_EXP(self):
        proc = _run_normalization('"spiral+5,spiral+10"')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        exp_line = [l for l in proc.stdout.splitlines() if l.startswith("EXP=")][0]
        self.assertIn("NGVLA_SUBARRAYS=spiral+5:spiral+10", exp_line)
        self.assertNotIn(" ", exp_line)

    def test_no_subarrays_gives_empty_token_and_zero_count(self):
        proc = _run_normalization('""')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        exp_line = [l for l in proc.stdout.splitlines() if l.startswith("EXP=")][0]
        self.assertIn("NGVLA_SUBARRAYS=,", exp_line)
        self.assertIn("NGVLA_SUBARRAYS_N=0,", exp_line)

    def test_name_containing_colon_is_rejected(self):
        proc = _run_normalization('"spiral+5:bad"')
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("not allowed", proc.stderr)

    def test_colon_embedded_name_rejected_even_mixed_with_good_names(self):
        # a bad name anywhere in the list must fail the whole request, not
        # just get silently dropped (same fail-closed principle as the
        # Python-side unknown-name test)
        proc = _run_normalization('"spiral+5 bad:name spiral+10"')
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("not allowed", proc.stderr)


class TestOfferedSetPreflight(unittest.TestCase):
    """S3: every offered subarray must be buildable (config.SUBARRAYS) and
    sizeable (config.IMSIZE) before any node is allocated."""

    def test_groups_rejects_an_offered_name_missing_from_config(self):
        code = (
            "import os\n"
            "os.environ.update(NGVLA_REV='revF', NGVLA_SIM_MODE='track', "
            "NGVLA_BAND='')\n"
            "import campaign_tasks as ct\n"
            "try:\n"
            "    ct._check_buildable(['spiral', 'not_a_config_subarray'])\n"
            "except SystemExit as exc:\n"
            "    print('EXIT', exc)\n"
            "else:\n"
            "    raise AssertionError('expected SystemExit')\n"
        )
        proc = subprocess.run([sys.executable, "-c", code], cwd=str(CURVEGEN),
                              text=True, capture_output=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("not_a_config_subarray", proc.stdout)
        self.assertIn("config.SUBARRAYS", proc.stdout)
        self.assertIn("config.IMSIZE", proc.stdout)

    def test_groups_names_which_mapping_is_missing(self):
        code = (
            "import os\n"
            "os.environ.update(NGVLA_REV='revF', NGVLA_SIM_MODE='track', "
            "NGVLA_BAND='')\n"
            "import campaign_tasks as ct\n"
            "import config\n"
            "assert 'spiral' in config.SUBARRAYS and 'spiral' in config.IMSIZE\n"
            "# simulate: buildable but not sizeable\n"
            "del config.IMSIZE['spiral']\n"
            "try:\n"
            "    ct._check_buildable(['spiral'])\n"
            "except SystemExit as exc:\n"
            "    msg = str(exc)\n"
            "    assert 'config.IMSIZE' in msg, msg\n"
            "    assert 'config.SUBARRAYS' not in msg, msg\n"
            "else:\n"
            "    raise AssertionError('expected SystemExit')\n"
            "print('ok')\n"
        )
        proc = subprocess.run([sys.executable, "-c", code], cwd=str(CURVEGEN),
                              text=True, capture_output=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("ok", proc.stdout)

    def test_full_offered_set_is_buildable_today(self):
        # the actual revF/track groups() call must succeed end to end -- this
        # is the "fires before any node is allocated" wiring, exercised for
        # real against the current metadata CSV + config.
        proc = run_ct("groups")
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_preflight_does_not_fire_on_seed_only_cap_references(self):
        # seed_set() deliberately includes non-offered cap references (e.g.
        # core-outer backs spiral+core-outer's cap); the preflight is wired
        # into groups(), not seed_set(), so it must never reject those.
        text = (CURVEGEN / "campaign_tasks.py").read_text()
        groups_body = re.search(r"def groups\(\):.*?(?=\ndef |\Z)", text,
                                re.S).group(0)
        seeds_body = re.search(r"def seed_set\(\):.*?(?=\ndef |\Z)", text,
                               re.S).group(0)
        self.assertIn("_check_buildable", groups_body)
        self.assertNotIn("_check_buildable", seeds_body)
        # and, for real: seed_set() must still succeed even though it
        # includes core-outer (a non-offered cap reference).
        proc = run_ct("seeds")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("core-outer", proc.stdout.split())


if __name__ == "__main__":
    unittest.main()
