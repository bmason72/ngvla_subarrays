#!/usr/bin/env python3
"""
Quantify bmason's observation: MFS (band4, 32-chan, 20.25-33.75 GHz snapshot)
gives less robust-leverage on beam size/eta, and a persistently higher/harder
to sculpt skirt, compared to the single-channel ("mono", 30 GHz) snapshot
curves.

Inputs:
  sa_select/data/revf_snapshot_curves.csv        (mono, ref 30 GHz, taper_arcsec_30ghz)
  sa_select/data/revf_snapshot_band4_curves.csv  (MFS band4, ref 27 GHz, taper_arcsec_native)

Both files record taper=0 (untapered) rows with taper column == NaN (verified
against the `source` string, e.g. "...briggs_r-2.0_t0.0").

Output: printed tables + a compact CSV dump to the scratchpad.
"""
import numpy as np
import pandas as pd

DATA = "/home1/10240/bmason72/Code/ngvla_subarrays/sa_select/data"
SKIRT_THRESH = 0.10  # sa_select/schema.py default imaging skirt_threshold

m = pd.read_csv(f"{DATA}/revf_snapshot_curves.csv")
b = pd.read_csv(f"{DATA}/revf_snapshot_band4_curves.csv")

m = m.rename(columns={"resolution_arcsec_30ghz": "res", "taper_arcsec_30ghz": "taper"})
b = b.rename(columns={"resolution_arcsec_native": "res", "taper_arcsec_native": "taper"})

MONO_REF_GHZ = 30.0
BAND4_REF_GHZ = float(b["ref_freq_ghz"].iloc[0])  # 27.0 (band4 center freq)
print(f"mono ref freq = {MONO_REF_GHZ} GHz; band4 ref (native) freq = {BAND4_REF_GHZ} GHz")
print("Normalizing band4 resolution to the 30 GHz mono reference by the "
      f"native-frequency scale factor {BAND4_REF_GHZ}/30 = {BAND4_REF_GHZ/30:.4f} "
      "(theta ~ lambda/D, so res_30ghz = res_native * freq_native/30).\n")
b["res30"] = b["res"] * (BAND4_REF_GHZ / MONO_REF_GHZ)
m["res30"] = m["res"]

# restrict to untapered rows (taper column NaN => t=0.0), keep robust as
# the only knob; natural rows get robust filled to +2.0 (natural == r=+2
# convention used elsewhere in the report code) for a uniform sequence.
def untapered(df):
    d = df[df["taper"].isna()].copy()
    d["robust_eff"] = d["robust"]
    d.loc[d["weighting"] == "natural", "robust_eff"] = 2.0
    return d

mu = untapered(m)
bu = untapered(b)

common_subs = sorted(set(mu.subarray) & set(bu.subarray))
print("Common subarrays (present in both campaigns):", common_subs)
print("Mono-only subarrays:", sorted(set(mu.subarray) - set(bu.subarray)))
print("Band4-only subarrays:", sorted(set(bu.subarray) - set(mu.subarray)))
print()

GRID = [-2.0, -1.0, 0.0, 1.0, 2.0]

def nearest_row(d, sub, target_r):
    dd = d[d.subarray == sub]
    if dd.empty:
        return None
    idx = (dd.robust_eff - target_r).abs().idxmin()
    return dd.loc[idx]

# ---- Table 2: beam / eta / skirt at r = -2,-1,0,1,2 ----
rows = []
for sub in common_subs:
    rec = {"subarray": sub}
    for tag, d in (("mono", mu), ("mfs", bu)):
        beams, etas, skirts = [], [], []
        for r in GRID:
            row = nearest_row(d, sub, r)
            beams.append(row.res30 if row is not None else np.nan)
            etas.append(row.eta if row is not None else np.nan)
            skirts.append(row.skirt if row is not None else np.nan)
        rec[f"{tag}_beam"] = beams
        rec[f"{tag}_eta"] = etas
        rec[f"{tag}_skirt"] = skirts
    rows.append(rec)

print("=" * 100)
print("TABLE 2a: beam (arcsec, normalized to 30 GHz) at robust = -2,-1,0,1,2")
print("=" * 100)
hdr = f"{'subarray':22s} " + " ".join(f"m_r{r:+.0f}" for r in GRID) + "  | " + \
      " ".join(f"f_r{r:+.0f}" for r in GRID) + "   ratio(m +2/-2)  ratio(f +2/-2)"
print(hdr)
for rec in rows:
    mb, fb = rec["mono_beam"], rec["mfs_beam"]
    mratio = mb[4] / mb[0] if mb[0] not in (0, None) and not np.isnan(mb[0]) else np.nan
    fratio = fb[4] / fb[0] if fb[0] not in (0, None) and not np.isnan(fb[0]) else np.nan
    print(f"{rec['subarray']:22s} " +
          " ".join(f"{v:5.3f}" for v in mb) + "  | " +
          " ".join(f"{v:5.3f}" for v in fb) +
          f"   {mratio:6.3f}         {fratio:6.3f}")

