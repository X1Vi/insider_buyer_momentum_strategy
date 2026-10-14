#!/usr/bin/env python3
"""
Spread reversion pair trade: BANKBEES vs SETFNIFBK (Groww API).
Pole 2007: spread=ln(PA)-ln(PB), enter |z|>2, exit z→0.
PAPER_TRADING toggle below gates real order placement.
Stdout-only logging (Groww sandbox: no writable filesystem).
"""

# ============================================================
# ⚠️  PAPER_TRADING: True  = simulated P&L, zero real orders
#     PAPER_TRADING: False = LIVE MARKET orders (real money!)
#     Test thoroughly in paper mode before disabling.
# ============================================================
PAPER_TRADING = True

import math
import os
import sys
import time
import traceback
from collections import deque
from datetime import datetime, timedelta, timezone

from growwapi import GrowwAPI

PAIR_A = "BANKBEES"
PAIR_B = "SETFNIFBK"
WINDOW = 60
WARMUP = 5
ENTRY_Z = 2.0
POLL_SECS = 30
TRADE_QTY = 100

MIN_PRICE = 100.0
MAX_PRICE = 10000.0

BROKERAGE_FLAT = 20.0
BROKERAGE_PCT  = 0.001
BROKERAGE_MIN  = 5.0
STT_PCT        = 0.00025
STAMP_PCT      = 0.00003
EXCH_PCT       = 0.0000297
SEBI_PCT       = 0.000001
IPFT_PCT       = 0.000001
GST_PCT        = 0.18

IST = timezone(timedelta(hours=5, minutes=30))


def log(msg):
    print(f"[{datetime.now(IST).isoformat(timespec='seconds')}] {msg}", flush=True)


# ---------- fee model (Groww intraday MIS) ----------

def leg_fees(price, qty, side):
    value = price * qty
    brokerage = max(min(BROKERAGE_FLAT, BROKERAGE_PCT * value), BROKERAGE_MIN)
    stt   = value * STT_PCT   if side == "SELL" else 0.0
    stamp = value * STAMP_PCT if side == "BUY"  else 0.0
    exch  = value * EXCH_PCT
    sebi  = value * SEBI_PCT
    ipft  = value * IPFT_PCT
    gst   = GST_PCT * (brokerage + exch + sebi + ipft)
    return brokerage + stt + stamp + exch + sebi + ipft + gst


def entry_fees(direction, pa, pb):
    if direction == "LONG":
        return leg_fees(pa, TRADE_QTY, "BUY")  + leg_fees(pb, TRADE_QTY, "SELL")
    return leg_fees(pa, TRADE_QTY, "SELL") + leg_fees(pb, TRADE_QTY, "BUY")


def exit_fees(direction, pa, pb):
    if direction == "LONG":
        return leg_fees(pa, TRADE_QTY, "SELL") + leg_fees(pb, TRADE_QTY, "BUY")
    return leg_fees(pa, TRADE_QTY, "BUY")  + leg_fees(pb, TRADE_QTY, "SELL")


# ---------- PnL ----------

def gross_pnl(direction, entry_pa, entry_pb, pa, pb):
    if direction == "LONG":
        return (pa - entry_pa) * TRADE_QTY - (pb - entry_pb) * TRADE_QTY
    return (entry_pa - pa) * TRADE_QTY + (pb - entry_pb) * TRADE_QTY


# ---------- API helpers ----------

def fetch_pair(groww):
    resp = groww.get_ltp(
        segment=groww.SEGMENT_CASH,
        exchange_trading_symbols=(f"NSE_{PAIR_A}", f"NSE_{PAIR_B}"),
    )
    pa = float(resp.get(f"NSE_{PAIR_A}", 0))
    pb = float(resp.get(f"NSE_{PAIR_B}", 0))
    if pa <= MIN_PRICE or pa > MAX_PRICE or pb <= MIN_PRICE or pb > MAX_PRICE:
        raise ValueError(f"price out of range [{MIN_PRICE}-{MAX_PRICE}] pa={pa} pb={pb}")
    return pa, pb


def place_leg(groww, symbol, txn_type):
    return groww.place_order(
        trading_symbol=symbol,
        quantity=TRADE_QTY,
        validity=groww.VALIDITY_DAY,
        exchange=groww.EXCHANGE_NSE,
        segment=groww.SEGMENT_CASH,
        product=groww.PRODUCT_MIS,
        order_type=groww.ORDER_TYPE_MARKET,
        transaction_type=txn_type,
    )


def place_entry_orders(groww, direction):
    if direction == "LONG":
        return [
            place_leg(groww, PAIR_A, groww.TRANSACTION_TYPE_BUY),
            place_leg(groww, PAIR_B, groww.TRANSACTION_TYPE_SELL),
        ]
    return [
        place_leg(groww, PAIR_A, groww.TRANSACTION_TYPE_SELL),
        place_leg(groww, PAIR_B, groww.TRANSACTION_TYPE_BUY),
    ]


def place_exit_orders(groww, direction):
    if direction == "LONG":
        return [
            place_leg(groww, PAIR_A, groww.TRANSACTION_TYPE_SELL),
            place_leg(groww, PAIR_B, groww.TRANSACTION_TYPE_BUY),
        ]
    return [
        place_leg(groww, PAIR_A, groww.TRANSACTION_TYPE_BUY),
        place_leg(groww, PAIR_B, groww.TRANSACTION_TYPE_SELL),
    ]


def order_ids(responses):
    return [r.get("groww_order_id", "?") if isinstance(r, dict) else "?" for r in responses]


# ---------- main loop ----------

