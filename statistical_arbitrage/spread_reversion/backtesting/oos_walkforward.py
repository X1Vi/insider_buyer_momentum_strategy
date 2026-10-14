#!/usr/bin/env python3
"""
HONEST out-of-sample evaluation (quarterly walk-forward) of the scanner's ML.
Same event builder + features as export_model.py, but the model is retrained
quarterly on TRAILING events only and tested on the NEXT quarter's events
(events AFTER training — the model never sees them during training).
Writes backtesting/oos_results.csv (leg, arm, prob, t2, fwd5, fwd10) and
prints the per-leg out-of-sample win rates.
"""
import glob
import numpy as np
import pandas as pd
from xgboost import XGBClassifier

W_BETA, W_Z, Z_ARM, OBS = 252, 60, -3.0, 10
GATE_ZREC, GATE_PX = 0.5, 0.02
QUARTER, Q0 = 63, 3 * 63

files = sorted(glob.glob("backtesting/data/*.csv"))
names = [f.split("/")[-1][:-4] for f in files]
data = {nm: pd.read_csv(f)["close"].values for nm, f in zip(names, files)}
n_global = min(len(d) for d in data.values())

FEATURES = ["z_arm", "z_now", "z_min", "z_rec", "z_rec_speed", "days_zmin",
            "zslope_win", "zslope_short", "px_dist_low", "px_ret_arm",
            "ret_last2", "ret_last3", "ret_last5", "days_pxlow", "div",
            "z_slope_after_min", "px_slope_after_min", "div_strength",
            "drop_depth", "vol_ratio", "svol20", "beta", "leg_id"]


def rbz(pa, pb):
    sla, slb = pd.Series(np.log(pa)), pd.Series(np.log(pb))
    beta = (sla.rolling(W_BETA).cov(slb) / slb.rolling(W_BETA).var()).values
    alpha = (sla.rolling(W_BETA).mean() - pd.Series(beta) * slb.rolling(W_BETA).mean()).values
    spread = (sla - pd.Series(beta) * slb - pd.Series(alpha)).values
    mu = pd.Series(spread).rolling(W_Z).mean().values
    sd = pd.Series(spread).rolling(W_Z).std().values
    z = np.where(sd > 1e-9, (spread - mu) / np.maximum(sd, 1e-9), 0.0)
    z[:W_BETA + W_Z] = 0.0
    return z, beta


def t2(ps, i):
    e0 = ps[i]
    for k in range(1, 11):
        if i + k >= len(ps):
            return 0
        c = ps[i + k]
        if c >= e0 * 1.02:
            return 1
        if c <= e0 * 0.98:
            return 0
    return 0


def build():
    events = []  # (leg, partner, arm, feats, t2, z_arm)
    for a in range(len(names)):
        for b in range(a + 1, len(names)):
            A, B = names[a], names[b]
            pa, pb = data[A], data[B]
            n = min(len(pa), len(pb))
            if n < W_BETA + W_Z + OBS + 22:
                continue
            pa, pb = pa[:n], pb[:n]
            z, beta = rbz(pa, pb)
            i = 0
            while i < n:
                if z[i] < Z_ARM and i >= W_BETA + W_Z and i + OBS + 20 < n:
                    e = i + OBS
                    seg_z, seg_p = z[i:e + 1], pa[i:e + 1]
                    zm, pmin = seg_z.min(), seg_p.min()
                    dzm, dpm = int(np.argmin(seg_z)), int(np.argmin(seg_p))
                    zrec = z[e] - zm
                    pxdist = pa[e] / pmin - 1
                    if zrec >= max(GATE_ZREC, 0.3 * abs(zm)) and pxdist <= GATE_PX:
                        vf = np.std(np.diff(np.log(pa[i:i + 6])))
                        vl = np.std(np.diff(np.log(pa[e - 5:e + 1])))
                        feats = [z[i], z[e], zm, zrec, zrec / max(dzm, 1), dzm,
                                 (z[e] - z[i]) / OBS, z[e] - z[e - 2], pxdist,
                                 pa[e] / pa[i] - 1, pa[e] / pa[e - 2] - 1,
                                 pa[e] / pa[e - 3] - 1, pa[e] / pa[e - 5] - 1, dpm,
                                 max(0.0, zrec) * max(0.0, pa[i] / pmin - 1),
                                 (z[e] - seg_z[dzm]) / max(OBS - dzm, 1),
                                 (pa[e] - seg_p[dpm]) / max(OBS - dpm, 1) / max(pmin, 1e-9),
                                 zrec / max(pxdist, 1e-4), abs(zm),
                                 vl / max(vf, 1e-9), np.std(np.log(pa[e - 19:e + 1])),
                                 beta[e], a]
                        events.append((A, B, i, feats, t2(pa, e), z[i]))
                    i += 5
                i += 1
    best = {}
    for ev in events:
        key = (ev[0], ev[2])
        if key not in best or ev[5] < best[key][5]:
            best[key] = ev
    return list(best.values())


