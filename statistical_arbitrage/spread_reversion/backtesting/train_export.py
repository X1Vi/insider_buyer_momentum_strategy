#!/usr/bin/env python3
"""Authoritative ML v3 WATCH model training + export.

Regenerates BOTH `model_dump.txt` (text, read by the Rust scanner and the
`reaction` app) and `model_check.json` (the parity reference) from ONE training
run, so they can never drift apart again.

Why this file exists (from the parity audit):
  * model_check.json and model_dump.txt had come from different runs -> live
    P= differed from the real model.
  * XGBoost compares features/thresholds in float32, but the scanner compared
    in float64 -> near-tie splits flipped branches and shifted P= by up to ~1%.
  * base_score was hardcoded as logit(0.43); the true auto-computed base is
    logit(T2_mean) of the training set.

This script writes the TRUE base_score into model_check.json and prints a
parity check (predict_proba vs text-dump inference, float32) that must pass
within PARITY_TOL before the export is considered good.

Usage:
  .venv/bin/python backtesting/train_export.py
"""
import glob
import json
import math
import os

import numpy as np
import pandas as pd
from xgboost import XGBClassifier

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
DUMP_PATH = os.path.join(HERE, "model_dump.txt")
CHECK_PATH = os.path.join(HERE, "model_check.json")

W_BETA, W_Z, Z_ARM, OBS = 252, 60, -3.0, 10
GATE_ZREC, GATE_PX = 0.5, 0.02
PARITY_TOL = 0.005            # max |predict_proba - dump-parse| accepted

FEATURES = ["z_arm", "z_now", "z_min", "z_rec", "z_rec_speed", "days_zmin",
            "zslope_win", "zslope_short", "px_dist_low", "px_ret_arm",
            "ret_last2", "ret_last3", "ret_last5", "days_pxlow", "div",
            "z_slope_after_min", "px_slope_after_min", "div_strength",
            "drop_depth", "vol_ratio", "svol20", "beta", "leg_id"]

files = sorted(glob.glob(os.path.join(DATA, "*.csv")))
names = [os.path.basename(f)[:-4] for f in files]
data = {nm: pd.read_csv(f)["close"].values for nm, f in zip(names, files)}


def rolling_beta_z(pa, pb):
    sla = pd.Series(np.log(pa)); slb = pd.Series(np.log(pb))
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
    """Variant-12 event build: requires i+OBS+12 < n (the canonical export set)."""
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
                    seg_z, seg_p = z[i:e + 1], pa[i:e + 1]
                    zm, pmin = seg_z.min(), seg_p.min()
                    dzm, dpm = int(np.argmin(seg_z)), int(np.argmin(seg_p))
                    z_rec = z[e] - zm
                    px_dist_low = pa[e] / pmin - 1
                    if z_rec >= max(GATE_ZREC, 0.3 * abs(zm)) and px_dist_low <= GATE_PX:
                        vf = np.std(np.diff(np.log(pa[i:i + 6])))
                        vl = np.std(np.diff(np.log(pa[e - 5:e + 1])))
                        feats = [z[i], z[e], zm, z_rec, z_rec / max(dzm, 1), dzm,
                                 (z[e] - z[i]) / OBS, z[e] - z[e - 2], px_dist_low,
                                 pa[e] / pa[i] - 1, pa[e] / pa[e - 2] - 1,
                                 pa[e] / pa[e - 3] - 1, pa[e] / pa[e - 5] - 1, dpm,
                                 max(0.0, z_rec) * max(0.0, pa[i] / pmin - 1) if pmin > 0 else 0.0,
                                 (z[e] - seg_z[dzm]) / max(e - (i + dzm), 1),
                                 (pa[e] - seg_p[dpm]) / max(e - (i + dpm), 1) / max(pmin, 1e-9),
                                 z_rec / max(px_dist_low, 1e-4), abs(zm), vl / max(vf, 1e-9),
                                 np.std(np.log(pa[e - 19:e + 1])), beta[e], a]
                        events.append((A, B, i, feats, quick_target(pa, e, 0.02, 0.02, 10), z[i]))
                    i += 5
                i += 1
    best = {}
    for ev in events:
        key = (ev[0], ev[2])
        if key not in best or ev[5] < best[key][5]:
            best[key] = ev
    return list(best.values())


# ---------------- text-dump parser + float32 inference (mirrors scanner.rs) ----------------

