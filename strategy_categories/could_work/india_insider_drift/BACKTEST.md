# BACKTEST — major-insider RSI-dip signal (India)

**2026-10-13.** Full backtest of the de-noised signal from the plots. Code:
`backtest_insider.py`. Data: `data/events.csv` (NSE PIT, 2015–2026) +
`data/bt_prices/*.csv` (yfinance, from 2010). **Verdict: no timing edge — the
signal does not beat random entry into the same stocks.** Research only.

---

## 1. Signal and execution

- **Signal:** a MAJOR insider (promoter / promoter-group / director / KMP)
  market-**buys ≥ ₹25 lakh**, **and RSI(14) < 40**.
- **Entry:** next trading day's **open** after the disclosure date (point-in-time).
- **Exit:** close after **HOLD** days (tested 5 / 20 / 60).
- **Long-only, no leverage** (cash). Cost **0.75%** round trip (₹8–16k delivery).
- Shorts are not executable in Indian cash overnight, so they are excluded.

**Selection criterion** (instead of "volatile"): money ≈ (signals/year) × (edge per
signal), so rank names by risk-adjusted return of the signal book with enough
trades — then confirm out-of-sample. Volatility alone gives trades, not money.

## 2. Basket (hand-picked: signal-rich + recent activity + tradable)

`DBCORP, STEL, MAHSEAMLES, JINDALSTEL, USHAMART, JSL, SURYAROSNI, NRBBEARING, NCC,
MANINFRA, APLLTD, MANGLMCEM, SHOPERSTOP, GREENPLY, PAISALO, JINDRILL, KRISHANA,
TFCILTD` (18 names). Chosen because they have ≥12 major size buys and ≥2 in 2024+,
so the out-of-sample window is not empty.

---

## 3. Results

### Pooled portfolio (equal sleeve per symbol)

| hold | trades | win | avg net/trade | CAGR | vol | **Sharpe** | maxDD | **Calmar** |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 5d | 237 | 0.43 | −1.69% | −0.82% | 1.9% | **−0.42** | −16.6% | −0.05 |
| 20d | 237 | 0.53 | +0.99% | −0.19% | 3.3% | **−0.04** | −15.4% | −0.01 |
| 60d | 237 | 0.52 | +5.38% | +0.52% | 5.0% | **+0.13** | −15.8% | +0.03 |

### Per symbol (hold 20) — best and worst

| symbol | n | win | avg net | Sharpe | maxDD | Calmar |
|---|--:|--:|--:|--:|--:|--:|
| KRISHANA | 15 | 0.47 | +4.3% | +0.39 | −14.9% | 0.26 |
| SURYAROSNI | 17 | 0.65 | +4.9% | +0.32 | −22.7% | 0.10 |
| APLLTD | 11 | 0.82 | +10.0% | +0.29 | −13.1% | 0.15 |
| … | | | | | | |
| NCC | 25 | 0.64 | +4.2% | −0.32 | −63.4% | −0.08 |
| SHOPERSTOP | 17 | 0.12 | −5.4% | −0.21 | −31.1% | −0.05 |
| PAISALO | 16 | 0.25 | −6.2% | −0.20 | −41.1% | −0.05 |

Highly inconsistent: some names positive, many negative. Nothing survives as a
group.

### Out-of-sample (entries ≥ 2024-01-01)

| hold | trades | win | avg net | median |
|--:|--:|--:|--:|--:|
| 5d | 111 | 0.43 | −0.41% | −0.61% |
| 20d | 111 | 0.59 | +1.37% | +2.27% |
| 60d | 111 | 0.51 | +3.73% | +0.64% |

Positive at 20/60d — but see the placebo: that is the stocks' own drift, not the
signal.

### Monte Carlo + placebo (the decisive test)

- **Block-bootstrap Sharpe** (hold 20): p05 −0.47, p50 −0.01, p95 +0.44;
  **P(Sharpe ≤ 0) = 0.51** — a coin flip.
- **Random-entry placebo** (same stocks, same number of trades, random dates):
  - hold 20: placebo mean Sharpe **+0.26** vs observed **−0.04**;
    **P(placebo ≥ observed) = 0.93**.
  - hold 60: placebo mean **+0.57** vs observed **+0.13**;
    **P(placebo ≥ observed) = 0.985**.

**Random entries into the same stocks beat the insider signal 93–98% of the time.**

---

## 4. What this means

1. **No timing edge.** The signal's portfolio Sharpe is ≈ 0, and it is *worse* than
   buying the same names on random dates. The stocks drift up (small-cap /
   survivorship), and *any* long hold captures that — the insider+RSI timing does
   not improve it; it slightly hurts.
2. **Longer holds only capture the drift, not the signal.** The 60d "improvement"
   (+5.38%/trade) is exactly what random 60d holds also earn.
3. **Consistent with the earlier stress test** (`REPORT.md`): after removing the
   size/survivorship drift, the insider effect is ≈ 0.
4. **Answer to "pick volatile names for many trades":** volatility gives trades,
   but here it gives *noise*, not money. The criterion that matters — expected edge
   per signal — is ≈ 0 across the basket.

## 5. Caveats

- Costs modelled (0.75%), spread unmeasured; small caps' spread would make it worse.
- Survivorship (yfinance universe) flatters the long side; the signal still lost.
- Multiple baskets/holds were tried — treat any single positive cell as noise.
- Not investment advice.

## 6. Verdict

**Kill it.** The major-insider RSI-dip long signal does not beat random entry into
the same stocks after cost. Recommend recording it as a tested-and-dead result and
not extending the approach.

## 7. Reproduce

```bash
python backtest_insider.py --fetch \
  --symbols "DBCORP,STEL,MAHSEAMLES,JINDALSTEL,USHAMART,JSL,SURYAROSNI,NRBBEARING,NCC,MANINFRA,APLLTD,MANGLMCEM,SHOPERSTOP,GREENPLY,PAISALO,JINDRILL,KRISHANA,TFCILTD" \
  --min-value 2500000 --rsi-dip 40 --hold 20 --cost 0.0075
```

*Research only; not investment advice.*