evs = build()
df = pd.DataFrame([e[3] for e in evs], columns=FEATURES)
df["leg"] = [e[0] for e in evs]
df["partner"] = [e[1] for e in evs]
df["arm"] = [e[2] for e in evs]
df["t2"] = [e[4] for e in evs]
print(f"candidate events: {len(df)}  T2 base={df['t2'].mean():.0%}")

X = df[FEATURES].values
y = df["t2"].values
arm = df["arm"].values

oos = []
for t in range(Q0, n_global, QUARTER):
    tr = arm < t
    te = (arm >= t) & (arm < t + QUARTER)
    if tr.sum() < 40 or te.sum() < 5:
        continue
    m = XGBClassifier(n_estimators=300, max_depth=4, learning_rate=0.05,
                      subsample=0.8, colsample_bytree=0.8, random_state=1)
    m.fit(X[tr], y[tr])
    p = m.predict_proba(X[te])[:, 1]
    for k in np.where(te)[0]:
        oos.append((df["leg"].iloc[k], df["partner"].iloc[k], int(arm[k]),
                    float(p[len(oos) - len(p) + list(np.where(te)[0]).index(k)]) if False else 0.0,
                    int(y[k]), 0.0, 0.0))
    # simpler: build oos rows directly
oos = []
for t in range(Q0, n_global, QUARTER):
    tr = arm < t
    te = (arm >= t) & (arm < t + QUARTER)
    if tr.sum() < 40 or te.sum() < 5:
        continue
    m = XGBClassifier(n_estimators=300, max_depth=4, learning_rate=0.05,
                      subsample=0.8, colsample_bytree=0.8, random_state=1)
    m.fit(X[tr], y[tr])
    p = m.predict_proba(X[te])[:, 1]
    idx = np.where(te)[0]
    for j, k in enumerate(idx):
        row = df.iloc[k]
        pa = data[row["leg"]]
        e = int(row["arm"]) + OBS
        f5 = 100 * (pa[e + 5] / pa[e] - 1) if e + 5 < len(pa) else float("nan")
        f10 = 100 * (pa[e + 10] / pa[e] - 1) if e + 10 < len(pa) else float("nan")
        oos.append((row["leg"], row["partner"], int(row["arm"]), p[j], int(y[k]), f5, f10))

odf = pd.DataFrame(oos, columns=["leg", "partner", "arm", "prob", "t2", "fwd5", "fwd10"])
odf.to_csv("backtesting/oos_results.csv", index=False)
print(f"OOS events: {len(odf)}   T2 win: {odf['t2'].mean():.0%}   "
      f"watch(prob>=0.5): {(odf['prob']>=0.5).sum()}")

per = odf.groupby("leg").agg(n=("t2", "size"), win=("t2", "mean"), watch=("prob", lambda s: (s >= 0.5).sum()),
                             f5=("fwd5", "mean"), f10=("fwd10", "mean"),
                             p=("prob", "mean")).sort_values("win", ascending=False)
print("\n=== PER-LEG OUT-OF-SAMPLE (model never saw these events during training) ===")
for leg, r in per.iterrows():
    print(f"  {leg:<12} n={int(r['n']):>3}  watch={int(r['watch']):>3}  "
          f"T2win={100*r['win']:>3.0f}%  fwd5={r['f5']:+.1f}%  fwd10={r['f10']:+.1f}%  avgP={r['p']:.0%}")
print(f"\nwrote backtesting/oos_results.csv")
