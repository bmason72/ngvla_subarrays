
Work plan for the human plus feature backlog (7jul26)

*review results with full sweeps complete and bi-linear interp implemented
*code change: don't prune / remove the grid - fully sample (not a mode, a change)
  --delete legacy code and reg-test
*switch to iterative relaxtion of s (0.1, 0.12, ... )
*after all this, if it still looks janky - do we need smaller robust steps? (0.4 is kind of big)
*step up the parallelization.
*add python API - ngECT friendly
 -show it ngECT
*add spiral+5, spiral+10, SBA (fixed), LONG combos (filtering short baselines involving LONG at minimum).
*clean up memo
 -add figures

after that, run RevD



