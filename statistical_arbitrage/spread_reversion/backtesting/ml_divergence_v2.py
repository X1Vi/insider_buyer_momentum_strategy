#!/usr/bin/env python3
"""
ML v2 — post-extreme TRAJECTORY pipeline.
  z < -3 = ARM (start of observation window, OBS=10 bars).
  At the observation end we extract TRAJECTORY features (z recovery, price
  stabilisation, divergence, volatility contraction) — all causal — and ask:
  "given the post-extreme trajectory, will a quick +3% before -2% (10d) win?"
  Variants: ALL arms vs RECOVERY-ONLY (z has started recovering by OBS end).
  Dedupe by (leg, arm-day). Train 60% / test 40%. Plots: ROC, precision-vs-base,
  feature importance, avg z/price trajectory winners vs losers, divergence plane.
"""
import glob
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import roc_auc_score, roc_curve, accuracy_score
from xgboost import XGBClassifier
from lightgbm import LGBMClassifier

SPLIT, W_BETA, W_Z, Z_ARM, L, OBS = 0.6, 252, 60, -3.0, 3, 10
TP, SL, WIN_DAYS = 0.03, 0.02, 10

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


def quick_target(pa, i):
    entry = pa[i]
    for k in range(1, WIN_DAYS + 1):
        if i + k >= len(pa):
            return 0
        c = pa[i + k]
        if c >= entry * (1 + TP):
            return 1
        if c <= entry * (1 - SL):
            return 0
    return 0


FEATURES = ["z_arm", "z_now", "z_min", "z_rec", "z_rec_speed", "days_zmin",
            "zslope_win", "zslope_short", "px_dist_low", "px_ret_arm",
            "ret_last2", "ret_last3", "ret_last5", "days_pxlow", "div",
            "vol_ratio", "svol20", "beta", "leg_id"]


def build():
    events = []          # (leg, arm_i, feats, target, z_arm, z_path, px_path)
    for a in range(len(names)):
        for b in range(a + 1, len(names)):
            A, B = names[a], names[b]
            pa, pb = data[A], data[B]
            n = min(len(pa), len(pb))
            if n < W_BETA + W_Z + OBS + WIN_DAYS + 30:
                continue
            pa, pb = pa[:n], pb[:n]
            z, beta = rolling_beta_z(pa, pb)
            i = 0
            while i < n:
                if z[i] < Z_ARM and i >= W_BETA + W_Z and i + OBS + WIN_DAYS < n:
                    e = i + OBS
                    seg_z = z[i:e + 1]
                    seg_p = pa[i:e + 1]
                    zm = seg_z.min()
                    pmin = seg_p.min()
                    dzm = int(np.argmin(seg_z))
                    dpm = int(np.argmin(seg_p))
                    vf = np.std(np.diff(np.log(pa[i:i + 6])))
                    vl = np.std(np.diff(np.log(pa[e - 5:e + 1])))
                    feats = {
                        "z_arm": z[i],
                        "z_now": z[e],
                        "z_min": zm,
                        "z_rec": z[e] - zm,
                        "z_rec_speed": (z[e] - zm) / max(dzm, 1),
                        "days_zmin": dzm,
                        "zslope_win": (z[e] - z[i]) / OBS,
                        "zslope_short": z[e] - z[e - 2],
                        "px_dist_low": pa[e] / pmin - 1,
                        "px_ret_arm": pa[e] / pa[i] - 1,
                        "ret_last2": pa[e] / pa[e - 2] - 1,
                        "ret_last3": pa[e] / pa[e - 3] - 1,
                        "ret_last5": pa[e] / pa[e - 5] - 1,
                        "days_pxlow": dpm,
                        "div": max(0.0, z[e] - zm) * max(0.0, pa[i] / pmin - 1) if pmin > 0 else 0.0,
                        "vol_ratio": vl / max(vf, 1e-9),
                        "svol20": np.std(np.log(pa[e - 19:e + 1])),
                        "beta": beta[e],
                        "leg_id": a,
                    }
                    events.append((A, i, [feats[f] for f in FEATURES],
                                   quick_target(pa, e), z[i], seg_z, seg_p / pa[i] - 1))
                    i += 5
                i += 1
    # dedupe by (leg, arm-day) keeping the strongest (min z_arm)
    best = {}
    for ev in events:
        key = (ev[0], ev[1])
        if key not in best or ev[4] < best[key][4]:
            best[key] = ev
    return list(best.values())


def evaluate(Xtr, ytr, Xte, yte):
    models = {
        "LogisticRegression": LogisticRegression(max_iter=2000),
        "RandomForest": RandomForestClassifier(n_estimators=300, min_samples_leaf=3, random_state=1),
        "XGBoost": XGBClassifier(n_estimators=300, max_depth=4, learning_rate=0.05,
                                 subsample=0.8, colsample_bytree=0.8, random_state=1),
        "LightGBM": LGBMClassifier(n_estimators=300, max_depth=4, learning_rate=0.05,
                                   subsample=0.8, colsample_bytree=0.8, random_state=1, verbose=-1),
    }
    out = {}
    for name, m in models.items():
        m.fit(Xtr, ytr)
        p = m.predict_proba(Xte)[:, 1]
        auc = roc_auc_score(yte, p)
        top = int(len(p) * 0.2)
        idx = np.argsort(-p)[:top]
        top_hit = yte[idx].mean()
        acc = accuracy_score(yte, (p > 0.5).astype(int))
        out[name] = {"p": p, "auc": auc, "top_hit": top_hit, "acc": acc, "model": m}
        print(f"    {name:<20} AUC={auc:.3f}  acc={acc:.0%}  top20% hit={top_hit:.0%}")
    return out


