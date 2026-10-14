#!/usr/bin/env python3
"""
LIVE spread reversion: BANKBEES vs SETFNIFBK (Groww API).
Inventory-based sizing from actual margin balance.
Places MARKET/MIS orders.  Stdout-only logging.
"""
import math, os, sys, time
from collections import deque
from datetime import datetime, timedelta, timezone
from growwapi import GrowwAPI

PAIR_A = "BANKBEES"
PAIR_B = "SETFNIFBK"
WINDOW = 60
WARMUP = 5
ENTRY_Z = 2.0
POLL_SECS = 30
MIN_QTY = 1
MIN_PRICE = 100.0
MAX_PRICE = 10000.0
BAL_SAFETY = 0.95

IST = timezone(timedelta(hours=5, minutes=30))


def log(msg):
    print(f"[{datetime.now(IST).isoformat(timespec='seconds')}] {msg}", flush=True)


def fetch_pair(groww):
    resp = groww.get_ltp(segment="CASH", exchange_trading_symbols=(f"NSE_{PAIR_A}", f"NSE_{PAIR_B}"))
    pa = float(resp.get(f"NSE_{PAIR_A}", 0))
    pb = float(resp.get(f"NSE_{PAIR_B}", 0))
    if pa <= MIN_PRICE or pa > MAX_PRICE or pb <= MIN_PRICE or pb > MAX_PRICE:
        raise ValueError(f"price out of range [{MIN_PRICE}-{MAX_PRICE}] pa={pa} pb={pb}")
    return pa, pb


def get_balance(groww):
    m = groww.get_available_margin_details()
    return float(m.get("equity_margin_details", {}).get("mis_balance_available", 0)) * BAL_SAFETY


def margin_per_leg(groww, symbol, price, txn):
    resp = groww.get_order_margin_details(segment="CASH", orders=[{
        "trading_symbol": symbol, "transaction_type": txn, "quantity": 1,
        "price": price, "order_type": "MARKET", "product": "MIS", "exchange": "NSE",
    }])
    return float(resp.get("total_requirement", 0))


def compute_qty(groww, pa, pb):
    bal = get_balance(groww)
    if bal <= 0:
        return 0
    per_pair = margin_per_leg(groww, PAIR_A, pa, "BUY") + margin_per_leg(groww, PAIR_B, pb, "SELL")
    if per_pair <= 0:
        return 0
    return max(int(bal / per_pair), MIN_QTY)


def entry_legs(d):
    if d == "SHORT":
        return [(PAIR_A, "SELL"), (PAIR_B, "BUY")]
    return [(PAIR_A, "BUY"), (PAIR_B, "SELL")]


def exit_legs(d):
    if d == "SHORT":
        return [(PAIR_A, "BUY"), (PAIR_B, "SELL")]
    return [(PAIR_A, "SELL"), (PAIR_B, "BUY")]


def place_orders(groww, legs, qty):
    resps = []
    for i, (sym, txn) in enumerate(legs):
        if i > 0:
            time.sleep(0.5)
        resps.append(groww.place_order(
            trading_symbol=sym, quantity=qty, validity="DAY", exchange="NSE",
            segment="CASH", product="MIS", order_type="MARKET", transaction_type=txn,
        ))
    return resps


def gross_pnl(direction, epa, epb, pa, pb, qty):
    if direction == "LONG":
        return (pa - epa) * qty - (pb - epb) * qty
    return (epa - pa) * qty + (pb - epb) * qty


def main():
    log(f"=== LIVE: {PAIR_A} vs {PAIR_B} ===")
    log(f"window={WINDOW} warmup={WARMUP} entry_z=±{ENTRY_Z} poll={POLL_SECS}s bal_safety={BAL_SAFETY}")

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
        sys.exit(1)

    # -- startup sanity --
    try:
        pa_s, pb_s = fetch_pair(groww)
        log(f"sanity: prices OK  {PAIR_A}={pa_s:.2f} {PAIR_B}={pb_s:.2f}")
    except Exception as e:
        log(f"FATAL: cannot fetch prices — {e}")
        sys.exit(1)

    try:
        bal_s = get_balance(groww)
        log(f"sanity: mis_balance_available=₹{bal_s:.2f}")
        if bal_s <= 0:
            log("FATAL: zero available margin")
            sys.exit(1)
    except Exception as e:
        log(f"FATAL: cannot check balance — {e}")
        sys.exit(1)

    try:
        pos = groww.get_positions_for_user(segment="CASH")
        for p in pos.get("positions", []):
            if p.get("trading_symbol") in (PAIR_A, PAIR_B):
                log(f"WARNING: orphan position in {p['trading_symbol']} (qty={p.get('quantity')}, product={p.get('product')}) — manual check advised")
    except Exception as e:
        log(f"warning: could not check positions — {e}")

    # -- main loop --
    history = deque(maxlen=WINDOW)
    position = None
    total_pnl = 0.0
    tick = 0

    while True:
        try:
            pa, pb = fetch_pair(groww)
        except Exception as e:
            log(f"fetch error: {e}")
            time.sleep(POLL_SECS)
            continue

        spread = math.log(pa) - math.log(pb)
        history.append(spread)
        tick += 1

        if len(history) < WARMUP:
            log(f"warmup {len(history)}/{WINDOW}  pa={pa:.2f} pb={pb:.2f} spread={spread:.6f}")
            time.sleep(POLL_SECS)
            continue

        mean = sum(history) / len(history)
        var  = sum((s - mean) ** 2 for s in history) / len(history)
        std  = max(math.sqrt(var), 0.0001)
        z    = (spread - mean) / std

        if position is None:
            if z > ENTRY_Z:
                direction = "SHORT"
            elif z < -ENTRY_Z:
                direction = "LONG"
            else:
                direction = None

            if direction is not None:
                try:
                    qty = compute_qty(groww, pa, pb)
                    if qty < MIN_QTY:
                        log(f"SKIP {direction}: qty={qty} — insufficient margin")
                        time.sleep(POLL_SECS)
                        continue
                    legs = entry_legs(direction)
                    orders = place_orders(groww, legs, qty)
                    ids = [r.get("groww_order_id", "?") for r in orders]
                    log(f"ENTER {direction}  qty={qty}  z={z:+.2f}  pa={pa:.2f} pb={pb:.2f}  orders={ids}")
                    position = {"dir": direction, "pa": pa, "pb": pb, "qty": qty, "orders": ids, "tick": tick}
                except Exception as e:
                    log(f"ENTRY FAILED ({direction}): {e}")
            elif tick % 6 == 0:
                log(f"idle  z={z:+.3f} spread={spread:.6f}")
        else:
            g = gross_pnl(position["dir"], position["pa"], position["pb"], pa, pb, position["qty"])
            should_exit = z >= 0.0 if position["dir"] == "LONG" else z <= 0.0
            if should_exit:
                try:
                    legs = exit_legs(position["dir"])
                    orders = place_orders(groww, legs, position["qty"])
                    ids = [r.get("groww_order_id", "?") for r in orders]
                    total_pnl += g
                    log(
                        f"EXIT {position['dir']}  est_gross=₹{g:+.2f}  total_est=₹{total_pnl:+.2f}  "
                        f"held={tick - position['tick']} ticks  orders={ids}"
                    )
                    position = None
                except Exception as e:
                    log(f"EXIT FAILED ({position['dir']}): {e} — retrying next tick")
            elif tick % 3 == 0:
                log(f"hold {position['dir']}  unreal=₹{g:+.2f}  z={z:+.3f}  ticks={tick - position['tick']}")

        time.sleep(POLL_SECS)


if __name__ == "__main__":
    main()
