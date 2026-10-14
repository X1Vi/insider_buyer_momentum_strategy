#!/usr/bin/env python3
"""Plot the basis vs pairs trades per pair from the WATCH backtest.

Reads basis_trades.csv / pairs_trades.csv (written by backtest_basis.py) and the
price CSVs, then draws one figure per distinct (leg, partner) into
backtesting/basis/trade_graphs/:

  top:    price of A, B and the equal-weight index (normalized to A)
  bottom: the A/B z-score

Signals are marked with clear triangles:
  GREEN  UP-triangle (^) labelled BUY   at the entry bar
  RED    DOWN-triangle (v) labelled SELL at the exit bar
Basis trades are offset slightly left of the bar, pairs slightly right, so both
are visible when they share the same entry/exit.

Run:
  .venv/bin/python backtesting/basis/plot_basis_trades.py
"""
import glob
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")
PLOTDIR = os.path.join(HERE, "trade_graphs")

OFFSET = {"BASIS": -0.25, "PAIRS": +0.25}
COL = {"BASIS": "#00703c", "PAIRS": "#8a0000"}


def load_closes(name):
    return pd.read_csv(os.path.join(DATA, f"{name}.csv"))["close"].values.astype(float)


def equal_weight_index(names, data):
    n = min(len(v) for v in data.values())
    rets = np.array([data[nm][1:n] / data[nm][:n - 1] - 1.0 for nm in names])
    idx = np.empty(n)
    idx[0] = 1.0
    for t in range(1, n):
        idx[t] = idx[t - 1] * (1.0 + rets[:, t - 1].mean())
    return idx


def rolling_z(pa, pb):
    W_BETA, W_Z = 252, 60
    sla = pd.Series(np.log(pa)); slb = pd.Series(np.log(pb))
    beta = (sla.rolling(W_BETA).cov(slb) / slb.rolling(W_BETA).var()).values
    alpha = (sla.rolling(W_BETA).mean() - pd.Series(beta) * slb.rolling(W_BETA).mean()).values
    spread = (sla - pd.Series(beta) * slb - pd.Series(alpha)).values
    mu = pd.Series(spread).rolling(W_Z).mean().values
    sd = pd.Series(spread).rolling(W_Z).std().values
    z = np.where(sd > 1e-9, (spread - mu) / np.maximum(sd, 1e-9), 0.0)
    return z


def mark(ax_price, ax_z, bar, val_price, val_z, kind, side, s_price, s_z):
    """side: 'BUY' (green up) or 'SELL' (red down)."""
    x = bar + OFFSET[kind]
    if side == "BUY":
        mc, mkc, dy, lbl = "tab:green", "^", 10, "BUY"
    else:
        mc, mkc, dy, lbl = "tab:red", "v", -18, "SELL"
    ax_price.scatter(x, val_price, marker=mkc, s=s_price, color=mc, edgecolors="k", lw=0.7, zorder=6)
    ax_price.annotate(lbl, (x, val_price), textcoords="offset points",
                      xytext=(0, dy), ha="center", fontsize=8, fontweight="bold", color=mc)
    ax_z.scatter(x, val_z, marker=mkc, s=s_z, color=mc, edgecolors="k", lw=0.5, zorder=6)


