#!/usr/bin/env python3
"""
ML v3 — "recovering-divergence candidate set" + honest evaluation.
  ARM z<-3 -> observe OBS=10 -> CANDIDATE GATE: z recovered materially
  (z_rec >= max(0.5, 0.3*|z_min|)) AND price still near the post-arm low
  (px_dist_low <= 2%). Then ML ranks candidates (walk-forward, quarterly refit).
  Targets: +3%/-2%/10d (primary), +2%/-2%/10d, +3%/-2%/5d.
  Evaluation: AUC, Brier + calibration curve, lift curve, per-leg consistency,
  leg-ID sensitivity. Plots to ml_v3.png.
"""
import glob
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from xgboost import XGBClassifier
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


def walk_forward(target, use_leg=True):
    cols = FEATURES if use_leg else [f for f in FEATURES if f != "leg_id"]
    X = df[cols].values
    y = df[target].values
    arm = df["arm_i"].values
    oos_i, oos_p, oos_y = [], [], []
    for t in range(Q0, n_global, QUARTER):
        tr = arm < t
        te = (arm >= t) & (arm < t + QUARTER)
        if tr.sum() < 40 or te.sum() < 5:
            continue
        m = XGBClassifier(n_estimators=300, max_depth=4, learning_rate=0.05,
                          subsample=0.8, colsample_bytree=0.8, random_state=1)
        m.fit(X[tr], y[tr])
        oos_p.extend(m.predict_proba(X[te])[:, 1])
        oos_y.extend(y[te])
        oos_i.extend(np.where(te)[0])
    return np.array(oos_p), np.array(oos_y), np.array(oos_i)


print("\n=== WALK-FORWARD (quarterly refit), out-of-sample ===")
results = {}
for tgt, label in (("T1", "+3%/-2%/10d"), ("T2", "+2%/-2%/10d"), ("T3", "+3%/-2%/5d")):
    p, y, idx = walk_forward(tgt)
    auc = roc_auc_score(y, p) if len(np.unique(y)) > 1 else float("nan")
    brier = brier_score_loss(y, p)
    base = y.mean()
    top = int(len(p) * 0.2)
    top_hit = y[np.argsort(-p)[:top]].mean() if len(p) else 0
    results[tgt] = {"p": p, "y": y, "idx": idx, "auc": auc, "brier": brier,
                    "base": base, "top_hit": top_hit, "label": label}
    print(f"  {label:<12} n={len(p):>3}  AUC={auc:.3f}  Brier={brier:.3f}  "
          f"base={base:.0%}  top20%={top_hit:.0%}  lift={top_hit/base:.2f}x")

# leg-ID sensitivity on primary target
p_no, y_no, _ = walk_forward("T1", use_leg=False)
auc_no = roc_auc_score(y_no, p_no) if len(np.unique(y_no)) > 1 else float("nan")
print(f"\n  leg-ID sensitivity (T1): with leg_id AUC={results['T1']['auc']:.3f}  "
      f"without leg_id AUC={auc_no:.3f}")

# per-leg consistency (T1)
df_ = df.copy()
df_["p"] = np.nan
df_.loc[results["T1"]["idx"], "p"] = results["T1"]["p"]
per = df_[df_["p"].notna()].groupby("leg").agg(n=("p", "size"), hit=("T1", "mean"),
                                               p=("p", "mean"))
print("\n=== PER-LEG out-of-sample (T1) ===")
print(f"{'leg':<12} {'n':>3} {'hit%':>5} {'avgP':>6}")
for leg, r in per.sort_values("hit", ascending=False).iterrows():
    print(f"{leg:<12} {int(r['n']):>3} {100*r['hit']:>4.0f}% {r['p']:>5.0%}")

# ---- plots ----
p, y, idx = results["T1"]["p"], results["T1"]["y"], results["T1"]["idx"]
base = results["T1"]["base"]
fig = plt.figure(figsize=(16, 10))

# lift curve
ax = fig.add_subplot(2, 2, 1)
ks = [0.1, 0.2, 0.3, 0.4, 0.5, 1.0]
hits = [y[np.argsort(-p)[:int(len(p) * k)]].mean() for k in ks]
ax.plot([int(k * 100) for k in ks], [h * 100 for h in hits], marker="o", color="#14568c")
ax.axhline(base * 100, color="k", ls="--", lw=0.8, label=f"base {base*100:.0f}%")
ax.set_xlabel("top % of candidates"); ax.set_ylabel("win rate %")
ax.set_title("Lift — does ranking beat base? (T1, walk-forward OOS)")
ax.legend(); ax.grid(alpha=0.3)

# calibration
ax = fig.add_subplot(2, 2, 2)
bins = np.linspace(0, 1, 6)
bins[0], bins[-1] = -0.001, 1.001
centers, actuals, ns = [], [], []
for b0, b1 in zip(bins[:-1], bins[1:]):
    m = (p > b0) & (p <= b1)
    if m.sum() >= 5:
        centers.append((b0 + b1) / 2)
        actuals.append(y[m].mean())
        ns.append(m.sum())
ax.plot(centers, actuals, marker="o", color="#c0392b", label="actual")
ax.plot([0, 1], [0, 1], "k--", lw=0.8, label="perfect")
ax.set_xlabel("predicted probability"); ax.set_ylabel("actual hit rate")
ax.set_title(f"Calibration (Brier={results['T1']['brier']:.3f}) — overconfident if below line")
ax.legend(); ax.grid(alpha=0.3)

# per-leg hit rates
ax = fig.add_subplot(2, 2, 3)
per2 = per.sort_values("hit")
ax.barh([str(x) for x in per2.index], per2["hit"] * 100, color="#14568c")
ax.axvline(base * 100, color="k", ls="--", lw=0.8, label=f"base {base*100:.0f}%")
ax.set_xlabel("OOS hit rate %"); ax.set_title("Per-leg out-of-sample hit rate (T1)")
ax.legend(); ax.grid(alpha=0.3)

# candidate gate effect + z_rec vs px_dist_low scatter
ax = fig.add_subplot(2, 2, 4)
sc = ax.scatter(df["px_dist_low"] * 100, df["z_rec"], c=df["T1"], cmap="RdYlGn", s=30, alpha=0.8)
cbar = plt.colorbar(sc, ax=ax)
cbar.set_label("T1 target (1=win)")
ax.set_xlabel("price distance from post-arm low %")
ax.set_ylabel("z recovery")
ax.set_title(f"Candidate set (n={len(df)}) — price-vs-z recovery, coloured by outcome")
ax.grid(alpha=0.3)

plt.tight_layout()
plt.savefig("backtesting/plots/ml_v3.png", dpi=110)
print("\nsaved backtesting/plots/ml_v3.png")

# top candidates table
order = np.argsort(-p)[:12]
print("\n=== TOP-12 OOS CANDIDATES (T1, walk-forward) ===")
print(f"{'leg':<12} {'arm':>5} {'prob':>6} {'outcome':>7}")
for k in order:
    row = df_.iloc[idx[k]]
    print(f"{row['leg']:<12} {int(row['arm_i']):>5} {p[k]:>5.0%} {'WIN' if y[k] else 'LOSS':>7}")
