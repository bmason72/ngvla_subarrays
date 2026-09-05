
My instructions defining our high level goal now (17aug2026).
This supercedes the previous docs/plans/PLAN.md and docs/plans/NEXT_AGENT.md where in conflict
and may in particular apply a narrower scope of activities in some respects.

1- New goal: release the calculator web and python prototypes 
     only for RevF (4h track; ptsrc and imaging), RevD (4h track; ptsrc), and RevC (4h track; ptsrc).
   The last, RevC is an addition. The snapshot and other use cases are not sufficiently
   mature, and we need to get something out for now.

   The motivation for this scope specifically is that i would like to be able to
   reproduce the current envelope observing program https://ngvla.nrao.edu/download/MediaFile/260/original
   and run it for revF (point source) as well as revF(imaging, for cases that need it).
   This is a near future activity.

2- refine the web page a little.
    -make imaging curves section "Omitted/Intentionally blank" for campaigns i specified to skip them.
    -remove the following caveat:  core+mid is omitted from this report — its two-component beam needs sculpt targets anchored to the higher-resolution component (the v1 sweep found false minima there). The color slot is reserved; curves can drop in without re-mapping the others.

3- if we have the data products on hand for it, add PSF cuts to the 
    web page, as previously discussed. if it involves more sim runs
   besides the revC point source runs, skip it. This should really
   only be done if it's really quite close already, i'm tempted to
   completely descope it in order to get an MVP out sooner.

4- Review and update all documentation, including MD files and the
   latex memo. The latex memo should include concise instructions on
   how to run the campaigns and code to generate reports (and underlying data products).
   It should also document the interface to the python calculator.
 
   The latex document in particular could use a solid editorial pass
    with the writing guidelines below.

5- If possible, in all of this, i'd like to support MStroh style subarray
   input files (the format he gave sensitity curves in). do not descope
   core functionality or break things to make this happen.

GUIDELINES
===========

write in ASD-STE100, or Simplified Technical English; and
follow Zinsser's four principles of quality writing:
1. Simplicity
2. Brevity
3. Clarity
4. Humanity (where relevant/applicable)

Use subagents of equal or lower capability for well specified tasks (e.g. implementation, testing).

Use the claude-codex-bridge here to invoke codex for well specified tasks, or (using sol) as a thinking partner.

