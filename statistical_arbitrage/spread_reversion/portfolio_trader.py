#!/usr/bin/env python3
"""
Paper portfolio trader: BANKBEES vs SETFNIFBK spread reversion with STOP LOSS.
Portfolio balance is tracked in rupees; position size computed from it.
Pole 2007: spread = ln(PA) - ln(PB); enter |z|>2; exit z crosses 0, or stop-loss/take-profit.
Fees: Groww intraday (MIS), 4 legs per round trip.  PURELY PAPER - no orders placed.
"""
import math
import os
import sys
import time
from collections import deque
from datetime import datetime, timedelta, timezone

from growwapi import GrowwAPI

# ---------- portfolio (rupees) ----------
PORTFOLIO   = 5000.0   # starting balance in ₹
CAPITAL_USE = 0.5      # fraction of portfolio invested per trade (0.5 = 50%)

# ---------- strategy ----------
WINDOW        = 60
WARMUP        = 5
ENTRY_Z       = 2.0
POLL_SECS     = 30
STOP_LOSS_RS  = 100.0  # cut trade if unrealized loss >= this many ₹
TAKE_PROFIT_RS = 0.0   # 0 = disabled; else exit at profit >= this many ₹

# ---------- fees (Groww intraday MIS) ----------
BROKERAGE_FLAT, BROKERAGE_PCT, BROKERAGE_MIN = 20.0, 0.001, 5.0
STT_PCT, STAMP_PCT, EXCH_PCT = 0.00025, 0.00003, 0.0000297
SEBI_PCT, IPFT_PCT, GST_PCT = 0.000001, 0.000001, 0.18

PAIR_A, PAIR_B = "BANKBEES", "SETFNIFBK"
MIN_PRICE, MAX_PRICE = 100.0, 10000.0
IST = timezone(timedelta(hours=5, minutes=30))


def log(msg):
    print(f"[{datetime.now(IST).isoformat(timespec='seconds')}] {msg}", flush=True)


def leg_fees(price, qty, side):
    v = price * qty
    brk = max(min(BROKERAGE_FLAT, BROKERAGE_PCT * v), BROKERAGE_MIN)
    stt = v * STT_PCT if side == "SELL" else 0.0
    stamp = v * STAMP_PCT if side == "BUY" else 0.0
    exch, sebi, ipft = v * EXCH_PCT, v * SEBI_PCT, v * IPFT_PCT
    return brk + stt + stamp + exch + sebi + ipft + GST_PCT * (brk + exch + sebi + ipft)


def entry_fees(d, pa, pb, qty):
    return (leg_fees(pa, qty, "BUY") + leg_fees(pb, qty, "SELL")) if d == "LONG" \
        else (leg_fees(pa, qty, "SELL") + leg_fees(pb, qty, "BUY"))


def exit_fees(d, pa, pb, qty):
    return (leg_fees(pa, qty, "SELL") + leg_fees(pb, qty, "BUY")) if d == "LONG" \
        else (leg_fees(pa, qty, "BUY") + leg_fees(pb, qty, "SELL"))


def gross_pnl(d, epa, epb, pa, pb, qty):
    if d == "LONG":
        return (pa - epa) * qty - (pb - epb) * qty
    return (epa - pa) * qty + (pb - epb) * qty


def compute_qty(pa, pb):
    """Invest CAPITAL_USE of the current portfolio (₹) in the pair, one unit each leg."""
    budget = portfolio * CAPITAL_USE
    return max(int(budget / (pa + pb)), 1)


def fetch_pair(groww):
    resp = groww.get_ltp(segment="CASH", exchange_trading_symbols=(f"NSE_{PAIR_A}", f"NSE_{PAIR_B}"))
    pa = float(resp.get(f"NSE_{PAIR_A}", 0))
    pb = float(resp.get(f"NSE_{PAIR_B}", 0))
    if pa <= MIN_PRICE or pa > MAX_PRICE or pb <= MIN_PRICE or pb > MAX_PRICE:
        raise ValueError(f"price out of range [{MIN_PRICE}-{MAX_PRICE}] pa={pa} pb={pb}")
    return pa, pb


