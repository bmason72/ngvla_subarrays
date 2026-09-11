
-curveRefactor: refactor to make the curves the basic product - no need to carry around
   all the sime. is the npts small enough that we could keep the full PSF? 
   or inner part thereof

-curveLimits: manually specified valid range per curve

-more parallelism for the sweep and refine - use pylauncher to keep node busy until
   closer to the end for instance. scatter across more nodes per slurm job.
   the user level limit of 8 jobs in the queue is a real pace setter for getting
   things done, and there are many nodes available here.

-add spiral+5, spiral+10, SBA (fixed), LONG combos (filtering short baselines involving LONG at minimum).

-run rest of subarrays on RevF MFS

-add declination support (bmason, 10 Sep 2026): evaluate whether simulations and
   their derived curves can be scaled to other declinations, and establish the
   accuracy and limits of that approximation. This is broader than the
   efficient/performance baseline bounds: assess resolution, projected uv
   coverage, beam asymmetry, weighting/taper response and PSF quality generally.
   Simple scaling may be sufficient, but that is a hypothesis to evaluate.
   Future development only; outside the current ranking change.

===========
actually maintenance tasks

-review documentation to ensure it is clear, states the essential conceptual points,
   and lacks ambiguities which would confuse humans or LLMs.

-make an ngvla imaging skill (general)

-add alma data skill, krishna+preshanth data skills

