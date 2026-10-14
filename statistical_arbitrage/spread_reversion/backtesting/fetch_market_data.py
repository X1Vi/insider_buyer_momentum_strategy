#!/usr/bin/env python3
"""Fetch ETF + S&P daily history via yfinance and cache as CSVs for the scanner.

Writes new files into backtesting/data/ (existing files are untouched):
    BANKBEES.csv, SETFNIFBK.csv, NIFTYBEES.csv, SETFNIF50.csv, SP500.csv
Format matches the existing data:  ts,close,volume

Run:
    .venv/bin/python backtesting/fetch_market_data.py
"""
import os

import pandas as pd
import yfinance as yf

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")

# (ticker on yfinance, cached filename)
SYMBOLS = [
    ("BANKBEES.NS", "BANKBEES"),
    ("SETFNIFBK.NS", "SETFNIFBK"),
    ("NIFTYBEES.NS", "NIFTYBEES"),
    ("SETFNIF50.NS", "SETFNIF50"),
    ("^GSPC", "SP500"),
]


def fetch_one(ticker, out_name):
    path = os.path.join(DATA, f"{out_name}.csv")
    print(f"fetching {ticker} -> {path} ...", end=" ", flush=True)
    df = yf.download(ticker, start="2022-01-01", auto_adjust=False, progress=False)
    if df is None or df.empty:
        print("EMPTY (skip)")
        return
    df = df[["Close", "Volume"]].dropna()
    df.columns = ["close", "volume"]
    out = df.reset_index()
    out = out.rename(columns={out.columns[0]: "ts"})
    out["ts"] = out["ts"].astype(str).str[:10]
    out[["ts", "close", "volume"]].to_csv(path, index=False)
    print(f"{len(out)} rows, {out['ts'].iloc[0]}..{out['ts'].iloc[-1]}")


if __name__ == "__main__":
    os.makedirs(DATA, exist_ok=True)
    for ticker, name in SYMBOLS:
        fetch_one(ticker, name)
    print("done")
