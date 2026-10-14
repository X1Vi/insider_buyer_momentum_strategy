"""Reaction app server — pushes the FINAL UNTOUCHED TEST window (candles + z)
once over a WebSocket, then returns a fresh WATCH-scan for ANY bar you seek to.
You move the cursor back and forth (slow / day-by-day) and the scanner
re-predicts at every position. Paper BUY/SELL with a stop-loss. No real orders.

Run:  .venv/bin/python -m reaction.server   then open http://127.0.0.1:8080
"""
import asyncio
import json
import os
import glob

import pandas as pd
from aiohttp import web

from reaction import scanner as S

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "backtesting", "data")
MODEL_PATH = os.path.join(ROOT, "backtesting", "model_dump.txt")
PRED_PATH = os.path.join(ROOT, "backtesting", "model_backtests", "xgboost", "predictions.csv")
INDEX = os.path.join(HERE, "index.html")

CAPITAL = 20000.0
STOP_NOTIONAL_PCT = 0.05

_trees = None
_names = None
_data = None
_vol = None
_name_index = {}
_test_start = None
_pairs = None
_zcache = {}


def load_all():
    global _trees, _names, _data, _vol, _name_index, _test_start, _pairs
    _trees = S.parse_model(MODEL_PATH)
    files = sorted(glob.glob(os.path.join(DATA, "*.csv")))
    _names = [os.path.basename(f)[:-4] for f in files]
    _data = {nm: pd.read_csv(f)["close"].values.astype(float) for nm, f in zip(_names, files)}
    _vol = {nm: pd.read_csv(f)["volume"].values.astype(float) for nm, f in zip(_names, files)}
    _name_index = {nm: i for i, nm in enumerate(_names)}
    # FINAL UNTOUCHED TEST split: newest 20% of events (test==True) -> min arm = test start
    pred = pd.read_csv(PRED_PATH)
    test = pred[pred["test"] == True]  # noqa: E712
    _test_start = int(test["arm"].min())
    # unique (leg, partner) pairs that have out-of-sample (test) events
    _pairs = sorted(set(zip(test["leg"], test["partner"])), key=lambda x: (x[0], x[1]))


def pair_z(leg, partner):
    key = (leg, partner)
    if key not in _zcache:
        pa, pb = _data[leg], _data[partner]
        n = min(len(pa), len(pb))
        z, beta = S.rbz(pa[:n], pb[:n])
        _zcache[key] = (pa[:n], pb[:n], z, beta)
    return _zcache[key]


# ----------------------------- trade sim -----------------------------

def open_trade(pa, pb, z, i, side):
    q = max(int(CAPITAL / (pa[i] + pb[i])), 1)
    return {"side": side, "qty": q, "pa0": float(pa[i]), "pb0": float(pb[i]),
            "entry_i": i, "z0": float(z[i]), "pnl": 0.0}


def trade_pnl(pos, pa, pb, i):
    q = pos["qty"]
    if pos["side"] == "BUY":      # long leg / short partner
        return (pa[i] - pos["pa0"]) * q - (pb[i] - pos["pb0"]) * q
    return (pos["pa0"] - pa[i]) * q - (pos["pb0"] - pb[i]) * q


def check_exit(pos, pa, pb, z, i, stop_pct):
    """Return (closed, reason) for a stop-loss or mean-reversion completion."""
    q = pos["qty"]
    stop = -(stop_pct / 100.0) * (pos["pa0"] + pos["pb0"]) * q
    pnl = trade_pnl(pos, pa, pb, i)
    if pnl <= stop:
        return True, "STOP"
    if pos["side"] == "BUY" and pos["z0"] < 0 and z[i] >= 0:
        return True, "ZERO"
    if pos["side"] == "SELL" and pos["z0"] > 0 and z[i] <= 0:
        return True, "ZERO"
    return False, None


# ----------------------------- websocket -----------------------------

def window(leg, partner):
    """Build the full test-window candle series + z + per-bar WATCH probabilities."""
    pa, pb, z, beta = pair_z(leg, partner)
    n = len(pa)
    start = min(_test_start, n - S.OBS - 1)
    ts = pd.read_csv(os.path.join(DATA, f"{leg}.csv"))["ts"].values
    vol = _vol[leg]
    ohlc, prev_c = [], None
    for k in range(start, n):
        c = float(pa[k])
        o = prev_c if prev_c is not None else c
        ohlc.append({"i": k, "ts": str(ts[k]), "o": o, "h": max(o, c),
                     "l": min(o, c), "c": c, "v": float(vol[k])})
        prev_c = c
    zser = [float(v) for v in z[start:n]]
    pbwin = [float(v) for v in pb[start:n]]
    # pre-scan every bar so the chart can shade where WATCH fired historically
    leg_id = _name_index[leg]
    watches, probs = [], []
    for k in range(start, n):
        sc = S.scan(pa, pb, z, beta, _trees, leg_id, k + 1)
        probs.append(sc["prob"])
        if sc["watch"]:
            watches.append({"i": k, "prob": sc["prob"], "arm": sc["arm"]})
    return {"leg": leg, "partner": partner, "leg_id": leg_id, "test_start": int(start),
            "total": int(n), "ohlc": ohlc, "z": zser, "pb": pbwin,
            "watches": watches, "probs": probs}


