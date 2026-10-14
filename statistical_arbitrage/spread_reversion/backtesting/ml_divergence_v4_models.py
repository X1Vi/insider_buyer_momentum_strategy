#!/usr/bin/env python3
"""
ML v4 — ml_divergence_v3.py taken VERBATIM, only the models change.
  Same recovering-divergence candidate set + walk-forward quarterly refit, but
  now trains & tests 4 models (XGBoost, LightGBM, RandomForest,
  LogisticRegression) on the SAME out-of-sample slices and plots ALL their trades.
  Targets: +3%/-2%/10d (primary), +2%/-2%/10d, +3%/-2%/5d.
"""
import glob
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from xgboost import XGBClassifier
from lightgbm import LGBMClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score, brier_score_loss

SPLIT, W_BETA, W_Z, Z_ARM, L, OBS = 0.6, 252, 60, -3.0, 3, 10
GATE_ZREC, GATE_PX = 0.5, 0.02     # z_rec >= max(0.5, 0.3*|z_min|); px_dist_low <= 2%
QUARTER = 63
Q0 = 3 * QUARTER

files = sorted(glob.glob("backtesting/data/*.csv"))
names = [f.split("/")[-1][:-4] for f in files]
data = {nm: pd.read_csv(f)["close"].values for nm, f in zip(names, files)}
n_global = min(len(d) for d in data.values())
split_idx = int(SPLIT * n_global)


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


FEATURES = ["z_arm", "z_now", "z_min", "z_rec", "z_rec_speed", "days_zmin",
            "zslope_win", "zslope_short", "px_dist_low", "px_ret_arm",
            "ret_last2", "ret_last3", "ret_last5", "days_pxlow", "div",
            "z_slope_after_min", "px_slope_after_min", "div_strength",
            "drop_depth", "vol_ratio", "svol20", "beta", "leg_id"]


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
                    # CANDIDATE GATE — the recovering-divergence set
                    if z_rec >= max(GATE_ZREC, 0.3 * abs(zm)) and px_dist_low <= GATE_PX:
                        vf = np.std(np.diff(np.log(pa[i:i + 6])))
                        vl = np.std(np.diff(np.log(pa[e - 5:e + 1])))
                        z_slope_am = (z[e] - seg_z[dzm]) / max(e - (i + dzm), 1)
                        px_slope_am = (pa[e] - seg_p[dpm]) / max(e - (i + dpm), 1) / max(pmin, 1e-9)
                        feats = {
                            "z_arm": z[i], "z_now": z[e], "z_min": zm, "z_rec": z_rec,
                            "z_rec_speed": z_rec / max(dzm, 1), "days_zmin": dzm,
                            "zslope_win": (z[e] - z[i]) / OBS, "zslope_short": z[e] - z[e - 2],
                            "px_dist_low": px_dist_low, "px_ret_arm": pa[e] / pa[i] - 1,
                            "ret_last2": pa[e] / pa[e - 2] - 1, "ret_last3": pa[e] / pa[e - 3] - 1,
                            "ret_last5": pa[e] / pa[e - 5] - 1, "days_pxlow": dpm,
                            "div": max(0.0, z_rec) * max(0.0, pa[i] / pmin - 1) if pmin > 0 else 0.0,
                            "z_slope_after_min": z_slope_am,
                            "px_slope_after_min": px_slope_am,
                            "div_strength": z_rec / max(px_dist_low, 1e-4),
                            "drop_depth": abs(zm), "vol_ratio": vl / max(vf, 1e-9),
                            "svol20": np.std(np.log(pa[e - 19:e + 1])), "beta": beta[e],
                            "leg_id": a,
                        }
                        y = {k: None for k in ("T1", "T2", "T3")}
                        y["T1"] = quick_target(pa, e, 0.03, 0.02, 10)
                        y["T2"] = quick_target(pa, e, 0.02, 0.02, 10)
                        y["T3"] = quick_target(pa, e, 0.03, 0.02, 5)
                        events.append((A, i, [feats[f] for f in FEATURES], y, z[i]))
                    i += 5
                i += 1
    best = {}
    for ev in events:
        key = (ev[0], ev[1])
        if key not in best or ev[4] < best[key][4]:
            best[key] = ev
    return list(best.values())


