#!/usr/bin/env python3
"""Shared pipeline for the three-model WATCH backtest (borrowed from
export_model.py, oos_walkforward.py and backtest_one_side.py).

Pipeline (as speced):
    PAIR DATA -> detect z < -3 -> create event -> event features
        -> {XGBoost | LightGBM | Logistic} -> probability
        -> calibration (Platt sigmoid) -> expected-value filter
        -> trading signal -> mechanical entry+exit -> walk-forward backtest

Nothing here writes to the repo outside its own output directory.
"""
import glob
import numpy as np
import pandas as pd

W_BETA, W_Z, Z_ARM, OBS = 252, 60, -3.0, 10
GATE_ZREC, GATE_PX = 0.5, 0.02
QUARTER, Q0 = 63, 3 * 63          # walk-forward: quarterly folds, 3 qtr warmup

# mechanical trade params (one position at a time, LONG A / SHORT B)
CAPITAL, MAX_HOLD = 20000.0, 30
STOP_NOTIONAL_PCT = 0.05          # stop-loss = 5% of entry notional (was fixed Rs 400)
PROB_MIN = 0.5                    # WATCH probability floor (raw model prob, as in prev backtest)
EV_MIN = 0.0                      # expected-value filter floor (rupees)

FEATURES = ["z_arm", "z_now", "z_min", "z_rec", "z_rec_speed", "days_zmin",
            "zslope_win", "zslope_short", "px_dist_low", "px_ret_arm",
            "ret_last2", "ret_last3", "ret_last5", "days_pxlow", "div",
            "z_slope_after_min", "px_slope_after_min", "div_strength",
            "drop_depth", "vol_ratio", "svol20", "beta", "leg_id"]

# Indian cash-market fee model (copied from backtest_one_side.py)
BROKERAGE_FLAT, BROKERAGE_PCT, BROKERAGE_MIN = 20.0, 0.001, 5.0
STT_PCT, STAMP_PCT, EXCH_PCT = 0.00025, 0.00003, 0.0000297
SEBI_PCT, IPFT_PCT, GST_PCT = 0.000001, 0.000001, 0.18


def load_data(path="backtesting/data"):
    files = sorted(glob.glob(f"{path}/*.csv"))
    names = [f.split("/")[-1][:-4] for f in files]
    data = {nm: pd.read_csv(f)["close"].values for nm, f in zip(names, files)}
    return names, data


def rbz(pa, pb):
    """Rolling hedge-ratio regression + z-score of the spread (from export_model.py)."""
    sla, slb = pd.Series(np.log(pa)), pd.Series(np.log(pb))
    beta = (sla.rolling(W_BETA).cov(slb) / slb.rolling(W_BETA).var()).values
    alpha = (sla.rolling(W_BETA).mean() - pd.Series(beta) * slb.rolling(W_BETA).mean()).values
    spread = (sla - pd.Series(beta) * slb - pd.Series(alpha)).values
    mu = pd.Series(spread).rolling(W_Z).mean().values
    sd = pd.Series(spread).rolling(W_Z).std().values
    z = np.where(sd > 1e-9, (spread - mu) / np.maximum(sd, 1e-9), 0.0)
    z[:W_BETA + W_Z] = 0.0
    return z, beta


def t2_target(pa, e):
    """T2 target: +2% hit before -2% within 10 bars after obs-end (from oos_walkforward)."""
    entry = pa[e]
    for k in range(1, 11):
        if e + k >= len(pa):
            return 0
        c = pa[e + k]
        if c >= entry * 1.02:
            return 1
        if c <= entry * 0.98:
            return 0
    return 0


