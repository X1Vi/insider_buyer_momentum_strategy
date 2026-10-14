#!/usr/bin/env python3
"""ML WATCH backtest — three models + raw reversion baseline, bias-hardened.

Pipeline:
    PAIR DATA -> detect z < -3 -> event -> 23 features
      -> {baseline | XGBoost | LightGBM | Logistic} -> raw probability
      -> WATCH gate (raw prob >= PROB_MIN) + EV filter
      -> mechanical LONG A/SHORT B, exit z>=0 / stop=5% notional / max-hold
      -> walk-forward VALIDATION + a FINAL UNTOUCHED hold-out TEST

Bias controls (built in):
  * No look-ahead: training events require arm+OBS+10 < fold boundary, so each
    event's forward label window ends before the period it predicts. Features
    use only prices up to the signal bar.
  * No overfitting: quarterly walk-forward for validation, plus a final test set
    (newest ~TEST_FRAC by time) that is NEVER touched during training or
    threshold choice. Thresholds (PROB_MIN/EV_MIN) are fixed a priori from the
    previous backtest, not tuned on the test set. Tree models use early stopping
    on a held-out slice.
  * Survivorship: every symbol in the data dir is used; no pair is dropped based
    on past performance. (Caveat: the universe is today's large caps — point-in-
    time index membership is unavailable, documented in the report.)

Usage:
  python run.py --model all            # baseline + xgboost + lightgbm + logistic
  python run.py --model xgboost
  python run.py --model baseline
  python run.py --data etf --model all
"""
import argparse
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import lightgbm as lgb
from lightgbm import LGBMClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier

from pipeline import (FEATURES, CAPITAL, PROB_MIN, EV_MIN, QUARTER, Q0, OBS,
                      load_data, build_events, simulate_trade, train_ev_stats)

TEST_FRAC = 0.20            # newest fraction of events = final untouched test
EVAL_FRAC = 0.30            # newest fraction of each training set = early-stop + EV stats

MODELS = {
    "xgboost": lambda: XGBClassifier(
        n_estimators=300, max_depth=4, learning_rate=0.05,
        subsample=0.8, colsample_bytree=0.8, random_state=1, eval_metric="logloss"),
    "lightgbm": lambda: LGBMClassifier(
        n_estimators=150, max_depth=3, learning_rate=0.05,
        subsample=0.8, colsample_bytree=0.8, min_child_samples=10,
        lambda_l2=1.0, random_state=1, verbose=-1, force_row_wise=True),
    "logistic": lambda: Pipeline([
        ("scale", StandardScaler()),
        ("lr", LogisticRegression(max_iter=5000, C=1.0, random_state=1)),
    ]),
}


def fit_model(name, X_fit, y_fit, X_ev, y_ev):
    """Fit with early stopping on the held-out eval slice (trees only)."""
    if name == "xgboost":
        m = XGBClassifier(n_estimators=300, max_depth=4, learning_rate=0.05,
                          subsample=0.8, colsample_bytree=0.8, random_state=1,
                          eval_metric="logloss", early_stopping_rounds=20)
        m.fit(X_fit, y_fit, eval_set=[(X_ev, y_ev)], verbose=False)
        return m
    if name == "lightgbm":
        m = LGBMClassifier(n_estimators=150, max_depth=3, learning_rate=0.05,
                           subsample=0.8, colsample_bytree=0.8,
                           min_child_samples=10, lambda_l2=1.0, random_state=1,
                           verbose=-1, force_row_wise=True)
        m.fit(X_fit, y_fit, eval_X=X_ev, eval_y=y_ev, eval_metric="logloss",
              callbacks=[lgb.early_stopping(20, verbose=False)])
        return m
    # logistic: no early stopping, fit on all training data
    m = Pipeline([("scale", StandardScaler()),
                  ("lr", LogisticRegression(max_iter=5000, C=1.0, random_state=1))])
    m.fit(np.vstack([X_fit, X_ev]), np.concatenate([y_fit, y_ev]))
    return m


def ev_filter_stats(tr_df, data, zcache):
    """avg win / avg loss (net Rs) of mechanically simulated TRAINING trades
    (used only to build the EV filter; computed from training events only)."""
    return train_ev_stats(tr_df, data, zcache)