evs = build()
df = pd.DataFrame([e[2] for e in evs], columns=FEATURES)
df["leg"] = [e[0] for e in evs]
df["arm_i"] = [e[1] for e in evs]
for t in ("T1", "T2", "T3"):
    df[t] = [e[3][t] for e in evs]
print(f"candidate events (post gate): {len(df)}   "
      f"base T1(+3/-2/10d)={df['T1'].mean():.0%}  T2={df['T2'].mean():.0%}  T3={df['T3'].mean():.0%}")


MODELS = {
    "XGBoost": lambda: XGBClassifier(n_estimators=300, max_depth=4, learning_rate=0.05,
                                     subsample=0.8, colsample_bytree=0.8, random_state=1),
    "LightGBM": lambda: LGBMClassifier(n_estimators=300, max_depth=4, learning_rate=0.05,
                                       subsample=0.8, colsample_bytree=0.8, random_state=1, verbose=-1),
    "RandomForest": lambda: RandomForestClassifier(n_estimators=300, min_samples_leaf=3, random_state=1),
    "LogisticRegression": lambda: LogisticRegression(max_iter=2000),
}


def walk_forward(target, model_factory):
    X = df[FEATURES].values
    y = df[target].values
    arm = df["arm_i"].values
    oos_i, oos_p, oos_y = [], [], []
    for t in range(Q0, n_global, QUARTER):
        tr = arm < t
        te = (arm >= t) & (arm < t + QUARTER)
        if tr.sum() < 40 or te.sum() < 5:
            continue
        m = model_factory()
        m.fit(X[tr], y[tr])
        oos_p.extend(m.predict_proba(X[te])[:, 1])
        oos_y.extend(y[te])
        oos_i.extend(np.where(te)[0])
    return np.array(oos_p), np.array(oos_y), np.array(oos_i)


print("\n=== WALK-FORWARD (quarterly refit), out-of-sample — ALL MODELS ===")
results = {}
for tgt, label in (("T1", "+3%/-2%/10d"), ("T2", "+2%/-2%/10d"), ("T3", "+3%/-2%/5d")):
    print(f"\n-- target {label} --")
    results[tgt] = {}
    for mname, mf in MODELS.items():
        p, y, idx = walk_forward(tgt, mf)
        auc = roc_auc_score(y, p) if len(np.unique(y)) > 1 else float("nan")
        brier = brier_score_loss(y, p)
        base = y.mean()
        top = int(len(p) * 0.2)
        top_hit = y[np.argsort(-p)[:top]].mean() if len(p) else 0
        results[tgt][mname] = {"p": p, "y": y, "idx": idx, "auc": auc, "brier": brier,
                               "base": base, "top_hit": top_hit, "label": label}
        print(f"  {mname:<18} n={len(p):>3}  AUC={auc:.3f}  Brier={brier:.3f}  "
              f"base={base:.0%}  top20%={top_hit:.0%}  lift={top_hit/base:.2f}x")