def build_events(names, data):
    """Detect z < -3, create events, compute the 23 features + T2 label.

    Same logic as export_model.build() (all pair combos, dedup by (leg, arm)
    keeping the lowest z_arm). Returns a DataFrame plus the per-pair z/beta
    cache needed for the mechanical trade simulation.
    """
    zcache = {}
    events = []
    for a in range(len(names)):
        for b in range(a + 1, len(names)):
            A, B = names[a], names[b]
            pa, pb = data[A], data[B]
            n = min(len(pa), len(pb))
            if n < W_BETA + W_Z + OBS + 30:
                continue
            pa, pb = pa[:n], pb[:n]
            z, beta = rbz(pa, pb)
            zcache[(A, B)] = (z, beta)
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
                        events.append((A, B, i, feats, t2_target(pa, e), z[i]))
                    i += 5
                i += 1

    best = {}
    for ev in events:
        key = (ev[0], ev[2])
        if key not in best or ev[5] < best[key][5]:
            best[key] = ev
    rows = list(best.values())
    df = pd.DataFrame([r[3] for r in rows], columns=FEATURES)
    df["leg"] = [r[0] for r in rows]
    df["partner"] = [r[1] for r in rows]
    df["arm"] = [r[2] for r in rows]
    df["t2"] = [r[4] for r in rows]
    return df, zcache, names, data


def leg_fees(p, q, side):
    v = p * q
    brk = max(min(BROKERAGE_FLAT, BROKERAGE_PCT * v), BROKERAGE_MIN)
    stt = v * STT_PCT if side == "SELL" else 0.0
    stp = v * STAMP_PCT if side == "BUY" else 0.0
    e = v * EXCH_PCT; s = v * SEBI_PCT; i = v * IPFT_PCT
    return brk + stt + stp + e + s + i + GST_PCT * (brk + e + s + i)


def simulate_trade(pa, pb, z, entry_idx):
    """Mechanical LONG A / SHORT B entered at obs-end `entry_idx`.

    Exit when the spread z crosses 0 (mean reversion complete), or a stop-loss
    of STOP_NOTIONAL_PCT of entry notional is hit, or MAX_HOLD bars elapse.
    Returns a dict or None.
    """
    if entry_idx + 1 >= len(pa) or entry_idx + MAX_HOLD >= len(pa):
        return None
    q = max(int(CAPITAL / (pa[entry_idx] + pb[entry_idx])), 1)
    epa, epb = pa[entry_idx], pb[entry_idx]
    stop_gross = -STOP_NOTIONAL_PCT * (epa + epb) * q

    exit_idx, reason = None, None
    for k in range(1, MAX_HOLD + 1):
        idx = entry_idx + k
        g = (pa[idx] - epa) * q - (pb[idx] - epb) * q
        if g <= stop_gross:
            exit_idx, reason = idx, "STOP"
            break
        if z[idx] >= 0.0:
            exit_idx, reason = idx, "ZERO"
            break
    if exit_idx is None:
        exit_idx, reason = entry_idx + MAX_HOLD, "TIME"

    pa_x, pb_x = pa[exit_idx], pb[exit_idx]
    gross = (pa_x - epa) * q - (pb_x - epb) * q
    fees = (leg_fees(epa, q, "BUY") + leg_fees(epb, q, "SELL")
            + leg_fees(pa_x, q, "SELL") + leg_fees(pb_x, q, "BUY"))
    return {"q": q, "entry": int(entry_idx), "exit": int(exit_idx), "held": exit_idx - entry_idx,
            "gross": gross, "fees": fees, "net": gross - fees, "reason": reason}


def train_ev_stats(tr_df, data, zcache):
    """Avg win / avg loss (net rupees) of mechanically simulated training trades.

    Used by the expected-value filter: EV(p) = p*avg_win - (1-p)*avg_loss.
    """
    nets = []
    for _, r in tr_df.iterrows():
        pa = data[r["leg"]]; pb = data[r["partner"]]
        z, _ = zcache.get((r["leg"], r["partner"]), (None, None))
        if z is None:
            continue
        t = simulate_trade(pa, pb, z, int(r["arm"]) + OBS)
        if t:
            nets.append(t["net"])
    nets = np.array(nets)
    if len(nets) == 0:
        return 0.0, 1.0
    wins = nets[nets > 0]; losses = -nets[nets <= 0]
    avg_win = wins.mean() if len(wins) else 0.0
    avg_loss = losses.mean() if len(losses) else 0.0
    return avg_win, avg_loss