def report(test_df, res, base, label):
    print(f"\n=== {label} — TEST (informational) base rate={base:.0%} ===")
    res = evaluate(np.array(train_df[FEATURES]), train_df["y"].values,
                   np.array(test_df[FEATURES]), test_df["y"].values)
    return res


events = build()
df = pd.DataFrame([e[2] for e in events], columns=FEATURES)
df["leg"] = [e[0] for e in events]
df["i"] = [e[1] for e in events]
df["y"] = [e[3] for e in events]
df["z_arm"] = [e[4] for e in events]
df["zpath"] = [e[5] for e in events]
df["pxpath"] = [e[6] for e in events]
print(f"events (deduped by leg+day): {len(df)}")

all_arm = df
rec_only = df[df["z_rec"] > 0.05].reset_index(drop=True)
all_arm = all_arm.reset_index(drop=True)

for label, ds in (("ALL ARMS", all_arm), ("RECOVERY-ONLY (z rec >0.05)", rec_only)):
    train_df = ds[ds["i"] < split_idx].reset_index(drop=True)
    test_df = ds[ds["i"] >= split_idx].reset_index(drop=True)
    print(f"\n{label}: total={len(ds)}  train={len(train_df)} (y={train_df['y'].mean():.0%})  "
          f"test={len(test_df)} (y={test_df['y'].mean():.0%})")
    Xtr = np.array(train_df[FEATURES]); ytr = train_df["y"].values
    Xte = np.array(test_df[FEATURES]); yte = test_df["y"].values
    res = evaluate(Xtr, ytr, Xte, yte)
    base = yte.mean()
    print(f"  top20% lift: " + "  ".join(f"{k}={v['top_hit']/base:.2f}x" for k, v in res.items()))
    if label.startswith("ALL"):
        all_res, all_test = res, test_df

# ---- plots (on ALL-ARMS) ----
test_df = all_test
yte = test_df["y"].values
base = yte.mean()
xgb = all_res["XGBoost"]
p = xgb["p"]

fig = plt.figure(figsize=(16, 10))

# 1) ROC
ax = fig.add_subplot(2, 2, 1)
for name in ("XGBoost", "LightGBM", "RandomForest", "LogisticRegression"):
    fpr, tpr, _ = roc_curve(yte, all_res[name]["p"])
    ax.plot(fpr, tpr, lw=1.4, label=f"{name} (AUC={all_res[name]['auc']:.3f})")
ax.plot([0, 1], [0, 1], "k--", lw=0.8)
ax.set_xlabel("FPR"); ax.set_ylabel("TPR"); ax.set_title("Out-of-sample ROC — quick +3%/-2% win")
ax.legend(); ax.grid(alpha=0.3)

# 2) precision by model-decile (top 10%..50%)
ax = fig.add_subplot(2, 2, 2)
deciles = [0.1, 0.2, 0.3, 0.4, 0.5]
for name in ("XGBoost", "LightGBM", "RandomForest", "LogisticRegression"):
    pp = all_res[name]["p"]
    hits = []
    for d in deciles:
        idx = np.argsort(-pp)[:int(len(pp) * d)]
        hits.append(yte[idx].mean())
    ax.plot([int(d * 100) for d in deciles], [h * 100 for h in hits], marker="o", label=name)
ax.axhline(base * 100, color="k", ls="--", lw=0.8, label=f"base {base*100:.0f}%")
ax.set_xlabel("top % of candidates"); ax.set_ylabel("win rate %")
ax.set_title("Precision by rank (does ranking beat base?)")
ax.legend(); ax.grid(alpha=0.3)

# 3) feature importance
ax = fig.add_subplot(2, 2, 3)
imp = sorted(zip(FEATURES, xgb["model"].feature_importances_), key=lambda t: -t[1])[:12]
ax.barh([f for f, _ in imp][::-1], [v for _, v in imp][::-1], color="#14568c")
ax.set_title("XGBoost feature importance (trajectory features)")

# 4) avg trajectory winners vs losers (TEST)
ax = fig.add_subplot(2, 2, 4)
zp = np.array([np.array(v) for v in test_df["zpath"]])
xp = np.array([np.array(v) for v in test_df["pxpath"]])
x = np.arange(zp.shape[1])
ax.plot(x, zp[yte == 1].mean(0), color="green", lw=1.6, label="winners (avg z)")
ax.plot(x, zp[yte == 0].mean(0), color="red", lw=1.6, label="losers (avg z)")
ax2 = ax.twinx()
ax2.plot(x, xp[yte == 1].mean(0) * 100, color="green", ls="--", lw=1.0, label="winners (avg price%)")
ax2.plot(x, xp[yte == 0].mean(0) * 100, color="red", ls="--", lw=1.0, label="losers (avg price%)")
ax.set_xlabel("bars since ARM"); ax.set_ylabel("z-score")
ax2.set_ylabel("price % since arm")
ax.set_title("TEST: average post-ARM trajectory — winners vs losers")
ax.legend(loc="upper left"); ax.grid(alpha=0.3)

plt.tight_layout()
plt.savefig("backtesting/plots/ml_v2.png", dpi=110)
print("\nsaved backtesting/plots/ml_v2.png")

# ranking table (XGBoost, test)
order = np.argsort(-p)[:12]
print("\n=== TOP-12 TEST CANDIDATES (XGBoost) ===")
print(f"{'leg':<12} {'day':>5} {'prob':>6} {'outcome':>7}  z_arm z_rec px_ret div")
for k in order:
    row = test_df.iloc[k]
    print(f"{row['leg']:<12} {int(row['i']):>5} {p[k]:>5.0%} {'WIN' if row['y'] else 'LOSS':>7}  "
          f"{row['z_arm']:+.1f} {row['z_rec']:+.1f} {row['px_ret_arm']*100:+.1f}% {row['div']*100:.1f}%")