def main():
    log(f"=== spread reversion: {PAIR_A} vs {PAIR_B} ===")
    log(f"PAPER_TRADING={'ON' if PAPER_TRADING else 'OFF — LIVE ORDERS!'}")
    log(f"window={WINDOW} warmup={WARMUP} entry_z=±{ENTRY_Z} qty={TRADE_QTY} poll={POLL_SECS}s")

    api_key = os.getenv("GROWW_API_KEY")
    secret  = os.getenv("GROWW_API_SECRET")
    token   = os.getenv("GROWW_ACCESS_TOKEN")

    try:
        if token:
            groww = GrowwAPI(token)
        elif api_key and secret:
            groww = GrowwAPI(GrowwAPI.get_access_token(api_key=api_key, secret=secret))
        else:
            log("FATAL: set GROWW_API_KEY+GROWW_API_SECRET or GROWW_ACCESS_TOKEN")
            sys.exit(1)
    except Exception as e:
        log(f"FATAL: auth failed — {e}")
        traceback.print_exc()
        sys.exit(1)

    history = deque(maxlen=WINDOW)
    position = None
    total_gross = 0.0
    total_fees = 0.0
    tick = 0
    day = datetime.now(IST).date()
    exit_retries = 0

    while True:
        try:
            pa, pb = fetch_pair(groww)
        except Exception as e:
            log(f"fetch error: {e}")
            time.sleep(POLL_SECS)
            continue

        now = datetime.now(IST)

        # ---- day rollover ----
        if now.date() != day:
            if position:
                if PAPER_TRADING:
                    # paper: force-close position at day boundary
                    g = gross_pnl(position["dir"], position["pa"], position["pb"], pa, pb)
                    fees = position["fees_entry"] + exit_fees(position["dir"], pa, pb)
                    total_gross += g
                    total_fees += fees
                    log(
                        f"DAY-ROLLOVER CLOSE {position['dir']}  "
                        f"gross=₹{g:+.2f}  fees=₹{fees:.2f}  net=₹{g - fees:+.2f}  "
                        f"total_net=₹{total_gross - total_fees:+.2f}"
                    )
                    position = None
                else:
                    # real: cannot trade at midnight — keep position open, reset only the window
                    log(
                        f"NEW DAY — window reset, position {position['dir']} remains open "
                        f"(real exit on z-cross only)"
                    )
                    if "orders" in position:
                        log(f"  entry orders still tracked: {position['orders']}")
            history.clear()
            tick = 0
            day = now.date()

        # ---- spread & z-score ----
        spread = math.log(pa) - math.log(pb)
        history.append(spread)
        tick += 1

        if len(history) < WARMUP:
            log(f"warmup {len(history)}/{WINDOW}  pa={pa:.2f} pb={pb:.2f} spread={spread:.6f}")
            time.sleep(POLL_SECS)
            continue

        mean = sum(history) / len(history)
        var = sum((s - mean) ** 2 for s in history) / len(history)
        std = max(math.sqrt(var), 0.0001)
        z = (spread - mean) / std

        # ---- no position → check entry ----
        if position is None:
            if z > ENTRY_Z:
                direction = "SHORT"
            elif z < -ENTRY_Z:
                direction = "LONG"
            else:
                direction = None

            if direction is not None:
                entry_f = entry_fees(direction, pa, pb)
                orders = []

                if not PAPER_TRADING:
                    try:
                        orders = place_entry_orders(groww, direction)
                        log(f"  real entry orders: {order_ids(orders)}")
                    except Exception as e:
                        log(f"  ENTRY ORDER FAILED ({direction}): {e} — aborting entry")
                        traceback.print_exc()
                        time.sleep(POLL_SECS)
                        continue

                position = {
                    "dir": direction, "pa": pa, "pb": pb,
                    "z": z, "tick": tick, "fees_entry": entry_f,
                }
                if not PAPER_TRADING:
                    position["orders"] = orders

                log(
                    f"ENTER {direction}  z={z:+.2f} spread={spread:.6f}  "
                    f"qty={TRADE_QTY}  pa={pa:.2f} pb={pb:.2f}  "
                    f"est_entry_fees=₹{entry_f:.2f}"
                )
            elif tick % 6 == 0:
                log(f"idle  z={z:+.3f} spread={spread:.6f}")

        # ---- in position → check exit ----
        else:
            g = gross_pnl(position["dir"], position["pa"], position["pb"], pa, pb)
            should_exit = z >= 0.0 if position["dir"] == "LONG" else z <= 0.0

            if should_exit:
                exit_f = exit_fees(position["dir"], pa, pb)
                fees = position["fees_entry"] + exit_f

                if not PAPER_TRADING:
                    try:
                        orders = place_exit_orders(groww, position["dir"])
                        log(f"  real exit orders: {order_ids(orders)}")
                        exit_retries = 0
                    except Exception as e:
                        exit_retries += 1
                        log(
                            f"  EXIT ORDER FAILED ({position['dir']}, retry #{exit_retries}): {e} "
                            f"— will retry next tick"
                        )
                        traceback.print_exc()
                        # CRITICAL: do NOT clear position — real orders are unfilled
                        time.sleep(POLL_SECS)
                        continue

                total_gross += g
                total_fees += fees
                log(
                    f"EXIT {position['dir']}  gross=₹{g:+.2f}  fees=₹{fees:.2f}  "
                    f"net=₹{g - fees:.2f}  held={tick - position['tick']} ticks  "
                    f"total_gross=₹{total_gross:+.2f}  total_fees=₹{total_fees:.2f}  "
                    f"total_net=₹{total_gross - total_fees:+.2f}"
                )
                position = None
            elif tick % 3 == 0:
                log(
                    f"hold {position['dir']}  unreal=₹{g:+.2f}  z={z:+.3f}  "
                    f"ticks={tick - position['tick']}"
                )

        time.sleep(POLL_SECS)


if __name__ == "__main__":
    main()