async def ws_handler(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    st = {"win": None, "i": None, "pos": None, "realized": 0.0,
          "trades": [], "stop_pct": STOP_NOTIONAL_PCT * 100.0}

    async def scan_at(i):
        w = st["win"]
        pa, pb, z, beta = pair_z(w["leg"], w["partner"])
        sc = S.scan(pa, pb, z, beta, _trees, w["leg_id"], i + 1)
        closed = None
        if st["pos"]:
            done, reason = check_exit(st["pos"], pa, pb, z, i, st["stop_pct"])
            if done:
                pnl = trade_pnl(st["pos"], pa, pb, i)
                st["realized"] += pnl
                closed = {"status": "closed", "side": st["pos"]["side"],
                          "entry_i": st["pos"]["entry_i"], "exit_i": i, "pnl": pnl,
                          "reason": reason, "realized": st["realized"]}
                st["trades"].append({"side": st["pos"]["side"], "entry_i": st["pos"]["entry_i"],
                                     "exit_i": i, "pnl": pnl, "reason": reason})
                st["pos"] = None
        upnl = 0.0
        if st["pos"]:
            upnl = trade_pnl(st["pos"], pa, pb, i)
            st["pos"]["pnl"] = upnl
        return sc, closed, upnl

    try:
        # wait for start
        data = None
        while True:
            try:
                msg = await asyncio.wait_for(ws.receive(), 30.0)
            except asyncio.TimeoutError:
                continue
            except (RuntimeError, ConnectionResetError, asyncio.CancelledError):
                return ws
            if msg.type == web.WSMsgType.TEXT:
                data = json.loads(msg.data)
                if data.get("type") == "start":
                    break
            elif msg.type in (web.WSMsgType.CLOSE, web.WSMsgType.ERROR):
                return ws

        leg, partner = data.get("leg"), data.get("partner")
        if leg not in _data or partner not in _data:
            await ws.send_json({"type": "error", "msg": "unknown pair"})
            return ws
        w = window(leg, partner)
        st["win"], st["i"] = w, w["test_start"]
        await ws.send_json({"type": "init", **w, "stop_pct": st["stop_pct"]})

        while True:
            try:
                msg = await asyncio.wait_for(ws.receive(), 60.0)
            except asyncio.TimeoutError:
                continue
            except (RuntimeError, ConnectionResetError, asyncio.CancelledError):
                break
            if msg.type != web.WSMsgType.TEXT:
                if msg.type in (web.WSMsgType.CLOSE, web.WSMsgType.ERROR):
                    break
                continue
            data = json.loads(msg.data)
            t = data.get("type")
            w = st["win"]
            if t == "scan":
                i = max(w["test_start"], min(int(data.get("i", st["i"])), w["total"] - 1))
                st["i"] = i
                sc, closed, upnl = await scan_at(i)
                reply = {"type": "scan", "i": i, "watch": sc["watch"], "prob": sc["prob"],
                         "arm": sc["arm"], "z_now": sc["z_now"], "z_sig": sc["z_sig"],
                         "zrec": sc["zrec"], "pxdist": sc["pxdist"],
                         "upnl": upnl, "realized": st["realized"],
                         "pos": st["pos"] if st["pos"] else None}
                if closed:
                    reply["closed"] = closed
                await ws.send_json(reply)
                if closed:
                    await ws.send_json(closed)
            elif t == "buy" or t == "sell":
                pa, pb, z, _ = pair_z(w["leg"], w["partner"])
                i = st["i"]
                if st["pos"]:
                    await ws.send_json({"type": "trade", "status": "rejected", "reason": "already_open"})
                elif i >= w["total"] - 1:
                    await ws.send_json({"type": "trade", "status": "rejected", "reason": "end_of_data"})
                else:
                    st["pos"] = open_trade(pa, pb, z, i, t)
                    await ws.send_json({"type": "trade", "status": "open", "side": t,
                                        "qty": st["pos"]["qty"], "pa0": st["pos"]["pa0"],
                                        "pb0": st["pos"]["pb0"], "entry_i": st["pos"]["entry_i"]})
            elif t == "close":
                if st["pos"]:
                    pa, pb, _, _ = pair_z(w["leg"], w["partner"])
                    i = st["i"]
                    pnl = trade_pnl(st["pos"], pa, pb, i)
                    st["realized"] += pnl
                    st["trades"].append({"side": st["pos"]["side"], "entry_i": st["pos"]["entry_i"],
                                         "exit_i": i, "pnl": pnl, "reason": "MANUAL"})
                    await ws.send_json({"type": "trade", "status": "closed",
                                        "side": st["pos"]["side"], "entry_i": st["pos"]["entry_i"],
                                        "exit_i": i, "pnl": pnl, "reason": "MANUAL",
                                        "realized": st["realized"]})
                    st["pos"] = None
            elif t == "stop":
                st["stop_pct"] = max(0.5, min(100.0, float(data.get("value", st["stop_pct"]))))
                await ws.send_json({"type": "stop", "value": st["stop_pct"]})
            elif t == "reset":
                st["i"] = w["test_start"]
                st["pos"] = None
                st["realized"] = 0.0
                st["trades"] = []
                await ws.send_json({"type": "reset", "realized": 0.0})
            elif t == "quit":
                break
    finally:
        await ws.close()
    return ws


# ----------------------------- http -----------------------------

async def index(request):
    with open(INDEX, encoding="utf-8") as fh:
        return web.Response(text=fh.read(), content_type="text/html")


async def api_pairs(request):
    return web.json_response({
        "pairs": [{"leg": l, "partner": p} for l, p in _pairs],
        "test_start": _test_start,
        "symbols": _names,
        "default": {"leg": _pairs[0][0], "partner": _pairs[0][1]} if _pairs else None,
    })


def main():
    load_all()
    print(f"loaded {len(_names)} symbols, {len(_trees)} trees, test_start arm={_test_start}, "
          f"{len(_pairs)} test pairs")
    app = web.Application()
    app.router.add_get("/", index)
    app.router.add_get("/api/pairs", api_pairs)
    app.router.add_get("/ws", ws_handler)
    web.run_app(app, host="127.0.0.1", port=8080)


if __name__ == "__main__":
    main()
