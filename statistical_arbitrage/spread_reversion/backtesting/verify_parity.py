#!/usr/bin/env python3
"""Verify the DEPLOYED model files reproduce the trained model's probabilities.

Checks the WATCH scanner's probability against the authoritative reference
(model_check.json, written by train_export.py from the same training run as
model_dump.txt) using the EXACT code path the live scanner runs
(reaction/scanner.py: rolling z -> 23 features -> float32 tree walk).

Passes when every reference row agrees within PARITY_TOL (0.005).

Run:
  .venv/bin/python backtesting/verify_parity.py
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from reaction import scanner as S  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
CHECK_PATH = os.path.join(HERE, "model_check.json")
PARITY_TOL = 0.005

import json  # noqa: E402

ref = json.load(open(CHECK_PATH))
trees = S.parse_model(os.path.join(HERE, "model_dump.txt"))
assert len(trees) == 300, "expected 300 trees in model_dump.txt"

worst = 0.0
fails = []
for row in ref["rows"]:
    leg, partner, arm = row["leg"], row["partner"], row["arm_i"]
    pa = pd.read_csv(os.path.join(DATA, f"{leg}.csv"))["close"].values
    pb = pd.read_csv(os.path.join(DATA, f"{partner}.csv"))["close"].values
    n = min(len(pa), len(pb))
    pa, pb = pa[:n], pb[:n]
    z, beta = S.rbz(pa, pb)
    sc = S.scan(pa, pb, z, beta, trees, ref["leg_ids"][leg], arm + S.OBS + 1)
    d = abs(sc["prob"] - row["prob"])
    worst = max(worst, d)
    status = "OK" if d <= PARITY_TOL else "FAIL"
    if d > PARITY_TOL:
        fails.append((leg, d))
    print(f"  {leg:10}/{partner:<10} arm={sc['arm']} ref={row['prob']:.4f} "
          f"scan={sc['prob']:.4f} diff={d:.4f} {status}")

print(f"parity: worst diff={worst:.4f}  tol={PARITY_TOL}  -> "
      f"{'PASS' if not fails else 'FAIL'}")
sys.exit(1 if fails else 0)