# ---- plots: all trades per model, per leg + paths (primary target T1) ----
THRESH, FALLBACK = 0.50, 15
for mname in MODELS:
    res = results["T1"][mname]
    idx, p, y = res["idx"], res["p"], res["y"]
    sel_i = idx[p >= THRESH]
    if len(sel_i) < 3:
        sel_i = idx[np.argsort(-p)[:FALLBACK]]
    mask = np.isin(idx, sel_i)
    prob, yt = p[mask], y[mask]
    legs = df["leg"].values[idx[mask]]
    arms = df["arm_i"].values[idx[mask]]
    rows = sorted(zip(legs, arms, prob, yt), key=lambda r: -r[2])
    print(f"\n=== MODEL TRADES {mname} (T1, n={len(prob)}) — plot all ===")
    for leg, a, pp, yy in rows:
        pa = data[leg]
        e = a + OBS
        f10 = 100 * (pa[min(e + 10, len(pa) - 1)] / pa[e] - 1) if e + 10 < len(pa) else float("nan")
        print(f"{leg:<12} {int(a):>5} {int(e):>5} {pp:>5.0%} {'WIN' if yy else 'LOSS':>7} {f10:>+6.1f}%")
    print(f"summary: {len(prob)} trades, {100*yt.mean():.0f}% hit target")

    import os
    os.makedirs(f"backtesting/plots/model_trades_v4_{mname}", exist_ok=True)
    for leg in sorted(set(legs)):
        pa = data[leg]
        n = len(pa)
        fig, ax = plt.subplots(figsize=(14, 5))
        ax.plot(np.arange(n), pa, color="#1f77b4", lw=1.1)
        for lg, a, pp, yy in rows:
            if lg != leg:
                continue
            e = a + OBS
            c = "green" if yy else "red"
            ax.scatter(e, pa[e], marker="^", s=90, color=c, edgecolors="k", lw=0.6, zorder=6)
            ax.annotate(f"{pp:.0%}\n{'WIN' if yy else 'LOSS'}", (e, pa[e]),
                        textcoords="offset points", xytext=(0, 8), ha="center",
                        fontsize=7, color=c, fontweight="bold")
        ax.set_xlim(Q0 - 30, n + 5)
        ax.set_ylabel("Price ₹")
        ax.set_title(f"{leg} — {mname} v4 T1 OOS trades (green=hit target, red=missed)")
        ax.grid(alpha=0.3)
        plt.tight_layout()
        plt.savefig(f"backtesting/plots/model_trades_v4_{mname}/{leg}.png", dpi=110)
        plt.close(fig)

    fig, ax = plt.subplots(figsize=(12, 6))
    for lg, a, pp, yy in rows:
        pa = data[lg]
        e = a + OBS
        path = np.array([pa[min(k, len(pa) - 1)] / pa[e] - 1
                         for k in range(a, e + 11)])
        x = np.arange(len(path)) - (e - a)
        ax.plot(x, path * 100, color=("green" if yy else "red"), alpha=0.6, lw=1.0)
    ax.axvline(0, color="k", ls="--", lw=0.8)
    ax.axhline(0, color="k", lw=0.6)
    ax.set_xlabel("bars (arm=start, 0=entry, +10=forward)")
    ax.set_ylabel("% from entry")
    ax.set_title(f"{mname} v4 T1 OOS trades: arm -> ENTRY(0) -> +10d (green=hit, red=missed)")
    ax.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(f"backtesting/plots/model_trades_v4_{mname}_paths.png", dpi=110)
    print(f"plots: backtesting/plots/model_trades_v4_{mname}/*.png  + paths")

# ---- model comparison summary plot (T1) ----
res = results["T1"]
fig, ax = plt.subplots(figsize=(10, 6))
mnames = list(MODELS)
aucs = [res[m]["auc"] for m in mnames]
hits = [res[m]["top_hit"] * 100 for m in mnames]
x = np.arange(len(mnames))
w = 0.38
ax.bar(x - w / 2, aucs, w, color="#14568c", label="AUC (out-of-sample)")
ax2 = ax.twinx()
ax2.bar(x + w / 2, hits, w, color="#c0392b", label="top20% hit rate %")
for xi, v in zip(x, aucs):
    ax.text(xi - w / 2, v, f"{v:.3f}", ha="center", va="bottom", fontsize=8)
for xi, v in zip(x, hits):
    ax2.text(xi + w / 2, v, f"{v:.0f}%", ha="center", va="bottom", fontsize=8)
ax.set_xticks(x)
ax.set_xticklabels(mnames)
ax.set_ylabel("AUC")
ax2.set_ylabel("top20% hit rate %")
ax.axhline(res["XGBoost"]["base"], color="k", ls="--", lw=0.8, label="base")
ax.set_title("ML v4 model comparison (T1, walk-forward OOS)")
ax.legend(loc="upper left"); ax.grid(alpha=0.3, axis="y")
plt.tight_layout()
plt.savefig("backtesting/plots/ml_v4_model_comparison.png", dpi=110)
print("\nsaved backtesting/plots/ml_v4_model_comparison.png")