print()
print("=" * 100)
print("TABLE 2b: eta at robust = -2,-1,0,1,2")
print("=" * 100)
print(hdr.replace("beam", "eta"))
for rec in rows:
    me, fe = rec["mono_eta"], rec["mfs_eta"]
    mratio = me[4] / me[0] if not np.isnan(me[0]) and me[0] != 0 else np.nan
    fratio = fe[4] / fe[0] if not np.isnan(fe[0]) and fe[0] != 0 else np.nan
    print(f"{rec['subarray']:22s} " +
          " ".join(f"{v:5.3f}" for v in me) + "  | " +
          " ".join(f"{v:5.3f}" for v in fe) +
          f"   {mratio:6.3f}         {fratio:6.3f}")

print()
print("=" * 100)
print("TABLE 2c: skirt at robust = -2,-1,0,1,2")
print("=" * 100)
print(hdr)
for rec in rows:
    ms, fs = rec["mono_skirt"], rec["mfs_skirt"]
    print(f"{rec['subarray']:22s} " +
          " ".join(f"{v:6.3f}" for v in ms) + " | " +
          " ".join(f"{v:6.3f}" for v in fs))

# ---- Table 3: leverage d ln(beam)/d robust near r=0, and eta crossing points ----
def leverage_and_crossings(d, sub):
    dd = d[d.subarray == sub].sort_values("robust_eff")
    dd = dd.dropna(subset=["res30", "robust_eff"])
    if len(dd) < 3:
        return np.nan, np.nan, np.nan
    r = dd.robust_eff.values
    lnb = np.log(dd.res30.values)
    eta = dd.eta.values
    # local slope via finite difference bracketing r=0 (use nearest points below/above 0)
    below = dd[dd.robust_eff < 0.0]
    above = dd[dd.robust_eff > 0.0]
    zero = dd[dd.robust_eff == 0.0]
    if len(zero) and (len(below) or len(above)):
        # straddle r=0 using the nearest neighbor on whichever side(s) exist
        r0v = 0.0
        b0v = zero.res30.iloc[0]
        if len(below) and len(above):
            r_lo, b_lo = below.robust_eff.iloc[-1], below.res30.iloc[-1]
            r_hi, b_hi = above.robust_eff.iloc[0], above.res30.iloc[0]
            slope = (np.log(b_hi) - np.log(b_lo)) / (r_hi - r_lo)
        elif len(above):
            r_hi, b_hi = above.robust_eff.iloc[0], above.res30.iloc[0]
            slope = (np.log(b_hi) - np.log(b0v)) / (r_hi - r0v) if b_hi > 0 and b0v > 0 else np.nan
        else:
            r_lo, b_lo = below.robust_eff.iloc[-1], below.res30.iloc[-1]
            slope = (np.log(b0v) - np.log(b_lo)) / (r0v - r_lo) if b_lo > 0 and b0v > 0 else np.nan
    elif len(below) and len(above):
        r0, r1 = below.robust_eff.iloc[-1], above.robust_eff.iloc[0]
        b0, b1 = below.res30.iloc[-1], above.res30.iloc[0]
        if r1 != r0 and b0 > 0 and b1 > 0:
            slope = (np.log(b1) - np.log(b0)) / (r1 - r0)
        else:
            slope = np.nan
    else:
        slope = np.nan
    # eta crossing (first robust, scanning from r=+2 downward, i.e. increasing
    # sharpness, where eta exceeds threshold) via linear interpolation on eta vs r
    def crossing(thresh):
        rr = dd.robust_eff.values
        ee = dd.eta.values
        order = np.argsort(rr)
        rr, ee = rr[order], ee[order]
        for i in range(len(rr) - 1):
            if (ee[i] - thresh) * (ee[i + 1] - thresh) <= 0 and ee[i] != ee[i + 1]:
                frac = (thresh - ee[i]) / (ee[i + 1] - ee[i])
                return rr[i] + frac * (rr[i + 1] - rr[i])
        return np.nan
    return slope, crossing(1.2), crossing(1.5)

print()
print("=" * 100)
print("TABLE 3: leverage dln(beam)/drobust near r=0, and robust at eta=1.2 / eta=1.5")
print("=" * 100)
print(f"{'subarray':22s} {'mono_slope':>11s} {'mfs_slope':>10s} | "
      f"{'mono_r@1.2':>10s} {'mfs_r@1.2':>10s} | {'mono_r@1.5':>10s} {'mfs_r@1.5':>10s}")
for sub in common_subs:
    ms, mc12, mc15 = leverage_and_crossings(mu, sub)
    fs, fc12, fc15 = leverage_and_crossings(bu, sub)
    print(f"{sub:22s} {ms:11.4f} {fs:10.4f} | {mc12:10.3f} {fc12:10.3f} | {mc15:10.3f} {fc15:10.3f}")

# ---- Table 4: min skirt over robust range, and where; count of imaging-passing points ----
print()
print("=" * 100)
print(f"TABLE 4: min skirt over untapered robust grid (skirt_threshold={SKIRT_THRESH})")
print("=" * 100)
print(f"{'subarray':22s} {'mono_min':>9s} {'@r':>6s} {'mfs_min':>9s} {'@r':>6s} "
      f"{'mono_n<=thr':>11s} {'mfs_n<=thr':>10s} {'mono_ntot':>10s} {'mfs_ntot':>9s}")
