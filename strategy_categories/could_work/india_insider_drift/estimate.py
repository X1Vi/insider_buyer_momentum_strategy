#!/usr/bin/env python3
"""estimate.py — what would ~Rs 8,000 do in this strategy?

Simulates a single small account that:
  - trades the best variant (major insider buy, RSI dip, above 200-DMA, hold 20d),
  - takes ONE position at a time (deploys the whole balance),
  - only buys stocks affordable at the balance (>=1 whole share),
  - pays 0.75% round-trip cost (already in `net`).

Reports the equity path and a bootstrap of a typical YEAR (5th/50th/95th pct).
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from backtest_insider import load_events, load_px, signals, backtest  # noqa: E402

SYMS = ("DBCORP,STEL,MAHSEAMLES,JINDALSTEL,USHAMART,JSL,SURYAROSNI,NRBBEARING,NCC,"
        "MANINFRA,APLLTD,MANGLMCEM,SHOPERSTOP,GREENPLY,PAISALO,JINDRILL,KRISHANA,"
        "TFCILTD").split(",")
START, HOLD, COST = 8000.0, 20, 0.0075

ev = load_events(2.5e6)
trs = []
for s in SYMS:
    px = load_px(s)
    if px is None:
        continue
    sig = signals(ev[ev["symbol"] == s], px, 40)
    if sig.empty:
        continue
    _, tr, _ = backtest(px, sig, HOLD, COST, "dip", 40, 200)
    if tr.empty:
        continue
    tr = tr.copy(); tr["symbol"] = s
    tr["entry_px"] = px["open"].reindex(tr["entry_date"]).to_numpy()
    trs.append(tr)
tr = pd.concat(trs).sort_values("entry_date").reset_index(drop=True)
print(f"all variant trades: {len(tr)}")
aff = tr[tr["entry_px"] <= START]
print(f"affordable at Rs {START:,.0f} (<=1 whole share): {len(aff)}")

# --- single-account sequential simulation (one position at a time) ---
cap, cur_exit, taken, path = START, None, [], []
for _, t in aff.iterrows():
    if cur_exit is None or t["entry_date"] >= cur_exit:
        cap *= (1 + t["net"])
        taken.append(t["net"])
        cur_exit = t["exit_date"]
        path.append((t["exit_date"], cap))
taken = np.asarray(taken)
yrs = (aff["exit_date"].max() - aff["entry_date"].min()).days / 365.25
print(f"\n=== single Rs {START:,.0f} account, one position at a time ===")
print(f"trades taken: {len(taken)} over {yrs:.1f} years ({len(taken)/yrs:.1f}/yr)")
print(f"win rate {np.mean(taken>0):.2f}  avg net/trade {np.mean(taken)*100:.2f}%  "
      f"median {np.median(taken)*100:.2f}%")
print(f"final balance Rs {cap:,.0f}  (start Rs {START:,.0f})  "
      f"total {100*(cap/START-1):.1f}%  CAGR {100*((cap/START)**(1/yrs)-1):.2f}%")
eq = np.array([START] + [c for _, c in path])
dd = (eq / np.maximum.accumulate(eq) - 1).min()
print(f"max drawdown {dd*100:.1f}%")

# --- bootstrap a typical year (~5 trades) ---
rng = np.random.default_rng(7)
per_year = max(1, round(len(taken) / yrs))
sims = np.array([np.prod(1 + rng.choice(taken, size=per_year, replace=True)) - 1
                 for _ in range(5000)])
print(f"\n=== a typical YEAR (~{per_year} trades) on Rs {START:,.0f} ===")
for p in (5, 25, 50, 75, 95):
    v = np.percentile(sims, p)
    print(f"  p{p:>2}: {v*100:6.1f}%  -> Rs {START*(1+v):,.0f}")
print(f"  P(lose money in a year) = {np.mean(sims<0):.2f}")

# --- comparison: buy & hold the basket ---
print("\n=== for reference ===")
print(f"  avg net per trade (all {len(tr)} trades): {tr['net'].mean()*100:.2f}%")
print(f"  if you took EVERY trade at full size (impossible, overlapping): "
      f"{100*(np.prod(1+tr['net'])-1):,.0f}% total")
