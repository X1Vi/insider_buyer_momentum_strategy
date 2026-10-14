#!/usr/bin/env python3
"""Train the final ML v3 XGBoost (T2 target) on ALL data and export it for the
Rust scanner. Also finds the most common pair-partner per scanner leg and
writes a few verification rows (features -> expected probability)."""
import glob
import json
import numpy as np
import pandas as pd
from xgboost import XGBClassifier

W_BETA, W_Z, Z_ARM, L, OBS = 252, 60, -3.0, 3, 10
GATE_ZREC, GATE_PX = 0.5, 0.02

files = sorted(glob.glob("backtesting/data/*.csv"))
names = [f.split("/")[-1][:-4] for f in files]
data = {nm: pd.read_csv(f)["close"].values for nm, f in zip(names, files)}

FEATURES = ["z_arm", "z_now", "z_min", "z_rec", "z_rec_speed", "days_zmin",
            "zslope_win", "zslope_short", "px_dist_low", "px_ret_arm",
            "ret_last2", "ret_last3", "ret_last5", "days_pxlow", "div",
            "z_slope_after_min", "px_slope_after_min", "div_strength",
            "drop_depth", "vol_ratio", "svol20", "beta", "leg_id"]


def rolling_beta_z(pa, pb):
    sla, slb = pd.Series(np.log(pa)), pd.Series(np.log(pb))
    beta = (sla.rolling(W_BETA).cov(slb) / slb.rolling(W_BETA).var()).values
    alpha = (sla.rolling(W_BETA).mean() - pd.Series(beta) * slb.rolling(W_BETA).mean()).values
    spread = (sla - pd.Series(beta) * slb - pd.Series(alpha)).values
    mu = pd.Series(spread).rolling(W_Z).mean().values
    sd = pd.Series(spread).rolling(W_Z).std().values
    z = np.where(sd > 1e-9, (spread - mu) / np.maximum(sd, 1e-9), 0.0)
    z[:W_BETA + W_Z] = 0.0
    return z, beta


def quick_target(pa, i, tp, sl, days):
    entry = pa[i]
    for k in range(1, days + 1):
        if i + k >= len(pa):
            return 0
        c = pa[i + k]
        if c >= entry * (1 + tp):
            return 1
        if c <= entry * (1 - sl):
            return 0
    return 0


def build():
    events = []
    for a in range(len(names)):
        for b in range(a + 1, len(names)):
            A, B = names[a], names[b]
            pa, pb = data[A], data[B]
            n = min(len(pa), len(pb))
            if n < W_BETA + W_Z + OBS + 12 + 30:
                continue
            pa, pb = pa[:n], pb[:n]
            z, beta = rolling_beta_z(pa, pb)
            i = 0
            while i < n:
                if z[i] < Z_ARM and i >= W_BETA + W_Z and i + OBS + 12 < n:
                    e = i + OBS
                    seg_z = z[i:e + 1]
                    seg_p = pa[i:e + 1]
                    zm, pmin = seg_z.min(), seg_p.min()
                    dzm, dpm = int(np.argmin(seg_z)), int(np.argmin(seg_p))
                    z_rec = z[e] - zm
                    px_dist_low = pa[e] / pmin - 1
                    if z_rec >= max(GATE_ZREC, 0.3 * abs(zm)) and px_dist_low <= GATE_PX:
                        vf = np.std(np.diff(np.log(pa[i:i + 6])))
                        vl = np.std(np.diff(np.log(pa[e - 5:e + 1])))
                        feats = {
                            "z_arm": z[i], "z_now": z[e], "z_min": zm, "z_rec": z_rec,
                            "z_rec_speed": z_rec / max(dzm, 1), "days_zmin": dzm,
                            "zslope_win": (z[e] - z[i]) / OBS, "zslope_short": z[e] - z[e - 2],
                            "px_dist_low": px_dist_low, "px_ret_arm": pa[e] / pa[i] - 1,
                            "ret_last2": pa[e] / pa[e - 2] - 1, "ret_last3": pa[e] / pa[e - 3] - 1,
                            "ret_last5": pa[e] / pa[e - 5] - 1, "days_pxlow": dpm,
                            "div": max(0.0, z_rec) * max(0.0, pa[i] / pmin - 1) if pmin > 0 else 0.0,
                            "z_slope_after_min": (z[e] - seg_z[dzm]) / max(e - (i + dzm), 1),
                            "px_slope_after_min": (pa[e] - seg_p[dpm]) / max(e - (i + dpm), 1) / max(pmin, 1e-9),
                            "div_strength": z_rec / max(px_dist_low, 1e-4),
                            "drop_depth": abs(zm), "vol_ratio": vl / max(vf, 1e-9),
                            "svol20": np.std(np.log(pa[e - 19:e + 1])), "beta": beta[e],
                            "leg_id": a,
                        }
                        events.append((A, B, i, [feats[f] for f in FEATURES],
                                       quick_target(pa, e, 0.02, 0.02, 10), z[i]))
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
df["arm_i"] = [e[2] for e in evs]
df["T2"] = [e[4] for e in evs]
print(f"events: {len(df)}  T2 base={df['T2'].mean():.0%}")

# most common partner per scanner leg
for leg in ("AXISBANK", "KOTAKBANK", "TATASTEEL"):
    sub = df[df["leg"] == leg]
    if len(sub):
        pc = sub["partner"].value_counts().head(3)
        print(f"  {leg}: events={len(sub)}  partners: {dict(pc)}  hit={sub['T2'].mean():.0%}")

# train final model (T2) on ALL events
model = XGBClassifier(n_estimators=300, max_depth=4, learning_rate=0.05,
                      subsample=0.8, colsample_bytree=0.8, random_state=1)
model.fit(df[FEATURES].values, df["T2"].values)
booster = model.get_booster()
booster.dump_model("backtesting/model_dump.txt", with_stats=False)
params = model.get_params()
base_score = booster.base_score if hasattr(booster, "base_score") else 0.5
print(f"\nmodel: estimators={params['n_estimators']} depth={params['max_depth']} "
      f"features={len(FEATURES)} base_score={base_score}")
print("dumped backtesting/model_dump.txt")

# verification rows: one recent event per scanner leg
ver = []
for leg in ("AXISBANK", "KOTAKBANK", "TATASTEEL"):
    sub = df[df["leg"] == leg].sort_values("arm_i")
    if len(sub):
        r = sub.iloc[-1]
        p = model.predict_proba(r[FEATURES].values.reshape(1, -1))[0, 1]
        ver.append({"leg": leg, "arm_i": int(r["arm_i"]), "partner": r["partner"],
                    "prob": float(round(p, 4)), "T2": int(r["T2"]),
                    "features": [round(float(x), 6) for x in r[FEATURES].values]})
with open("backtesting/model_check.json", "w") as f:
    json.dump({"features": FEATURES, "leg_ids": {nm: i for i, nm in enumerate(names)},
               "rows": ver}, f, indent=1)
print("wrote backtesting/model_check.json (for Rust verification)")
