#!/usr/bin/env python3
"""Fetch data for the two-stage Ross-style momentum screener.

Caches (into backtesting/ross_data/):
  {SYM}_1d.csv   daily   ts,open,high,low,close,volume
  {SYM}_15m.csv  intraday ts,open,high,low,close,volume  (recent days)
  fundamentals.csv        symbol,float_shares,market_cap

Two stages are fetched separately so you only pull the hot sector's stocks:
  fetch_data.py              -> sector ETFs only (Stage 1, cheap)
  fetch_data.py BANK         -> that sector's constituent stocks (Stage 2)
The Rust screener (src/bin/screener.rs) reads these and does the ranking.

Run:
  .venv/bin/python backtesting/ross/fetch_data.py [SECTOR]
"""
import os
import sys

import pandas as pd
import yfinance as yf

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "ross_data")
os.makedirs(os.path.join(DATA, "etf"), exist_ok=True)
os.makedirs(os.path.join(DATA, "stock"), exist_ok=True)

# sector -> (sector ETF ticker, constituent .NS symbols)
SECTORS = {
    "BANK":   ("BANKBEES.NS",   ["HDFCBANK.NS", "ICICIBANK.NS", "KOTAKBANK.NS", "SBIN.NS", "AXISBANK.NS", "INDUSINDBK.NS"]),
    "IT":     ("ITBEES.NS",     ["TCS.NS", "INFY.NS", "WIPRO.NS", "HCLTECH.NS", "TECHM.NS", "LTIM.NS"]),
    "PHARMA": ("PHARMABEES.NS", ["SUNPHARMA.NS", "CIPLA.NS", "DRREDDY.NS", "DIVISLAB.NS", "LUPIN.NS", "AUROPHARMA.NS"]),
    "AUTO":   ("AUTOBEES.NS",   ["MARUTI.NS", "TATAMOTORS.NS", "M&M.NS", "BAJAJ-AUTO.NS", "EICHERMOT.NS", "TVSMOTOR.NS"]),
    "FMCG":   ("CONSUMBEES.NS", ["ITC.NS", "HINDUNILVR.NS", "NESTLEIND.NS", "BRITANNIA.NS", "DABUR.NS", "MARICO.NS"]),
}


def write(sym, df, folder):
    if df is None or df.empty:
        print(f"  {sym}: EMPTY (skip)")
        return
    df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
    df.columns = ["open", "high", "low", "close", "volume"]
    out = df.reset_index().rename(columns={df.index.name or "Date": "ts"})
    out = out.rename(columns={out.columns[0]: "ts"})
    out["ts"] = out["ts"].astype(str)
    base = sym.replace(".NS", "")
    out[["ts", "open", "high", "low", "close", "volume"]].to_csv(
        os.path.join(folder, f"{base}_1d.csv"), index=False)
    print(f"  {sym}: daily {len(out)} rows")


def write_intraday(sym, folder):
    df = yf.download(sym, interval="15m", period="5d", auto_adjust=False, progress=False)
    if df is None or df.empty:
        print(f"  {sym}: 15m EMPTY (skip)")
        return
    df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
    df.columns = ["open", "high", "low", "close", "volume"]
    # drop trailing incomplete bars (yfinance forming bars have volume 0)
    while len(df) and (df["volume"].iloc[-1] == 0 or df["close"].iloc[-1] == 0):
        df = df.iloc[:-1]
    out = df.reset_index()
    out = out.rename(columns={out.columns[0]: "ts"})
    out["ts"] = out["ts"].astype(str)
    base = sym.replace(".NS", "")
    out[["ts", "open", "high", "low", "close", "volume"]].to_csv(
        os.path.join(folder, f"{base}_15m.csv"), index=False)
    print(f"  {sym}: 15m {len(out)} rows")


def fetch_sector_etfs():
    for sector, (etf, _) in SECTORS.items():
        print(f"[{sector}] ETF {etf}")
        d = yf.download(etf, start="2024-01-01", auto_adjust=False, progress=False)
        write(etf, d, os.path.join(DATA, "etf"))
        write_intraday(etf, os.path.join(DATA, "etf"))


def fetch_sector_stocks(sector):
    etf, stocks = SECTORS[sector]
    print(f"[{sector}] fetching {len(stocks)} constituents")
    d = yf.download(stocks, start="2024-01-01", auto_adjust=False, group_by="ticker", progress=False)
    # fundamentals
    fund_rows = []
    for sym in stocks:
        base = sym.replace(".NS", "")
        try:
            sd = d[sym]
            write(sym, sd, os.path.join(DATA, "stock"))
            write_intraday(sym, os.path.join(DATA, "stock"))
            info = yf.Ticker(sym).info
            fund_rows.append((base, info.get("floatShares", 0), info.get("marketCap", 0)))
        except Exception as e:
            print(f"  {sym}: ERR {str(e)[:60]}")
    if fund_rows:
        pf = os.path.join(DATA, "fundamentals.csv")
        fd = pd.DataFrame(fund_rows, columns=["symbol", "float_shares", "market_cap"])
        existing = pd.read_csv(pf) if os.path.exists(pf) else pd.DataFrame(columns=fd.columns)
        merged = pd.concat([existing, fd]).drop_duplicates("symbol", keep="last")
        merged.to_csv(pf, index=False)
        print(f"  wrote {len(fund_rows)} fundamentals")


if __name__ == "__main__":
    arg = sys.argv[1].upper() if len(sys.argv) > 1 else None
    if arg is None:
        fetch_sector_etfs()
        print("\nNow run:  fetch_data.py <SECTOR>  (e.g. BANK) to pull that sector's stocks")
    elif arg in SECTORS:
        fetch_sector_stocks(arg)
    else:
        print(f"unknown sector {arg}; options: {list(SECTORS)}")
