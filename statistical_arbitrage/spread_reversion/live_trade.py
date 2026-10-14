#!/usr/bin/env python3
"""
LIVE TRADE (one-sided, LONG) — BANKBEES vs SETFNIFBK spread reversion.
Live prices via Groww get_ltp, refresh 1-5s. MANUAL — no orders placed; alerts you.
  ENTER LONG when z < -2  -> BUY  BANKBEES qty / SELL SETFNIFBK qty
  EXIT        when z >= 0  (reversion complete)
  STOP LOSS   when unrealized loss <= -STOP_LOSS_RS  (default ₹400 = 2% of ₹20,000)
Every refresh shows the live stop-loss level so you know exactly when to cut.
Usage: python live_trade.py [refresh_secs=3] [window=60]
Env:   GROWW_ACCESS_TOKEN or GROWW_API_KEY/GROWW_API_SECRET
"""
import math
import os
import subprocess
import sys
import time
from collections import deque
from datetime import datetime, timedelta, timezone

from growwapi import GrowwAPI

PAIR_A, PAIR_B = "BANKBEES", "SETFNIFBK"
SIDE = "LONG"                 # one-sided
REFRESH_SECS = int(sys.argv[1]) if len(sys.argv) > 1 else 3
WINDOW = int(sys.argv[2]) if len(sys.argv) > 2 else 60
WARMUP = 5
ENTRY_Z = 2.0
CAPITAL = 20000.0             # per trade
STOP_LOSS_RS = 400.0          # strong stop: 2% of capital
MIN_PRICE, MAX_PRICE = 100.0, 10000.0
IST = timezone(timedelta(hours=5, minutes=30))


def now():
    return datetime.now(IST)


def log(msg):
    print(f"[{now().strftime('%H:%M:%S')}] {msg}", flush=True)


def beep():
    for _ in range(4):
        print("\a", end="", flush=True)
        time.sleep(0.12)
    for cmd in (("paplay", "/usr/share/sounds/freedesktop/stereo/bell.oga"),
                ("aplay", "/usr/share/sounds/alsa/Front_Center.wav")):
        if os.path.exists(cmd[1]):
            try:
                subprocess.run(cmd, timeout=2, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass


def alert(msg):
    print("\n" + "=" * 54, flush=True)
    print(f">>> {msg} <<<", flush=True)
    print("=" * 54, flush=True)
    beep()


def fetch_pair(groww):
    resp = groww.get_ltp(segment="CASH", exchange_trading_symbols=(f"NSE_{PAIR_A}", f"NSE_{PAIR_B}"))
    pa = float(resp.get(f"NSE_{PAIR_A}", 0))
    pb = float(resp.get(f"NSE_{PAIR_B}", 0))
    if pa <= MIN_PRICE or pa > MAX_PRICE or pb <= MIN_PRICE or pb > MAX_PRICE:
        raise ValueError(f"price out of range pa={pa} pb={pb}")
    return pa, pb


def main():
    log(f"=== LIVE TRADE (one-sided {SIDE})  {PAIR_A} vs {PAIR_B}  "
        f"refresh={REFRESH_SECS}s  window={WINDOW}  capital=₹{CAPITAL:,.0f}  "
        f"stop_loss=₹{STOP_LOSS_RS:,.0f} ===")

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
    state = "FLAT"             # FLAT | LONG
    entry = None               # dict with z, pa, pb, qty, at
    z = 0.0
    spread = 0.0
    ticks = 0
    pa = pb = 0.0

    while True:
        try:
            pa, pb = fetch_pair(groww)
        except Exception as e:
            log(f"fetch error: {e}")
            time.sleep(REFRESH_SECS)
            continue

        ticks += 1
        spread = math.log(pa) - math.log(pb)
        history.append(spread)

        if len(history) >= WARMUP:
            mean = sum(history) / len(history)
            var = sum((s - mean) ** 2 for s in history) / len(history)
            z = (spread - mean) / max(math.sqrt(var), 1e-4)

            if state == "FLAT" and z < -ENTRY_Z:
                qty = max(int(CAPITAL / (pa + pb)), 1)
                state = "LONG"
                entry = {"z": z, "pa": pa, "pb": pb, "qty": qty,
                         "at": now().strftime("%H:%M:%S")}
                alert(f"ENTER LONG  z={z:+.2f}  -> BUY {qty} {PAIR_A} / SELL {qty} {PAIR_B}\n"
                      f"     STOP LOSS: exit if loss >= ₹{STOP_LOSS_RS:,.0f} "
                      f"(≈ ₹{STOP_LOSS_RS/qty:.2f}/unit spread move)")
            elif state == "LONG":
                g = (pa - entry["pa"]) * entry["qty"] - (pb - entry["pb"]) * entry["qty"]
                stop_pu = STOP_LOSS_RS / entry["qty"]
                if g <= -STOP_LOSS_RS:
                    alert(f"STOP LOSS HIT  loss=₹{g:,.0f} >= ₹{STOP_LOSS_RS:,.0f}  "
                          f"-> EXIT LONG NOW (buy back both legs)")
                    state = "FLAT"
                    entry = None
                elif z >= 0.0:
                    alert(f"EXIT LONG  z={z:+.2f}  reversion complete "
                          f"(entry z={entry['z']:+.2f} @ {entry['at']})")
                    state = "FLAT"
                    entry = None
                else:
                    # live stop-loss level display
                    spread_move = (pa - entry["pa"]) - (pb - entry["pb"])
                    print(f"  [LIVE] unrealized=₹{g:+,.2f}   STOP at -₹{STOP_LOSS_RS:,.0f} "
                          f"(≈ ₹{stop_pu:.2f}/unit, spread move {spread_move:+.3f} vs trigger {-stop_pu:.3f})")

        # ---- dashboard ----
        print("\033[H\033[J", end="", flush=True)
        print(f"=== LIVE TRADE {PAIR_A} vs {PAIR_B}  [{now().strftime('%H:%M:%S')}]  "
              f"refresh={REFRESH_SECS}s window={WINDOW} ===")
        print(f"{PAIR_A}={pa:.2f}  {PAIR_B}={pb:.2f}  spread(ln)={spread:.6f}  z={z:+.2f}")
        if state == "FLAT":
            print(f"state: FLAT  qty~{max(int(CAPITAL/(pa+pb)),1)}  ticks={ticks}  hist={len(history)}")
            print("[watch: ENTER LONG when z < -2]")
        else:
            g = (pa - entry["pa"]) * entry["qty"] - (pb - entry["pb"]) * entry["qty"]
            stop_pu = STOP_LOSS_RS / entry["qty"]
            print(f"state: LONG  qty={entry['qty']}  entry z={entry['z']:+.2f} @ {entry['at']}")
            print(f"unrealized: ₹{g:+,.2f}")
            print(f"STOP LOSS: exit if loss >= ₹{STOP_LOSS_RS:,.0f}  "
                  f"(≈ ₹{stop_pu:.2f}/unit spread move)")
            print(f"TARGET: exit LONG when z >= 0 (currently {z:+.2f})")


if __name__ == "__main__":
    main()