def plot_pair(outdir, name, leg, partner, pa, pb, z, trs):
    """Per-pair PNG. Emphasises the ENTRY buy signals (green ^); exits shown
    small (red v) since we mainly care where entries happened. LONG A/SHORT B."""
    os.makedirs(os.path.join(outdir, "plots"), exist_ok=True)
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 7), sharex=True)

    idx = np.arange(len(pa))
    ax1.plot(idx, pa, color="tab:blue", label=leg, lw=1.1)
    ax1.plot(idx, pb, color="tab:orange", label=partner, lw=1.1, alpha=0.85)
    ax1.set_ylabel("price"); ax1.grid(alpha=0.25)
    ax1.set_title(f"{leg} vs {partner}  [{name} backtest — LONG {leg} / SHORT {partner}, entry buys marked]")

    ax2.plot(idx, z, color="tab:purple", lw=0.9)
    ax2.axhline(0, color="k", ls=":", lw=0.8)
    ax2.axhline(-3.0, color="tab:red", ls="--", lw=1.0)
    ax2.set_ylabel("z-score"); ax2.grid(alpha=0.25)

    for i, tr in enumerate(trs):
        ei, xi = tr["entry"], tr["exit"]
        ax1.scatter(ei, pa[ei], marker="^", s=180, color="tab:green",
                    edgecolors="k", lw=0.8, zorder=6,
                    label="BUY entry" if i == 0 else None)
        ax1.scatter(xi, pa[xi], marker="v", s=70, color="tab:red", alpha=0.8, zorder=5)
        ax1.annotate(f"{tr['net']:+.0f}", (ei, pa[ei]), textcoords="offset points",
                     xytext=(0, 10), fontsize=8, fontweight="bold", color="darkgreen")
        ax2.scatter(ei, z[ei], marker="^", s=150, color="tab:green",
                    edgecolors="k", lw=0.6, zorder=6)
        ax2.scatter(xi, z[xi], marker="v", s=60, color="tab:red", alpha=0.8, zorder=5)

    ax1.legend(loc="upper left")
    ax1.set_xlim(0, len(pa))
    plt.tight_layout()
    plt.savefig(os.path.join(outdir, "plots", f"{leg}_{partner}.png"), dpi=110)
    plt.close()


def portfolio(trades):
    """One position at a time (no overlapping entries) -> taken trades."""
    taken = []
    open_till = -1
    skipped = 0
    for tr in sorted(trades, key=lambda x: (x["entry"], x["leg"])):
        if tr["entry"] < open_till:
            skipped += 1
            continue
        open_till = tr["exit"]
        taken.append(tr)
    return taken, skipped


