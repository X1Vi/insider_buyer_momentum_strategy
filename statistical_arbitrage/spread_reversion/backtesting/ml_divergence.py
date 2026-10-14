#!/usr/bin/env python3
"""
ML divergence ranking — Stage 1 event detector + Stage 2 probability model.
Candidates: every z<-3 extreme dislocation (arm) across all pairs, dedup 5 bars.
Features (ALL causal — only data <= bar i): pair z, z-min/slope/recovery,
spread vol, rolling beta, price returns, drawdown/distance, vol, and the
continuous price-z "low" divergence features.
Target (quick-profit): does the bought leg (pa) hit close >= +3% before
close <= -2% within the next 10 trading days? (close-based; path order checked)
Train on first 60% of the data, test on last 40% (purely informational).
Models: Logistic Regression, Random Forest, XGBoost, LightGBM.
"""
import glob
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import roc_auc_score, accuracy_score
from xgboost import XGBClassifier
from lightgbm import LGBMClassifier

SPLIT, W_BETA, W_Z, Z_ARM, L = 0.6, 252, 60, -3.0, 3
TP, SL, WIN_DAYS = 0.03, 0.02, 10

files = sorted(glob.glob("backtesting/data/*.csv"))
names = [f.split("/")[-1][:-4] for f in files]
data = {nm: pd.read_csv(f)["close"].values for nm, f in zip(names, files)}
n_global = min(len(d) for d in data.values())
split_idx = int(SPLIT * n_global)
print(f"universe {len(names)} names, bars ~{n_global}, train<{split_idx} test>={split_idx}")


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


def is_confirmed_low(j, c, L):
    lft = c[max(0, j - L):j]
    rgt = c[j + 1:j + L + 1]
    return len(lft) and len(rgt) and c[j] <= lft.min() and c[j] <= rgt.min()


def quick_target(pa, i):
    """Hit +3% close before -2% close within 10 days? (closes only)."""
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


FEATURES = ["z", "zmin5", "zmin10", "zmin20", "zslope1", "zslope3", "zrec",
            "svol20", "beta", "ret1", "ret3", "ret5", "ret10", "mom20",
            "dhigh20", "dlow20", "vol20", "lowchg", "lowzchg", "lowdays"]

events = []  # (leg, i, feat_values, target)
for a in range(len(names)):
    for b in range(a + 1, len(names)):
        A, B = names[a], names[b]
        pa, pb = data[A], data[B]
        n = min(len(pa), len(pb))
        if n < W_BETA + W_Z + WIN_DAYS + 30:
            continue
        pa, pb = pa[:n], pb[:n]
        z, beta = rolling_beta_z(pa, pb)
        last_low_px = last_low_z = last_low_i = None
        i = 0
        while i < n:
            # maintain causal confirmed lows (confirmed at i = j+L)
            j = i - L
            if j >= L and is_confirmed_low(j, pa, L):
                last_low_px, last_low_z, last_low_i = pa[j], z[j], j
            # arm event
            if z[i] < Z_ARM and i >= W_BETA + W_Z:
                lo = max(0, i - 20)
                feats = {
                    "z": z[i],
                    "zmin5": z[max(0, i - 5):i + 1].min(),
                    "zmin10": z[max(0, i - 10):i + 1].min(),
                    "zmin20": z[lo:i + 1].min(),
                    "zslope1": z[i] - z[i - 1],
                    "zslope3": z[i] - z[i - 3],
                    "zrec": z[i] - z[lo:i + 1].min(),
                    "svol20": np.std(np.log(pa[lo:i + 1])) if i - lo > 5 else 0.0,
                    "beta": beta[i],
                    "ret1": pa[i] / pa[i - 1] - 1,
                    "ret3": pa[i] / pa[i - 3] - 1,
                    "ret5": pa[i] / pa[i - 5] - 1,
                    "ret10": pa[i] / pa[i - 10] - 1,
                    "mom20": pa[i] / pa[i - 20] - 1,
                    "dhigh20": pa[i] / pa[lo:i + 1].max() - 1,
                    "dlow20": pa[i] / pa[lo:i + 1].min() - 1,
                    "vol20": np.std(np.diff(np.log(pa[lo:i + 1]))),
                    "lowchg": pa[i] / last_low_px - 1 if last_low_px else 0.0,
                    "lowzchg": z[i] - last_low_z if last_low_z is not None else 0.0,
                    "lowdays": i - last_low_i if last_low_i is not None else 60,
                }
                events.append((A, i, [feats[f] for f in FEATURES], quick_target(pa, i)))
                i += 5
            i += 1

