# Why large eta jumps occur

The main cause is coarse sampling of a constrained optimum—not necessarily
a genuinely discontinuous sensitivity curve.

Eta is minimized subject to achieving a requested resolution and, for the
imaging curve, approximately `skirt <= 0.10`. As resolution changes, the
best solution tends to move continuously through `(robust, taper)` space,
often riding close to that skirt boundary.

The large artificial jumps arise when the coarse grid fails to follow that
moving optimum.

## 1. Switching between coarse grid families

The base robust spacing is `0.4`, with relatively sparse logarithmic
tapers. Suppose the true optimum moves from roughly:

```text
robust = -0.8, taper = 10 mas
```

toward:

```text
robust = -0.4, taper = 13 mas
```

The ideal intermediate solution may be near `robust=-0.6`,
`taper=11.5 mas`. If that region is insufficiently measured, the envelope
can abruptly switch from one measured/interpolated family to the other.
The reported eta then jumps even though the true optimum probably changes
smoothly.

Polish measures those intermediate robust and taper values.

## 2. Crossing the skirt constraint

The imaging optimum often lies right on `skirt ~= 0.10`. A tiny change in
robust or taper can move a point from:

```text
skirt = 0.099 -- admissible
```

to:

```text
skirt = 0.101 -- not strictly admissible
```

With coarse sampling, the cheapest admissible family may suddenly
disappear, forcing the curve onto a much more expensive family or into the
best-achievable relaxed solution. That creates a large eta jump.

Sub-grid sampling finds intermediate points along the skirt contour, so the
curve can follow the boundary instead of jumping between distant options.

## 3. Rapid, nonlinear beam response

For heterogeneous arrays, especially LONG combinations, beam size can
change extremely rapidly with taper—the documented spike-to-plateau
transition. Two nearby taper samples can produce widely separated
resolutions.

The interpolation engine deliberately refuses to bridge sufficiently large
or suspicious gaps. Therefore, a coarse taper grid can leave an actual hole
in modeled resolution coverage. Taper midpoints and `×/÷ 1.22` probes
help populate that transition.

## 4. The interpolation model is only an approximation

The envelope interpolates between measured grid points, including bilinear
interpolation inside complete cells. But actual tclean behavior is not
perfectly bilinear:

- Briggs weighting depends nonlinearly on gridded UV density.
- The adaptive image cell changes with taper.
- The fitted restoring beam can change lobes or branches.
- PSF skirt behavior can curve sharply across a cell.

An off-grid tclean measurement therefore does more than merely add
resolution—it measures the real surface where the interpolation model may
be inaccurate.

## 5. Previous refinement stopped too early or chased the wrong things

The earlier campaigns had only a 60-point refinement budget per subarray.
Some exhausted that budget before reaching all the visible defects. Worse,
the previous code:

- Spent points chasing invisible `eta > 5` portions of the curve.
- Refined only the imaging curve, not the point-source curve.
- Could let one pathological jump crowd other jumps out of the budget.

The polish pass does not change the fundamental cause, but its
200-point/8-round budget and improved candidate allocation let refinement
reach the defects that were previously left behind.

## Some jumps are not sampling artifacts

Polish should not be expected to remove every jump:

- A corrupt empty tclean product caused one enormous LONG jump; that row was
  removed and guards were added. Sub-sampling was not the remedy.
- Genuine resolution-coverage gaps can exist, particularly in sparse
  snapshot and LONG configurations.
- Beam-fit lobe switching or sparse instantaneous UV coverage can produce
  real irregular behavior.
- Beam caps intentionally censor parts of heterogeneous curves.
- A hard skirt-feasibility boundary can sometimes produce a genuine change
  of solution branch.

The polish assumption is:

> Large jumps on otherwise connected portions of the curve are usually
> caused by the coarse lattice missing the smooth path of the constrained
> optimum.

Polish measures around those jumps to test and fill that path. If a jump
survives dense local sampling, it is much stronger evidence of real
PSF/coverage physics or a beam-measurement branch transition rather than
simple under-sampling.