def run_model(name, outdir, data_path="backtesting/data"):
    os.makedirs(outdir, exist_ok=True)
    names, data = load_data(data_path)
    df, zcache, names, data = build_events(names, data)

    arm = df["arm"].values
    X = df[FEATURES].values
    y = df["t2"].values

    # ---- chronological split: newest TEST_FRAC = final untouched test ----
    order = np.argsort(arm)
    n_test = max(int(len(order) * TEST_FRAC), 5)
    test_idx = set(order[-n_test:].tolist())
    test_start = arm[order[-n_test]]
    is_test = np.array([k in test_idx for k in range(len(df))])

    # label window for an event = [arm+OBS, arm+OBS+10]; require it to end
    # strictly before any boundary t -> training event usable for fold t.
    label_end = arm + OBS + 10

    rows, all_trades, folds = [], [], []

    def gate_and_simulate(te_idx, p_cal, ev, fold):
        for j, k in enumerate(te_idx):
            row = df.iloc[k]
            r = {"leg": row["leg"], "partner": row["partner"], "arm": int(row["arm"]),
                 "prob": float(p_cal[j]), "ev": float(ev[j]), "t2": int(y[k]),
                 "fold": fold, "test": bool(is_test[k])}
            rows.append(r)
            if p_cal[j] >= PROB_MIN and ev[j] > EV_MIN:
                pa = data[row["leg"]]; pb = data[row["partner"]]
                z, _ = zcache.get((row["leg"], row["partner"]), (None, None))
                if z is None:
                    continue
                trd = simulate_trade(pa, pb, z, int(row["arm"]) + OBS)
                if trd:
                    all_trades.append({**trd, "leg": row["leg"], "partner": row["partner"],
                                       "arm": int(row["arm"]), "prob": float(p_cal[j]),
                                       "ev": float(ev[j]), "t2": int(y[k]), "fold": fold,
                                       "test": bool(is_test[k])})

    if name == "baseline":
        # rule-based: every z<-3 event is a signal (prob := 1.0)
        for k in range(len(df)):
            row = df.iloc[k]
            r = {"leg": row["leg"], "partner": row["partner"], "arm": int(row["arm"]),
                 "prob": 1.0, "ev": 0.0, "t2": int(y[k]), "fold": 0,
                 "test": bool(is_test[k])}
            rows.append(r)
            pa = data[row["leg"]]; pb = data[row["partner"]]
            z, _ = zcache.get((row["leg"], row["partner"]), (None, None))
            if z is None:
                continue
            trd = simulate_trade(pa, pb, z, int(row["arm"]) + OBS)
            if trd:
                all_trades.append({**trd, "leg": row["leg"], "partner": row["partner"],
                                   "arm": int(row["arm"]), "prob": 1.0, "ev": 0.0,
                                   "t2": int(y[k]), "fold": 0, "test": bool(is_test[k])})
    else:
        # ---- Phase 1: walk-forward VALIDATION (events before the test set) ----
        for t in range(Q0, int(test_start), QUARTER):
            tr = (label_end < t) & (~is_test)
            te = (arm >= t) & (arm < t + QUARTER) & (~is_test)
            if tr.sum() < 40 or te.sum() < 3:
                continue
            folds.append((t, int(tr.sum()), int(te.sum())))
            tr_idx = np.sort(np.where(tr)[0])
            cut = int(len(tr_idx) * (1 - EVAL_FRAC))
            fit_idx, ev_idx = tr_idx[:cut], tr_idx[cut:]
            model = fit_model(name, X[fit_idx], y[fit_idx], X[ev_idx], y[ev_idx])
            te_idx = np.where(te)[0]
            p = model.predict_proba(X[te_idx])[:, 1]
            avg_win, avg_loss = ev_filter_stats(df.iloc[tr_idx], data, zcache)
            ev = p * avg_win - (1 - p) * avg_loss
            gate_and_simulate(te_idx, p, ev, int(t))

        # ---- Phase 2: FINAL UNTOUCHED TEST (newest events, never seen above) ----
        tr = label_end < test_start          # label windows end before the test set
        te = is_test
        if tr.sum() >= 40 and te.sum() >= 3:
            tr_idx = np.sort(np.where(tr)[0])
            cut = int(len(tr_idx) * (1 - EVAL_FRAC))
            fit_idx, ev_idx = tr_idx[:cut], tr_idx[cut:]
            model = fit_model(name, X[fit_idx], y[fit_idx], X[ev_idx], y[ev_idx])
            te_idx = np.where(te)[0]
            p = model.predict_proba(X[te_idx])[:, 1]
            avg_win, avg_loss = ev_filter_stats(df.iloc[tr_idx], data, zcache)
            ev = p * avg_win - (1 - p) * avg_loss
            gate_and_simulate(te_idx, p, ev, int(test_start))

    odf = pd.DataFrame(rows)
    odf.to_csv(os.path.join(outdir, "predictions.csv"), index=False)

    taken_all, skipped_all = portfolio(all_trades)
    tdf = pd.DataFrame(taken_all)
    tdf.to_csv(os.path.join(outdir, "trades.csv"), index=False)

    # ---- report: validation vs final test separated ----
    lines = [f"=== {name} — ML WATCH backtest (bias-hardened) ===",
             f"events: {len(df)}   T2 base: {df['t2'].mean():.0%}   symbols: {len(names)}",
             f"split: newest {n_test} events (arm>={test_start}) = FINAL UNTOUCHED TEST; "
             f"rest = walk-forward validation",
             f"look-ahead guard: training requires arm+OBS+10 < fold boundary (no label leakage)",
             (f"gates: every z<-3 event (baseline has no prob/EV gate)"
              if name == "baseline" else
              f"gates: raw prob >= {PROB_MIN}  &  EV > {EV_MIN}  (fixed a priori, not tuned on test)"),
             f"mechanical trade: LONG A/SHORT B, exit z>=0 / stop {0.05:.0%} notional / max {30}d",
             "",
             "--- walk-forward VALIDATION (all events except final test) ---",
             f"  walk-forward folds: {len(folds)}   (events arm<{test_start} only train, "
             f"never validate; validated events below)"]

    v = tdf[~tdf["test"]] if len(tdf) else tdf
    t = tdf[tdf["test"]] if len(tdf) else tdf
    vrows = odf[~odf["test"]] if len(odf) else odf
    trows = odf[odf["test"]] if len(odf) else odf

    for lbl, tt, rr in [("VALIDATION", v, vrows), ("FINAL TEST", t, trows)]:
        if not len(rr):
            lines.append(f"--- {lbl} ---")
            lines.append("  (no events)")
            continue
        lines.append(f"--- {lbl} ---")
        lines.append(f"  events: {len(rr)}   T2 win: {100*rr['t2'].mean():.0f}%   "
                     f"signals(raw>=0.5): {int((rr['prob']>=PROB_MIN).sum())}")
        if len(tt):
            lines.append(f"  trades taken: {len(tt)}   net: Rs {tt['net'].sum():+,.0f}   "
                         f"win%: {100*(tt['net']>0).mean():.0f}%   avg: Rs {tt['net'].mean():+,.0f}")
            lines.append(f"  exits: {dict(tt['reason'].value_counts())}   avg hold: {tt['held'].mean():.0f}d")
            lines.append("  per-pair:")
            per = tt.groupby(["leg", "partner"]).agg(n=("net", "size"), net=("net", "sum"),
                                                     win=("net", lambda s: (s > 0).mean()))
            for (lg, pn), r in per.sort_values("net", ascending=False).iterrows():
                lines.append(f"    {lg:<12}/{pn:<12} n={int(r['n'])}  net=Rs{r['net']:+8,.0f}  win={100*r['win']:.0f}%")
        else:
            lines.append("  trades taken: 0")
        lines.append("")

    lines.append("--- bias controls ---")
    lines.append("  look-ahead: training label windows end before the test period (arm+OBS+10<boundary)")
    lines.append("  overfitting: quarterly walk-forward validation + final untouched test; "
                 "early stopping for trees; thresholds fixed a priori")
    lines.append("  survivorship: all symbols used, no pair dropped for performance "
                 "(caveat: today's large-cap universe; no point-in-time membership data)")

    rep = "\n".join(lines)
    print(rep)
    with open(os.path.join(outdir, "summary.txt"), "w") as f:
        f.write(rep + "\n")

    # ---- plots (only the trades actually TAKEN, i.e. portfolio-filtered) ----
    pair_trades = {}
    for tr in taken_all:
        pair_trades.setdefault((tr["leg"], tr["partner"]), []).append(tr)

    if len(taken_all):
        eq = [CAPITAL]
        for _, tr in tdf.iterrows():
            eq.append(eq[-1] + tr["net"])
        plt.figure(figsize=(11, 5))
        plt.plot(eq, marker="o", color="tab:green")
        plt.axhline(CAPITAL, color="k", ls="--", lw=0.8)
        plt.title(f"{name} equity — {len(taken_all)} trades (net Rs{tdf['net'].sum():+,.0f})")
        plt.ylabel("capital Rs"); plt.xlabel("trade #"); plt.grid(alpha=0.3)
        plt.tight_layout()
        plt.savefig(os.path.join(outdir, "equity.png"), dpi=110)
        plt.close()

    if len(odf) > 15:
        bins = np.linspace(0, 1, 11)
        p = odf["prob"].values; yb = odf["t2"].values
        centers, fracs = [], []
        for i in range(10):
            m = (p > bins[i]) & (p <= bins[i + 1])
            if m.sum() >= 3:
                centers.append((bins[i] + bins[i + 1]) / 2)
                fracs.append(yb[m].mean())
        plt.figure(figsize=(5.5, 5.5))
        plt.plot([0, 1], [0, 1], "k--", lw=1)
        if centers:
            plt.plot(centers, fracs, "o-", color="tab:blue")
        plt.title(f"{name} reliability (raw prob, pooled)")
        plt.xlabel("predicted prob"); plt.ylabel("observed freq"); plt.grid(alpha=0.3)
        plt.tight_layout()
        plt.savefig(os.path.join(outdir, "reliability.png"), dpi=110)
        plt.close()

    for (leg, partner), trs in sorted(pair_trades.items()):
        pa = data[leg]; pb = data[partner]
        z, _ = zcache.get((leg, partner), (np.zeros(len(pa)), None))
        plot_pair(outdir, name, leg, partner, pa, pb, z, trs)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", choices=list(MODELS) + ["all", "baseline"], default="all")
    ap.add_argument("--data", default=None,
                    help="data dir with Date,close CSVs. Default backtesting/data; "
                         "'etf' = ../code/metal_market_data/etf_analysis")
    a = ap.parse_args()

    base = os.path.join(os.path.dirname(os.path.abspath(__file__)))
    out_root = os.path.join(base, "..", "model_backtests")   # outputs live here, away from code
    out_root = os.path.normpath(out_root)

    if a.data is None:
        data_path, tag = "backtesting/data", None
    elif a.data == "etf":
        data_path = ("/home/null/Documents/development/statistical_arbitrage/code/"
                     "metal_market_data/etf_analysis")
        tag = "etf"
    else:
        data_path, tag = a.data, os.path.basename(os.path.normpath(a.data))

    models = (["baseline"] + list(MODELS)) if a.model == "all" else [a.model]
    for m in models:
        run_model(m, os.path.join(out_root, tag or "", m), data_path=data_path)


if __name__ == "__main__":
    main()