for sub in common_subs:
    md = mu[mu.subarray == sub].dropna(subset=["skirt"])
    fd = bu[bu.subarray == sub].dropna(subset=["skirt"])
    m_idx = md.skirt.idxmin() if len(md) else None
    f_idx = fd.skirt.idxmin() if len(fd) else None
    m_min = md.loc[m_idx, "skirt"] if m_idx is not None else np.nan
    m_r = md.loc[m_idx, "robust_eff"] if m_idx is not None else np.nan
    f_min = fd.loc[f_idx, "skirt"] if f_idx is not None else np.nan
    f_r = fd.loc[f_idx, "robust_eff"] if f_idx is not None else np.nan
    m_pass = (md.skirt <= SKIRT_THRESH).sum()
    f_pass = (fd.skirt <= SKIRT_THRESH).sum()
    print(f"{sub:22s} {m_min:9.4f} {m_r:6.2f} {f_min:9.4f} {f_r:6.2f} "
          f"{m_pass:11d} {f_pass:10d} {len(md):10d} {len(fd):9d}")

# ---- data quality checks ----
print()
print("=" * 100)
print("DATA QUALITY CHECKS")
print("=" * 100)
print("mono sample_status counts:\n", m.sample_status.value_counts())
print("band4 sample_status counts:\n", b.sample_status.value_counts())
for tag, d in (("mono", mu), ("mfs", bu)):
    nan_eta = d.eta.isna().sum()
    nan_skirt = d.skirt.isna().sum()
    print(f"{tag}: NaN eta rows (untapered) = {nan_eta}, NaN skirt rows = {nan_skirt}")

# monotonicity of beam vs robust (should generally decrease as robust decreases
# from +2 to -2, i.e. increase as robust increases -- check sign flips)
print("\nNon-monotonic beam-vs-robust subarrays (untapered, sorted by robust_eff):")
for tag, d in (("mono", mu), ("mfs", bu)):
    for sub in common_subs:
        dd = d[d.subarray == sub].dropna(subset=["res30", "robust_eff"]).sort_values("robust_eff")
        if len(dd) < 3:
            continue
        diffs = np.diff(dd.res30.values)
        # beam should be non-increasing as robust increases (r: -2 -> +2 sharper to coarser? check sign)
        if not (np.all(diffs <= 1e-9) or np.all(diffs >= -1e-9)):
            n_flip = np.sum(np.sign(diffs[:-1]) != np.sign(diffs[1:]))
            print(f"  {tag} {sub}: sign flips = {n_flip} (non-monotonic)")

# ---- Table 5: eta and skirt cost at matched RELATIVE beam sharpening
#      (beam / beam_natural), the actual taperability-curve framing --
#      this is the metric sa_select ranks on, and arguably what "leverage"
#      means physically (cost paid for a given fractional resolution gain).
print()
print("=" * 100)
print("TABLE 5: eta (and skirt) at matched beam/beam_natural targets (untapered, briggs-only)")
print("=" * 100)
TARGETS = [0.95, 0.90, 0.80, 0.70, 0.60]

def cost_at_targets(d, sub):
    dd = d[(d.subarray == sub)].dropna(subset=["res30", "eta", "robust_eff"]).sort_values("robust_eff")
    if dd.empty:
        return None
    nat = dd[dd.robust_eff == 2.0]
    if nat.empty:
        return None
    b_nat = nat.res30.iloc[0]
    frac = dd.res30.values / b_nat
    order = np.argsort(frac)  # increasing fraction (sharper -> less), monotonic in robust normally
    frac_s = frac[order]
    eta_s = dd.eta.values[order]
    skirt_s = dd.skirt.values[order]
    out = {}
    for t in TARGETS:
        # interpolate eta,skirt at beam/beam_nat == t (frac_s should be increasing with robust;
        # find via np.interp on frac_s sorted ascending)
        if t < frac_s.min() or t > frac_s.max():
            out[t] = (np.nan, np.nan)
            continue
        srt = np.argsort(frac_s)
        e = np.interp(t, frac_s[srt], eta_s[srt])
        s = np.interp(t, frac_s[srt], skirt_s[srt])
        out[t] = (e, s)
    return out

for sub in common_subs:
    mc = cost_at_targets(mu, sub)
    fc = cost_at_targets(bu, sub)
    print(f"\n{sub}:")
    print(f"  {'beam/beam_nat':>14s}  {'mono_eta':>9s} {'mfs_eta':>8s}  | {'mono_skirt':>10s} {'mfs_skirt':>9s}")
    for t in TARGETS:
        me, ms = mc[t] if mc else (np.nan, np.nan)
        fe, fs = fc[t] if fc else (np.nan, np.nan)
        print(f"  {t:14.2f}  {me:9.4f} {fe:8.4f}  | {ms:10.4f} {fs:9.4f}")