df = pd.DataFrame([e[2] for e in events], columns=FEATURES)
df["leg"] = [e[0] for e in events]
df["i"] = [e[1] for e in events]
df["y"] = [e[3] for e in events]
train = df[df["i"] < split_idx].reset_index(drop=True)
test = df[df["i"] >= split_idx].reset_index(drop=True)
print(f"\nevents: {len(df)}   train={len(train)} (y=1: {train['y'].mean():.0%})   "
      f"test={len(test)} (y=1: {test['y'].mean():.0%})")

Xtr, ytr = train[FEATURES].values, train["y"].values
Xte, yte = test[FEATURES].values, test["y"].values

models = {
    "LogisticRegression": LogisticRegression(max_iter=2000),
    "RandomForest": RandomForestClassifier(n_estimators=300, min_samples_leaf=3, random_state=1),
    "XGBoost": XGBClassifier(n_estimators=300, max_depth=4, learning_rate=0.05,
                             subsample=0.8, colsample_bytree=0.8, random_state=1,
                             eval_metric="logloss", use_label_encoder=False),
    "LightGBM": LGBMClassifier(n_estimators=300, max_depth=4, learning_rate=0.05,
                               subsample=0.8, colsample_bytree=0.8, random_state=1,
                               verbose=-1),
}

print("\n=== TEST (out-of-sample, purely informational) ===")
base = yte.mean()
print(f"base rate (P(quick +3% win)): {base:.0%}")
for name, m in models.items():
    m.fit(Xtr, ytr)
    p = m.predict_proba(Xte)[:, 1]
    auc = roc_auc_score(yte, p)
    top = int(len(p) * 0.2)
    idx = np.argsort(-p)[:top]
    top_hit = yte[idx].mean()
    acc = accuracy_score(yte, (p > 0.5).astype(int))
    print(f"  {name:<20} AUC={auc:.3f}  acc={acc:.0%}  top20% hit={top_hit:.0%}  "
          f"(lift={top_hit / base:.1f}x)")

# ranking table from the best model (XGBoost)
best = models["XGBoost"]
p = best.predict_proba(Xte)[:, 1]
order = np.argsort(-p)[:15]
print("\n=== TOP-15 TEST CANDIDATES (highest model probability) ===")
print(f"{'leg':<12} {'day':>5} {'prob':>6} {'actual':>6}   z  zrec  ret5  lowchg lowzchg")
for k in order:
    row = test.iloc[k]
    print(f"{row['leg']:<12} {int(row['i']):>5} {p[k]:>5.0%} {'WIN' if row['y'] else 'LOSS':>6}   "
          f"{row['z']:+.1f} {row['zrec']:+.1f} {row['ret5']*100:+.1f}% {row['lowchg']*100:+.1f}% "
          f"{row['lowzchg']:+.1f}")

# feature importance (XGBoost)
imp = sorted(zip(FEATURES, best.feature_importances_), key=lambda t: -t[1])[:10]
print("\n=== TOP FEATURES (XGBoost importance) ===")
for f, v in imp:
    print(f"  {f:<10} {v:.3f}")

# ROC plot
from sklearn.metrics import roc_curve
fpr, tpr, _ = roc_curve(yte, p)
plt.figure(figsize=(7, 6))
plt.plot(fpr, tpr, lw=1.5, label=f"XGBoost AUC={roc_auc_score(yte, p):.3f}")
plt.plot([0, 1], [0, 1], "k--", lw=0.8)
plt.xlabel("FPR"); plt.ylabel("TPR"); plt.title("Out-of-sample ROC — quick +3%/-2% target")
plt.legend(); plt.grid(alpha=0.3)
plt.tight_layout()
plt.savefig("backtesting/plots/ml_roc.png", dpi=110)
print("\nsaved backtesting/plots/ml_roc.png")