def main():
    global portfolio
    portfolio = PORTFOLIO
    log(f"=== PORTFOLIO PAPER TRADER: {PAIR_A} vs {PAIR_B} ===")
    log(f"portfolio=₹{portfolio:.2f}  invest={CAPITAL_USE*100:.0f}%/trade  "
        f"window={WINDOW}  entry_z=±{ENTRY_Z}  stop_loss=₹{STOP_LOSS_RS}  tp=₹{TAKE_PROFIT_RS or 'off'}")

    api_key = os.getenv("GROWW_API_KEY")
    secret = os.getenv("GROWW_API_SECRET")
    token = os.getenv("GROWW_ACCESS_TOKEN")
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
        sys.exit(1)

    history = deque(maxlen=WINDOW)
    position = None
    total_fees = 0.0
    tick = 0
    day = datetime.now(IST).date()

    while True:
        try:
            pa, pb = fetch_pair(groww)
        except Exception as e:
            log(f"fetch error: {e}")
            time.sleep(POLL_SECS)
            continue

        if datetime.now(IST).date() != day:
            history.clear()
            tick = 0
            day = datetime.now(IST).date()
            log(f"new trading day {day} — window reset  portfolio=₹{portfolio:.2f}")

        spread = math.log(pa) - math.log(pb)
        history.append(spread)
        tick += 1

        if len(history) < WARMUP:
            log(f"warmup {len(history)}/{WINDOW}  pa={pa:.2f} pb={pb:.2f}")
            time.sleep(POLL_SECS)
            continue

        mean = sum(history) / len(history)
        var = sum((s - mean) ** 2 for s in history) / len(history)
        std = max(math.sqrt(var), 0.0001)
        z = (spread - mean) / std

        if position is None:
            if z > ENTRY_Z:
                direction = "SHORT"
            elif z < -ENTRY_Z:
                direction = "LONG"
            else:
                direction = None

            if direction is not None:
                qty = compute_qty(pa, pb)
                position = {"dir": direction, "pa": pa, "pb": pb, "qty": qty,
                            "fees_entry": entry_fees(direction, pa, pb, qty), "tick": tick}
                invested = (pa + pb) * qty
                log(f"ENTER {direction}  qty={qty}  invested=₹{invested:.2f} "
                    f"({invested/portfolio*100:.1f}% of portfolio)  z={z:+.2f}  "
                    f"est_entry_fees=₹{position['fees_entry']:.2f}")
            elif tick % 6 == 0:
                log(f"idle  z={z:+.3f}  portfolio=₹{portfolio:.2f}")
        else:
            g = gross_pnl(position["dir"], position["pa"], position["pb"], pa, pb, position["qty"])
            reason = None
            if g <= -STOP_LOSS_RS:
                reason = "STOP LOSS"
            elif TAKE_PROFIT_RS > 0 and g >= TAKE_PROFIT_RS:
                reason = "TAKE PROFIT"
            elif z >= 0.0 if position["dir"] == "LONG" else z <= 0.0:
                reason = "Z-CROSS"

            if reason:
                fees = position["fees_entry"] + exit_fees(position["dir"], pa, pb, position["qty"])
                net = g - fees
                portfolio += net
                total_fees += fees
                log(
                    f"{reason} {position['dir']}  gross=₹{g:+.2f}  fees=₹{fees:.2f}  "
                    f"net=₹{net:+.2f}  portfolio=₹{portfolio:+.2f}  "
                    f"held={tick - position['tick']} ticks"
                )
                position = None
            elif tick % 3 == 0:
                log(f"hold {position['dir']}  unreal=₹{g:+.2f}  z={z:+.3f}  "
                    f"stop_at=₹{-STOP_LOSS_RS:+.2f}  portfolio=₹{portfolio:.2f}")

        time.sleep(POLL_SECS)


if __name__ == "__main__":
    main()