def parse_dump(path):
    trees, nodes = [], []
    for raw in open(path):
        body = raw.strip()
        if body.startswith("booster["):
            if nodes:
                nodes.sort(key=lambda x: x[0])
                trees.append([n for _, n in nodes])
                nodes = []
            continue
        if ":" not in body:
            continue
        nid_s, rest = body.split(":", 1)
        nid = int(nid_s.strip())
        rest = rest.strip()
        if rest.startswith("leaf="):
            nodes.append((nid, ("leaf", float(rest[5:].strip()))))
        else:
            inner = rest.split("]")[0].lstrip("[").lstrip("f")
            fs, ts = inner.split("<")
            feat = int(fs.strip()); thr = float(ts.strip())
            tail = rest.split("]")[1] if "]" in rest else ""
            def ti(tail, key):
                p = tail.find(key)
                s = tail[p + len(key):] if p >= 0 else ""
                d = ""
                for ch in s:
                    if ch.isdigit(): d += ch
                    else: break
                return int(d) if d else 0
            nodes.append((nid, ("split", feat, thr, ti(tail, "yes="), ti(tail, "no="))))
    if nodes:
        nodes.sort(key=lambda x: x[0])
        trees.append([n for _, n in nodes])
    return trees


def dump_predict(trees, feats, base):
    """float32 comparison + additive base — bit-consistent with XGBoost."""
    margin = base
    for t in trees:
        i = 0
        while t[i][0] != "leaf":
            _, f, thr, yes, no = t[i]
            i = yes if np.float32(feats[f]) < np.float32(thr) else no
        margin += t[i][1]
    return 1.0 / (1.0 + math.exp(-margin))


def main():
    evs = build()
    df = pd.DataFrame([e[3] for e in evs], columns=FEATURES)
    df["leg"] = [e[0] for e in evs]
    df["partner"] = [e[1] for e in evs]
    df["arm_i"] = [e[2] for e in evs]
    df["T2"] = [e[4] for e in evs]
    print(f"events: {len(df)}   T2 base={df['T2'].mean():.4f}")

    model = XGBClassifier(n_estimators=300, max_depth=4, learning_rate=0.05,
                          subsample=0.8, colsample_bytree=0.8, random_state=1)
    model.fit(df[FEATURES].values, df["T2"].values)
    booster = model.get_booster()
    booster.dump_model(DUMP_PATH, with_stats=False)

    true_base = float(str(
        json.loads(booster.save_raw(raw_format="json").decode())
        ["learner"]["learner_model_param"]["base_score"]).strip("[]"))
    base_logit = math.log(true_base / (1 - true_base))
    print(f"true base_score={true_base:.6f}  logit={base_logit:.6f}")

    # reference rows: the most recent event per scanner leg
    ver = []
    for leg in ("AXISBANK", "KOTAKBANK", "TATASTEEL"):
        sub = df[df["leg"] == leg].sort_values("arm_i")
        if len(sub):
            r = sub.iloc[-1]
            p = model.predict_proba(r[FEATURES].values.reshape(1, -1))[0, 1]
            ver.append({"leg": leg, "arm_i": int(r["arm_i"]), "partner": r["partner"],
                        "prob": round(float(p), 6),
                        "features": [round(float(x), 6) for x in r[FEATURES].values]})
    with open(CHECK_PATH, "w") as f:
        json.dump({"features": FEATURES,
                   "leg_ids": {nm: i for i, nm in enumerate(names)},
                   "base_score": base_logit,
                   "rows": ver}, f, indent=1)
    print(f"wrote {CHECK_PATH} and {DUMP_PATH}")

    # ---- parity check: predict_proba (ground truth) vs text-dump parse ----
    # Uses FULL-precision features (what the scanner recomputes at runtime), not
    # the 6dp-rounded copy stored in model_check.json (which is for humans only).
    trees = parse_dump(DUMP_PATH)
    assert len(trees) == 300
    worst = 0.0
    ok = True
    for row in ver:
        full = df[(df["leg"] == row["leg"]) & (df["arm_i"] == row["arm_i"])]
        if len(full) == 0:
            continue
        fx = full[FEATURES].values[0]
        proba = model.predict_proba(fx.reshape(1, -1))[0, 1]
        parsed = dump_predict(trees, fx, base_logit)
        d = abs(proba - parsed)
        worst = max(worst, d)
        status = "OK" if d <= PARITY_TOL else "FAIL"
        if d > PARITY_TOL:
            ok = False
        print(f"  {row['leg']:10}/{row['partner']:<10} predict_proba={proba:.4f} "
              f"dump_parse={parsed:.4f} diff={d:.4f} {status}")
    print(f"parity: worst diff={worst:.4f}  tol={PARITY_TOL}  -> {'PASS' if ok else 'FAIL'}")
    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
