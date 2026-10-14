# Insider-purchase drift — data, method, and stress test

**2026-10-13.** How the insider event study was built, the exact code, and the traps
it was stress-tested against. Companion to `PLAN.md`. **Status: promising but NOT
established.** Everything here is research; not investment advice.

---

## 0. TL;DR — the honest number

Naively, buying the insider-bought stock at the next open after a disclosure and
holding 20–60 days shows a big excess return vs the Nifty. But the stress tests gut
most of it:

| Battery | +20d | +60d |
|---|---:|---:|
| Raw excess vs Nifty (next-day open) | **+2.24%** | **+6.61%** |
| Placebo (random dates, same stocks) | +0.99% | +3.79% |
| **Placebo-adjusted effect** | **≈ +1.25%** | **≈ +2.82%** |
| Cluster-robust mean (per symbol, n=167) | +3.46% (t=3.6) | +5.61% (t=3.6) |
| Excess vs Nifty **Midcap 150** | +1.75% | +4.61% |

**Read:** there is a real positive drift, but **more than half of the headline number
is a size/survivorship drift** (the placebo is strongly positive), the naive t≈13
collapses to **t≈3.6** once you count symbols instead of events, and the effect is
**negative in 2018, 2019 and 2025**. It is not yet a fundable edge.

---

## 1. How the data was obtained

### Source
NSE **corporate-filings PIT (insider) API** — free, no auth.

```
GET https://www.nseindia.com/api/corporates-pit
    ?index=equities&from_date=DD-MM-YYYY&to_date=DD-MM-YYYY&symbol=
Headers: browser User-Agent, Accept: application/json,
         Referer: https://www.nseindia.com/companies-listing/corporate-filings-insider-trading
```

The NSE **homepage returns 403** to this client, but the API returns 200 anyway — no
cookie jar needed. See `data/2026-10-13/DATA_SOURCES.md`.

### Measured rate limits (2026-10-13)
- 8 back-to-back calls → all HTTP 200, ~1.3–1.7 s each, **no throttle**.
- One call per year works (no server-side cap): 2025 = 13,545 rows (~11 MB), 2024 =
  17,332. Paging by year is enough.

### What was scraped
`insider_drift.py --fetch` pulls 2015–2026, one JSON per year into `data/raw/`:

```
2015 3,729 · 2016 45,609 · 2017 56,841 · 2018 58,542 · 2019 38,371 · 2020 30,667
2021 34,325 · 2022 19,280 · 2023 18,822 · 2024 17,332 · 2025 13,545 · 2026 4,451
```

### Cleaning (`insider_drift.py --clean`)
- Parse `acqfromDt`/`acqtoDt`/`intimDt` (`%d-%b-%Y`) and `date` (`%d-%b-%Y %H:%M`).
- Numeric-cast quantities/values; keep **Equity Shares** only.
- `is_buy = (side == "Buy") & (acqMode == "Market Purchase")`.
- Dedupe on (symbol, name, trade_date, mode, qty, value).
- **Source-bug fix:** 8 rows had century typos (trade date `22-Jul-1922` for 2022);
  where the trade date is implausible the disclosure date is used instead.

Result: **331,244 disclosures, 2,414 symbols; 42,553 market-purchase equity events
across 1,601 symbols.**

```python
# insider_drift.py — the date-bug fix
plausible = df["trade_date"].between("2015-01-01",
                                     pd.Timestamp.today() + pd.Timedelta(1, unit="D"))
df.loc[~plausible, "trade_date"] = df.loc[~plausible, "disclose_ts"].dt.normalize()
```

### Prices
`stress_insider.py --fetch` pulls adjusted daily OHLC via yfinance into
`data/panel/` (batch download, cached). Benchmark = `^NSEI` (and `^NSEMDCP50`).
**Delisted names are missing from yfinance** → survivorship caveat (§4).

---

## 2. The event-study method