def main():
    names = sorted(os.path.basename(f)[:-4] for f in glob.glob(os.path.join(DATA, "*.csv")))
    data = {nm: load_closes(nm) for nm in names}
    idx = equal_weight_index(names, data)
    os.makedirs(PLOTDIR, exist_ok=True)

    basis = pd.read_csv(os.path.join(HERE, "basis_trades.csv"))
    pairs = pd.read_csv(os.path.join(HERE, "pairs_trades.csv"))
    basis["kind"] = "BASIS"
    pairs["kind"] = "PAIRS"
    all_tr = pd.concat([basis, pairs], ignore_index=True)

    pairs_group = list(all_tr.groupby(["leg", "partner"]))
    print(f"plotting {len(pairs_group)} distinct pairs -> {PLOTDIR}")

    overview_fig, overview_ax = plt.subplots(figsize=(11, 5))
    for k, ((leg, partner), grp) in enumerate(sorted(pairs_group)):
        pa, pb = data[leg], data[partner]
        n = min(len(pa), len(pb))
        z = rolling_z(pa[:n], pb[:n])
        lo = max(int(grp["entry"].min()) - 60, 0)
        hi = min(int(grp["exit"].max()) + 60, n - 1)
        bars = np.arange(lo, hi + 1)

        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 6.5), sharex=True,
                                       gridspec_kw={"height_ratios": [2.4, 1]})
        ax1.plot(bars, pa[lo:hi + 1], color="#1f77b4", lw=1.1, label=leg)
        ax1.plot(bars, pb[lo:hi + 1], color="#ff7f0e", lw=1.1, alpha=0.8, label=partner)
        ax1.plot(bars, idx[lo:hi + 1] / idx[lo] * pa[lo], color="#555", lw=1.0,
                 ls="--", label="index(→A)")
        ax1.set_ylabel("price"); ax1.grid(alpha=0.25)
        ax1.set_title(f"{leg} / {partner}  — WATCH basis vs pairs trades", fontsize=12)

        ax2.plot(bars, z[lo:hi + 1], color="tab:purple", lw=0.9)
        ax2.axhline(0, color="k", ls=":", lw=0.8)
        ax2.axhline(-3.0, color="tab:red", ls="--", lw=1.0)
        ax2.set_ylabel("z-score"); ax2.grid(alpha=0.25)

        for kind in ("BASIS", "PAIRS"):
            sub = grp[grp["kind"] == kind]
            for _, tr in sub.iterrows():
                e, x = int(tr["entry"]), int(tr["exit"])
                # BUY at entry, SELL at exit
                mark(ax1, ax2, e, pa[e], z[e], kind, "BUY", 220, 120)
                mark(ax1, ax2, x, pa[x], z[x], kind, "SELL", 220, 120)
                ax1.annotate(f"{tr['net']:+.0f}\n{tr['reason']}", (e + OFFSET[kind], pa[e]),
                             textcoords="offset points", xytext=(0, 26), ha="center",
                             fontsize=7, fontweight="bold", color=COL[kind])

        # legend
        ax1.scatter([], [], marker="^", color="tab:green", edgecolors="k", label="BUY (entry)")
        ax1.scatter([], [], marker="v", color="tab:red", edgecolors="k", label="SELL (exit)")
        ax1.scatter([], [], marker="o", color=COL["BASIS"], label="basis")
        ax1.scatter([], [], marker="o", color=COL["PAIRS"], label="pairs")
        ax1.legend(loc="upper left", fontsize=8)
        ax1.set_xlim(lo, hi)
        plt.tight_layout()
        out = os.path.join(PLOTDIR, f"{leg}_{partner}.png")
        plt.savefig(out, dpi=110)
        plt.close(fig)
        print(f"  saved {out}")

        bb = grp[grp["kind"] == "BASIS"]
        pp = grp[grp["kind"] == "PAIRS"]
        eqb = np.cumsum(bb["net"].values)
        eqp = np.cumsum(pp["net"].values)
        overview_ax.plot(range(len(eqb)), eqb, "o-", color=COL["BASIS"],
                         label=f"{leg} basis" if k == 0 else None)
        overview_ax.plot(range(len(eqp)), eqp, "s-", color=COL["PAIRS"], alpha=0.7,
                         label=f"{leg} pairs" if k == 0 else None)

    overview_ax.axhline(0, color="k", ls="--", lw=0.8)
    overview_ax.set_title("per-pair cumulative net (basis vs pairs)")
    overview_ax.set_ylabel("cum net Rs"); overview_ax.grid(alpha=0.3)
    overview_ax.legend(fontsize=8)
    plt.tight_layout()
    overview = os.path.join(PLOTDIR, "_overview.png")
    plt.savefig(overview, dpi=110)
    plt.close()
    print(f"  saved {overview}")


if __name__ == "__main__":
    main()
