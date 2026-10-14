#!/usr/bin/env python3
"""
Plot the ACTUAL TRADES the model takes OUT-OF-SAMPLE (test period only).
Train XGBoost on train events; on test events, "take a trade" when predicted
probability of the quick +3%/-2% win >= THRESH (fallback: top-N). For each
trade: entry = observation end (arm_i + OBS), causal. Plots per-leg price
charts (green ^ = WIN, red ^ = LOSS) and the arm->entry->+10d path.
"""
import glob
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from xgboost import XGBClassifier

SPLIT, W_BETA, W_Z, Z_ARM, L, OBS = 0.6, 252, 60, -3.0, 3, 10
TP, SL, WIN_DAYS = 0.03, 0.02, 10
THRESH, N_FALLBACK = 0.60, 15

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
    events = []
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
                    zm, pmin = seg_z.min(), seg_p.min()
                    dzm, dpm = int(np.argmin(seg_z)), int(np.argmin(seg_p))
                    vf = np.std(np.diff(np.log(pa[i:i + 6])))
                    vl = np.std(np.diff(np.log(pa[e - 5:e + 1])))
                    feats = {
                        "z_arm": z[i], "z_now": z[e], "z_min": zm,
                        "z_rec": z[e] - zm, "z_rec_speed": (z[e] - zm) / max(dzm, 1),
                        "days_zmin": dzm, "zslope_win": (z[e] - z[i]) / OBS,
                        "zslope_short": z[e] - z[e - 2], "px_dist_low": pa[e] / pmin - 1,
                        "px_ret_arm": pa[e] / pa[i] - 1, "ret_last2": pa[e] / pa[e - 2] - 1,
                        "ret_last3": pa[e] / pa[e - 3] - 1, "ret_last5": pa[e] / pa[e - 5] - 1,
                        "days_pxlow": dpm,
                        "div": max(0.0, z[e] - zm) * max(0.0, pa[i] / pmin - 1) if pmin > 0 else 0.0,
                        "vol_ratio": vl / max(vf, 1e-9), "svol20": np.std(np.log(pa[e - 19:e + 1])),
                        "beta": beta[e], "leg_id": a,
                    }
                    events.append((A, i, [feats[f] for f in FEATURES], quick_target(pa, e),
                                   z[i], seg_z, seg_p / pa[i] - 1, pa, i + OBS))
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
df["y"] = [e[3] for e in evs]
df["z_arm"] = [e[4] for e in evs]
df["zpath"] = [e[5] for e in evs]
df["pxpath"] = [e[6] for e in evs]
df["pa"] = [e[7] for e in evs]
df["entry_i"] = [e[8] for e in evs]

train = df[df["arm_i"] < split_idx].reset_index(drop=True)
test = df[df["arm_i"] >= split_idx].reset_index(drop=True)
model = XGBClassifier(n_estimators=300, max_depth=4, learning_rate=0.05,
                      subsample=0.8, colsample_bytree=0.8, random_state=1)
model.fit(train[FEATURES].values, train["y"].values)
p = model.predict_proba(test[FEATURES].values)[:, 1]

# ---- the model's actual test trades ----
trades = test.copy()
trades["prob"] = p
sel = trades[trades["prob"] >= THRESH]
if len(sel) < 3:
    sel = trades.nlargest(N_FALLBACK, "prob")
    print(f"threshold {THRESH} gave {len(trades[trades['prob']>=THRESH])} — using top {N_FALLBACK}")
sel = sel.sort_values("prob", ascending=False)

print(f"\n=== MODEL'S ACTUAL OUT-OF-SAMPLE TRADES ({len(sel)}) ===")
print(f"{'leg':<12} {'arm':>5} {'entry':>5} {'prob':>6} {'outcome':>7} {'fwd5':>7} {'fwd10':>7}")
for _, r in sel.iterrows():
    e = r["entry_i"]
    pa = r["pa"]
    f5 = 100 * (pa[e + 5] / pa[e] - 1) if e + 5 < len(pa) else float("nan")
    f10 = 100 * (pa[min(e + 10, len(pa) - 1)] / pa[e] - 1) if e + 10 < len(pa) else float("nan")
    print(f"{r['leg']:<12} {int(r['arm_i']):>5} {int(e):>5} {r['prob']:>5.0%} "
          f"{'WIN' if r['y'] else 'LOSS':>7} {f5:>+6.1f}% {f10:>+6.1f}%")

print(f"\nsummary: {len(sel)} trades, "
      f"{100*sel['y'].mean():.0f}% hit the +3%/-2% target, "
      f"avg prob={sel['prob'].mean():.0%}")

# ---- plots ----
os_ = __import__("os")
os_.makedirs("backtesting/plots/model_trades", exist_ok=True)

# per-leg price charts (test period) with trade markers
for leg in sorted(sel["leg"].unique()):
    pa = data[leg]
    n = len(pa)
    rows = sel[sel["leg"] == leg]
    fig, ax = plt.subplots(figsize=(14, 5))
    ax.plot(np.arange(n), pa, color="#1f77b4", lw=1.1)
    ax.axvline(split_idx, color="black", ls="--", lw=1, alpha=0.7, label="train|test split")
    for _, r in rows.iterrows():
        e = int(r["entry_i"])
        c = "green" if r["y"] else "red"
        ax.scatter(e, r["pa"][e], marker="^", s=90, color=c, edgecolors="k", lw=0.6, zorder=6)
        ax.annotate(f"{r['prob']:.0%}\n{'WIN' if r['y'] else 'LOSS'}",
                    (e, r["pa"][e]), textcoords="offset points", xytext=(0, 8),
                    ha="center", fontsize=7, color=c, fontweight="bold")
    ax.set_xlim(split_idx - 30, n + 5)
    ax.set_ylabel("Price ₹")
    ax.set_title(f"{leg} — MODEL TEST TRADES (green=hit +3% target, red=missed)")
    ax.legend(loc="upper left"); ax.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(f"backtesting/plots/model_trades/{leg}.png", dpi=110)
    plt.close(fig)
    print(f"plot: backtesting/plots/model_trades/{leg}.png")

# arm -> entry -> +10d path, winners vs losers
fig, ax = plt.subplots(figsize=(12, 6))
for _, r in sel.iterrows():
    e = int(r["entry_i"])
    pa = r["pa"]
    path = np.array([r["pa"][min(k, len(pa) - 1)] / r["pa"][e] - 1 for k in range(r["arm_i"], e + WIN_DAYS + 1)])
    x = np.arange(len(path)) - (e - r["arm_i"])
    ax.plot(x, path * 100, color=("green" if r["y"] else "red"), alpha=0.6, lw=1.0)
ax.axvline(0, color="k", ls="--", lw=0.8)
ax.axhline(0, color="k", lw=0.6)
ax.set_xlabel("bars (arm=start, 0=entry, +10=forward)")
ax.set_ylabel("% from entry")
ax.set_title("Model test trades: arm -> ENTRY(0) -> +10d  (green=hit +3%, red=missed)")
ax.grid(alpha=0.3)
plt.tight_layout()
plt.savefig("backtesting/plots/model_trades_paths.png", dpi=110)
print("plot: backtesting/plots/model_trades_paths.png")