For each market-purchase event:
- **Entry:** the disclosure day's close (`close`) or the **next trading day's open**
  (`next_open`, the tradeable assumption).
- **Exit:** close at entry + 1/5/20/60 trading days.
- **Return:** `close[exit]/entry − 1`, then **subtract the benchmark** return over the
  same calendar window (market-adjusted / "excess" CAR).

```python
# stress_insider.py — the core, numpy for speed
def _excess(px, bd, bv, d, h, timing):
    dates = px["dates"]
    pos = np.searchsorted(dates, np.datetime64(d))
    if pos >= len(dates): return np.nan
    if timing == "next_open":
        if pos + 1 >= len(dates): return np.nan
        ei, entry = pos + 1, px["open"][pos + 1]
    else:
        ei, entry = pos, px["close"][pos]
    xi = ei + h
    if xi >= len(dates) or not np.isfinite(entry) or entry <= 0: return np.nan
    r = px["close"][xi] / entry - 1.0
    d0, d1 = dates[ei], dates[xi]
    j0, j1 = np.searchsorted(bd, d0), np.searchsorted(bd, d1)
    if j0 >= len(bd) or j1 >= len(bd) or bd[j0] != d0 or bd[j1] != d1: return np.nan
    return r - (bv[j1] / bv[j0] - 1.0)
```

**Sample:** random 200 of the 1,601 symbols (seed 42), to avoid the top-frequency
selection of the first look → 167 had price data → **4,485 events**.

---

## 3. Stress batteries and results

`stress_insider.py --n 200 --placebo 100`

| # | Battery | Result |
|---|---|---|
| B1 | From disclosure **close** | +0.34 / +1.07 / +2.60 / +6.89 % (1/5/20/60d) |
| B2 | **Next-day open** (tradeable) | +0.18 / +0.74 / +2.24 / +6.61 % |
| B3 | **Placebo** (random dates) | mean −0.21 / +0.01 / **+0.99 / +3.79 %**; p=0.000 (5/20/60d) |
| B4 | **Subperiod** (+20d) | 2018 **−2.0%**, 2019 **−0.4%**, 2025 **−1.8%**; 2017 +4.7, 2021 +7.2, 2023 +8.4 |
| B5 | Only buys ≥ ₹10 L | +0.20 / +0.60 / +2.02 / +5.15 % |
| B6 | **Clustered** (≤5d collapsed) | +0.32 / +1.05 / +3.11 / +6.05 % |
| B7 | Net of cost (next open) | 20d: gross 2.24 → net@27bp 1.97 → net@75bp 1.49; 60d: 6.61 → 6.34 → 5.86 |
| B8 | **Top-frequency names** | **−0.23%** (+20d) — the "hot" names don't work |
| B9 | **Cluster-robust t** (per symbol, n=167) | 20d +3.46% **t=3.58**; 60d +5.61% **t=3.57** |
| B10 | Vs **Nifty Midcap 150** | +0.10 / +0.63 / +1.75 / +4.61 % |

### Placebo code
```python
def placebo(events, panel, bd, bv, timing, B=100, seed=42):
    rng = np.random.default_rng(seed)
    obs = {h: cars(events, panel, bd, bv, timing, (h,))[h].mean() for h in HORIZONS}
    null = {h: [] for h in HORIZONS}
    for _ in range(B):
        fake_d = np.empty(len(events), dtype="datetime64[ns]")
        for i, sym in enumerate(events["symbol"].to_numpy()):
            px = panel.get(sym)
            fake_d[i] = px["dates"][rng.integers(0, len(px["dates"]) - MAXH - 1)]
        fake = pd.DataFrame({"symbol": events["symbol"], "d": fake_d}).dropna()
        c = cars(fake, panel, bd, bv, timing, HORIZONS)
        for h in HORIZONS: null[h].append(c[h].mean())
    return {h: dict(obs=obs[h], p=(np.abs(null[h]) >= abs(obs[h])).mean(),
                    mean_null=np.mean(null[h])) for h in HORIZONS}
```

