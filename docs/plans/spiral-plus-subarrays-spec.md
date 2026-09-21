# Spec: spiral+5 and spiral+10 subarrays (Rev F)

Status: worker spec, 7 Sep 2026 (Fable orchestrator, from bmason's definition
the same day).  Build in the worktree
`/work2/10240/bmason72/stampede3/ngvla_wt_spiral` (branch
`feature/spiral-plus`); merge to `main` only after the running campaign's
collect stage has finished and been checked (the subarray metadata CSVs are
read by collect).

## Definition (bmason, 7 Sep 2026)

The Rev F spiral has five arms, labelled in the station names `spa`, `spb`,
`spc`, `spd`, `spe` (`ngvla-configurations/Rev F/CASA Files/RevF_Spiral_2025_01_16_xyz.cfg`,
54 stations).  The core is `RevF_Core_2025_01_27_xyz.cfg` (114 stations,
`cor001`...).

- **spiral+5** = spiral plus one core antenna per arm: for each arm, the core
  antenna closest to that arm's innermost spiral station.
- **spiral+10** = spiral+5 plus, for each arm, the next core antenna inward:
  treat the antenna chosen for spiral+5 as the arm's new tip and take the
  closest not-yet-chosen core antenna to it.

Operational rule to implement (orchestrator's reading of "closest (radially,
from the core center)"; the plot and table below let bmason check it):

1. Work in a local East-North tangent plane centred on the core centroid
   (mean of the 114 core positions).  Radius r = distance from that centroid.
2. Innermost station of an arm = the arm's station with the smallest r.
3. Per arm, the chosen core antenna is the unselected core antenna with the
   smallest tangent-plane distance to the arm's current tip.  Process arms in
   order a..e; an antenna, once chosen, is unavailable to other arms.
4. Record for every choice: arm, tip station, chosen antenna, distance
   tip-to-antenna, r of the antenna, r of the tip, azimuth difference.

## Deliverables

1. `curvegen/make_spiral_plus.py` (CASA-free; numpy only): reads the two Rev F
   cfg files, applies the rule, writes the selection table
   `sa_select/data/spiral_plus_selection.csv` (columns as in rule 4 plus a
   `set` column `+5`/`+10`) and prints it.  Deterministic; a `--plot PATH`
   option writes the figure below.
2. Subarray definitions: add `spiral+5` and `spiral+10` for Rev F wherever
   the existing composite subarrays (e.g. `core+spiral`, `spiral+mid`) are
   defined (find the mechanism in `curvegen/config.py` and the cfg writer;
   follow it exactly).  Membership = the spiral cfg plus the selected core
   stations by name.
3. Metadata rows: add both subarrays to every Rev F subarray-metadata CSV
   that lists the composite subarrays (`sa_select/data/subarrays_revf_*.csv`,
   including the MFS band4 ones), following how the existing rows were
   produced (look for a generator script; if rows were hand-made, compute
   N_ant, b_min, b_max and any derived columns the same way the existing
   code computes them, and leave measured columns such as beam caps blank).
   Do NOT add them to the release or offered sets unless the existing rows
   distinguish "defined" from "offered"; if they do, mark these as defined
   only.
4. Figure `docs/figures/spiral_plus_selection.png` (matplotlib, Agg
   backend): core antennas as small grey points, the first three or four
   stations of each spiral arm as coloured points labelled by station name,
   the +5 choices as large filled markers in the arm's colour, the +10
   additions as large open markers in the arm's colour, arrows from each tip
   to its chosen antenna, equal aspect, axes in km East/North relative to the
   core centroid, a legend, and an inset or second panel zoomed to the core
   edge if the full view is too crowded.  Title states the rule in one line.
5. Tests (CASA-free): rule gives exactly 5 and 10 distinct core antennas;
   no antenna chosen twice; every +5 antenna is a core station; the +10 set
   contains the +5 set; config exposes the two subarrays with the right
   antenna counts (54+5, 54+10); metadata rows parse.
6. Docs: `docs/worklog/spiral-plus.md` per `docs/worklog/README.md` with the
   selection table pasted and the interpretation of "closest" stated as an
   assumption for bmason to confirm; one line in `README.md`'s subarray list
   if one exists.

## Out of scope

Running any campaign for these subarrays; other revisions; LONG combos.
