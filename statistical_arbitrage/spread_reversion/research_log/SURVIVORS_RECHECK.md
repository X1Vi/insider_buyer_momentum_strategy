# The three survivors, rechecked

**16 September 2026.** Companion to `CRUDE_CARRY_RECHECK.md`. Four things in
`MASTER_V3.md` were not declared dead. Crude carry was rechecked separately and
re-rated from 0.6%/day to ~6%/yr hedged. This covers the other three.

**Verdict: none clears the project's own bar, but the combined momentum book is
the only thing in thirty-odd attempts that gets close — and unlike everything
else, it is getting better rather than decaying.**

---

## 1. Deflated Sharpe — the test that killed items 20–23, applied to the survivors

Run with the project's own `hip3/dsr.py`, on the project's own saved return
series. DSR answers: given ~30 strategies were tried, how likely is this Sharpe
to be skill rather than the best of thirty draws? **The bar is 0.95.**

| Book | Days | Ann Sharpe | t | DSR@10 | **DSR@30** | DSR@60 |
|---|---:|---:|---:|---:|---:|---:|
| Cross-sectional momentum | 1,401 | 1.00 | 1.95 | 0.642 | **0.447** | 0.342 |
| Factor-residual momentum | 1,220 | 1.04 | 1.91 | 0.641 | **0.445** | 0.341 |
| Combined, as published | 1,220 | 1.57 | 2.87 | 0.911 | **0.803** | 0.719 |
| **Combined, reproducible** | 1,220 | **1.44** | 2.63 | — | **0.710** | 0.611 |

Individually the two books are coin flips: DSR 0.45 means it is about as likely
as not that each is the best of thirty lucky draws. **Combining them is what does
the work** — 0.45 → 0.71–0.80.

For scale, items 20–23 (cross-sectional book, raw momentum, residual momentum,
ADR class) all scored **0.000** on this same test. These are genuinely a
different category. They are just not over the line.

---

## 2. The headline 1.57 is not reproducible from the published legs

`research/statarb/README.md` reports the combination as **"50/50 combined,
Sharpe 1.57"**. Reconstructing it from `momentum_daily.csv` and
`resid_momentum_daily.csv`:

| Construction | Sharpe | Matches the file? |
|---|---:|---|
| Literal 50/50 | **1.44** | no, max abs error 4.1e-02 |
| Inverse-vol, full sample (w=0.385) | 1.48 | no, 3.6e-02 |
| Inverse-vol, trailing 60d, lagged | 1.44 | — |
| Best-fit constant weight (w=0.16) | — | no, 2.5e-02 |
| **`combined_daily.csv` as shipped** | **1.57** | — |

**No constant weighting of the two published series reproduces it.** The most
likely benign explanation is that the combined book was built from the
underlying *positions* rather than by blending the two return streams, which
legitimately differs because offsetting positions net out and save cost. That
would be a better construction, not a worse one — but it is not what "50/50
combined" describes, and it cannot be checked from what is saved.

**Use 1.44 (DSR 0.710) as the honest figure** until the 1.57 can be regenerated.

Leg vols are also not equal — momentum 23.0%/yr against residual 14.4%/yr — so
"50/50" is ambiguous between capital and risk. Inverse-vol trailing and literal
50/50 happen to land on the same 1.44.

---

## 3. The diversification is real

| | |
|---|---:|
| Correlation, matched on date, 1,220 common days | **+0.002** |
| README claim | −0.044 |

Close enough; both are zero. This is the one structural claim in the statarb work
that fully holds up, and it is the reason the combination lifts DSR from 0.45 to
0.71.

*Method note, because I got this wrong first:* aligning the two series by array
position rather than by date gives **+0.284**. The two files start on different
dates (2022-10-31 vs 2023-04-29), so position-alignment silently compares
different days. The date-matched +0.002 is the correct figure.

---

## 4. It is improving, not decaying — which is unusual here

| Year | Momentum | Residual | Combined |
|---|---:|---:|---:|
| 2023 | 1.05 | 1.06 | 1.40 |
| 2024 | 0.10 | 0.04 | 0.80 |
| 2025 | 1.66 | 1.63 | **2.39** |
| 2026 (to 30 Aug) | 1.33 | 1.88 | **1.87** |

| | Sharpe |
|---|---:|
| First half (2023-04 → 2024-12) | 1.01 |
| **Second half (2024-12 → 2026-08)** | **2.15** |
| Last 6 months | 2.04 |
| Last 3 months | 2.35 |

Every other result in this project decayed when pushed forward — the India/Taiwan
ADR trade went from +135.8bp to −3.0bp, the SK Hynix line read across to −21.7bp.
This one does the opposite. That does not prove it is real (a strong recent run is
also what a lucky draw looks like) but it is the only survivor whose out-of-sample
period is its *best* period.

---

## 5. The paper trading is not running

`MASTER_V3.md` records item 1 as *"paper-traded since 1 Sep."* It is not.

```
paper/paper_log.csv   —  1 data row, dated 2026-09-01
paper/paper_state.json —  last written 1 Sep 08:49
```

**One day. It has not run in fifteen.** `paper/PAPER_TRADING.md` states clearly
and correctly that the purpose is *not* to find out whether the strategy makes
money — the error bar makes that impossible in a quarter — but to answer four
things a backtest cannot:

1. does the live signal reproduce the backtested one
2. what fills actually cost (day one came back at **0.00bp median** slippage)
3. does it survive delistings, timeouts, sub-minimum positions
4. what capacity looks like

**None of those four have been answered**, because the harness ran once. That
single day did produce one useful datapoint — 0.00bp median slippage on an $11
order, against a 5bp assumption — which is exactly the kind of thing only live
running can establish, and exactly why it should be running.

---

## What follows

**Restart the paper harness.** It is the cheapest unresolved item in the project
and it feeds the two things that actually matter: whether the live signal matches
the backtest, and what fills really cost. The second of those is the same
question as the maker/taker item, which the log already calls the highest-value
open problem.

**Do not quote 1.57.** Quote 1.44 with DSR 0.710, or regenerate the combined book
from positions and publish the code that does it.

**What would push it over 0.95.** At the current Sharpe and t = 2.63, reaching
DSR 0.95 against 30 trials needs roughly a t of 3.3–3.5 — about two more years of
data at this rate, or genuinely out-of-sample evidence from live running. There
is no analysis of the existing panel that gets there; the sample is the
constraint.

**What would kill it.** The factor-residual leg's parameter surface is spiky, not
a plateau: factor counts give 0.74, 0.50, 0.62, 0.59, **1.04**, 0.36, 0.29,
−0.06, **1.30** (median 0.59), and the residual window flips 60d→1.04 into
90d→−0.08. If the honest median 0.59 is used for that leg instead of the best
cell, the combination falls toward ~1.2, and DSR with it. That substitution has
not been run and should be.