### Cluster-robust code
```python
def cluster_t(events, panel, bd, bv, timing, h):
    pe = per_event_cars(events, panel, bd, bv, timing, h)   # symbol, car
    g = pe.groupby("symbol")["car"].mean()                  # one obs per symbol
    se = g.std(ddof=1) / np.sqrt(len(g))
    return len(pe), len(g), g.mean(), se, g.mean() / se
```

---

## 4. What the stress tests reveal

1. **Half the headline is not the signal.** The placebo mean is **+3.79% at 60d** — the
   same stocks at random dates already beat the Nifty by that much (small/mid-cap
   premium + survivorship). The event adds only ~+1.25% (20d) / ~+2.82% (60d) on top.
2. **Significance was overstated ~4×.** Counting events (4,485) gives t≈13; counting
   **symbols** (167) gives **t≈3.6**. Events within a symbol are not independent
   (repo trap: overlapping events counted independently).
3. **It is a size bet, partly.** Against Nifty 50 the 20d excess is +2.24%; against
   Nifty **Midcap 150** it is +1.75%. Some of the "edge" is just small-cap vs large-cap.
4. **Unstable across time.** Negative in 2018, 2019 and 2025; the 2015 cell (+44.8%,
   n=19) is an outlier, not signal.
5. **Selection flips the answer.** The most-frequently-bought names are **negative**
   (−0.23% at 20d). The first look (top-6 names) looked positive precisely because of
   that selection.
6. **Cost:** at ₹8–16k the round trip is ~0.6–0.75%, not 27 bp. The 20-day
   placebo-adjusted edge (~1.25% gross) leaves ~0.5–0.65% net — thin; the 60-day
   (~2.8% gross) leaves ~2.1–2.2%.

---

## 5. Caveats / what is NOT established

- **Survivorship:** the panel is symbols yfinance still has (167/200); insider buys in
  names that later died are excluded → biases returns **up**.
- **Disclosure-date semantics:** the NSE `date` field is *assumed* to be the
  dissemination time; unverified. If it lags, entry timing shifts.
- **Benchmark:** `^NSEI`/`^NSEMDCP50` are proxies; a true size-matched basket is better.
- **Cost & spread:** modelled, not measured; small caps' spread is the likely killer.
- **Overlap across years** within a symbol is only partly handled (B6/B9).
- Not investment advice.

---

## 6. Reproduce

```bash
# 1. scrape + clean the insider disclosures (free, no auth)
python strategy_categories/could_work/india_insider_drift/insider_drift.py --fetch
python strategy_categories/could_work/india_insider_drift/insider_drift.py --clean --summary

# 2. stress-test the event study (needs a venv with yfinance)
python strategy_categories/could_work/india_insider_drift/stress_insider.py --fetch --n 200 --placebo 100
```

| File | Role |
|---|---|
| `insider_drift.py` | fetch / clean / summary / plot / forward-return |
| `stress_insider.py` | the stress batteries (this report) |
| `data/raw/pit_YYYY.json` | raw NSE PIT disclosures |
| `data/events.csv` | cleaned events (331k rows) |
| `data/panel/*.csv` | price panel for the stress sample |
| `data/stress_results.json` | machine-readable stress output |
| `plots/*.png` | price charts with insider-buy markers |

---

## 7. Verdict and next step

**Keep, but on probation.** The effect is real-ish and survives clustering and a
midcap benchmark, but it is small, unstable across years, partly a size/survivorship
drift, and thin after realistic cost at ₹8–16k.

To promote it, the next test must: (a) use a **point-in-time, survivorship-aware**
universe (include delisted names); (b) use a **size-matched benchmark**; (c) measure
the real spread; and (d) pre-register one cell and run a walk-forward OOS. If it
still clears cost, it becomes a paper-trade candidate — otherwise it goes to the
graveyard as a tested-and-dead result.

*Research only; not investment advice.*
