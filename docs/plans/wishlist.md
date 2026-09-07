
-curveRefactor: refactor to make the curves the basic product - no need to carry around
   all the sime. is the npts small enough that we could keep the full PSF? 
   or inner part thereof

-curveLimits: manually specified valid range per curve

-more parallelism for the sweep and refine - use pylauncher to keep node busy until
   closer to the end for instance. scatter across more nodes per slurm job.
   the user level limit of 8 jobs in the queue is a real pace setter for getting
   things done, and there are many nodes available here.

===========
actually maintenance tasks

-review documentation to ensure it is clear, states the essential conceptual points,
   and lacks ambiguities which would confuse humans or LLMs.

-make an ngvla imaging skill (general)

-add alma data skill, krishna+preshanth data skills


