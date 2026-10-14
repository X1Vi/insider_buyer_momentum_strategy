#!/usr/bin/env python3
"""
LIVE indicator (Groww) — two-sided spread reversion with 1-5s refresh + ALERT SOUND.
Real-time via Groww get_ltp (rate limit: Live Data 10/sec, 300/min -> 1-5s refresh is safe).
  LONG  when z < -2  -> BUY  BANKBEES / SELL SETFNIFBK   (exit z >= 0)
  SHORT when z > +2  -> SELL BANKBEES / BUY  SETFNIFBK   (exit z <= 0)
Sounds an alert when it is time to enter or exit. MANUAL trading - no orders placed.
SIDE = "BOTH" (default) | "LONG" | "SHORT"
Usage: python indicator_groww.py [refresh_secs=3] [window=60]
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
SIDE = "BOTH"
REFRESH_SECS = int(sys.argv[1]) if len(sys.argv) > 1 else 3
WINDOW = int(sys.argv[2]) if len(sys.argv) > 2 else 60
WARMUP = 5
ENTRY_Z = 2.0
CAPITAL = 10000.0          # 5000..20000 for qty suggestion
MIN_PRICE, MAX_PRICE = 100.0, 10000.0
IST = timezone(timedelta(hours=5, minutes=30))


def log(msg):
    print(f"[{datetime.now(IST).strftime('%H:%M:%S')}] {msg}", flush=True)


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
    print("\n" + "=" * 50, flush=True)
    print(f">>> {msg} <<<", flush=True)
    print("=" * 50, flush=True)
    beep()


def fetch_pair(groww):
    resp = groww.get_ltp(segment="CASH", exchange_trading_symbols=(f"NSE_{PAIR_A}", f"NSE_{PAIR_B}"))
    pa = float(resp.get(f"NSE_{PAIR_A}", 0))
    pb = float(resp.get(f"NSE_{PAIR_B}", 0))
    if pa <= MIN_PRICE or pa > MAX_PRICE or pb <= MIN_PRICE or pb > MAX_PRICE:
        raise ValueError(f"price out of range pa={pa} pb={pb}")
    return pa, pb


def main():
    log(f"=== LIVE indicator: {PAIR_A} vs {PAIR_B}  side={SIDE}  refresh={REFRESH_SECS}s  window={WINDOW} ===")

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
    state = "FLAT"          # FLAT | LONG | SHORT
    entry = None
    z = 0.0
    spread = 0.0
    ticks = 0

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

            # ---- signals ----
            if state == "FLAT":
                if SIDE in ("BOTH", "SHORT") and z > ENTRY_Z:
                    state = "SHORT"
                    entry = {"z": z, "pa": pa, "pb": pb, "at": datetime.now(IST).strftime("%H:%M:%S")}
                    alert(f"ENTER SHORT  z={z:+.2f}  -> SELL {PAIR_A} / BUY {PAIR_B}   "
                          f"qty~{max(int(CAPITAL/(pa+pb)),1)}")
                elif SIDE in ("BOTH", "LONG") and z < -ENTRY_Z:
                    state = "LONG"
                    entry = {"z": z, "pa": pa, "pb": pb, "at": datetime.now(IST).strftime("%H:%M:%S")}
                    alert(f"ENTER LONG  z={z:+.2f}  -> BUY {PAIR_A} / SELL {PAIR_B}   "
                          f"qty~{max(int(CAPITAL/(pa+pb)),1)}")
            elif state == "LONG" and z >= 0.0:
                alert(f"EXIT LONG  z={z:+.2f}  (entry z={entry['z']:+.2f} at {entry['at']})")
                state = "FLAT"
                entry = None
            elif state == "SHORT" and z <= 0.0:
                alert(f"EXIT SHORT  z={z:+.2f}  (entry z={entry['z']:+.2f} at {entry['at']})")
                state = "FLAT"
                entry = None

        # ---- dashboard ----
        os.system("")  # enable ANSI
        print("\033[H\033[J", end="", flush=True)
        print(f"=== LIVE {PAIR_A} vs {PAIR_B}  [{datetime.now(IST).strftime('%H:%M:%S')}]  "
              f"refresh={REFRESH_SECS}s window={WINDOW} ===")
        print(f"BANKBEES={pa:.2f}  SETFNIFBK={pb:.2f}  spread(ln)={spread:.6f}  z={z:+.2f}")
        print(f"state: {state}" + (f"  (entry z={entry['z']:+.2f} @ {entry['at']})" if entry else ""))
        print(f"qty suggestion (₹{CAPITAL:,.0f}): {max(int(CAPITAL/(pa+pb)),1)}  "
              f"ticks={ticks}  hist={len(history)}")
        hint = ("ENTER SHORT when z>+2 | ENTER LONG when z<-2 | exit at z=0"
                if state == "FLAT" else f"WAITING to EXIT {state} (z should cross 0)")
        print(f"[{hint}]")

        time.sleep(REFRESH_SECS)


if __name__ == "__main__":
    main()
