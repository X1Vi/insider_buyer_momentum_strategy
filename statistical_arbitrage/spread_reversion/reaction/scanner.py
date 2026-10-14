"""WATCH scanner ported from src/bin/scanner.rs (model_dump.txt XGBoost trees).

This is the exact logic the live scanner runs: rolling beta + z-score of the
spread, then the ML v3 WATCH feature vector -> XGBoost probability -> WATCH gate.
Only used for the out-of-sample (test) replay; the model was trained on earlier
events, so signals here are genuinely unseen data.
"""
import math
import numpy as np
import pandas as pd

W_BETA, W_Z, Z_ARM, OBS = 252, 60, -3.0, 10
GATE_ZREC, GATE_PX = 0.5, 0.02
THRESH = 0.5
BASE_SCORE = -0.29783444391579905  # logit(T2 mean 0.426086) — XGBoost auto base_score
MODEL_PATH = "backtesting/model_dump.txt"


# ----------------------------- model -----------------------------

def parse_tail_int(tail, key):
    p = tail.find(key)
    if p < 0:
        return 0
    s = tail[p + len(key):]
    d = ""
    for ch in s:
        if ch.isdigit():
            d += ch
        else:
            break
    return int(d) if d else 0


def parse_model(path):
    """Parse XGBoost text dump into a list of trees. Each node is a tuple:
    ('leaf', value) or ('split', feature, threshold, yes_id, no_id)."""
    trees = []
    nodes = []
    with open(path) as fh:
        for raw in fh:
            body = raw.strip()
            if body.startswith("booster["):
                if nodes:
                    nodes.sort(key=lambda x: x[0])
                    trees.append([n for _, n in nodes])
                    nodes = []
                continue
            if not body or ":" not in body:
                continue
            id_s, rest = body.split(":", 1)
            try:
                nid = int(id_s.strip())
            except ValueError:
                continue
            rest = rest.strip()
            if rest.startswith("leaf="):
                try:
                    leaf = float(rest[5:].strip())
                except ValueError:
                    continue
                nodes.append((nid, ("leaf", leaf)))
            else:
                inner = rest.split("]")[0]
                inner = inner.lstrip("[").lstrip("f")
                try:
                    fs, ts = inner.split("<")
                    feat = int(fs.strip())
                    thr = float(ts.strip())
                except ValueError:
                    continue
                tail = rest.split("]")[1] if "]" in rest else ""
                yes = parse_tail_int(tail, "yes=")
                no = parse_tail_int(tail, "no=")
                nodes.append((nid, ("split", feat, thr, yes, no)))
    if nodes:
        nodes.sort(key=lambda x: x[0])
        trees.append([n for _, n in nodes])
    return trees


def predict(feats, trees):
    margin = BASE_SCORE
    for t in trees:
        idx = 0
        while True:
            nd = t[idx]
            if nd[0] == "leaf":
                margin += nd[1]
                break
            _, feat, thr, yes, no = nd
            idx = yes if np.float32(feats[feat]) < np.float32(thr) else no
    return 1.0 / (1.0 + math.exp(-margin))


# ----------------------------- z-score -----------------------------

def rbz(pa, pb):
    """Rolling hedge-ratio regression + z-score of the spread (matches pipeline.py)."""
    sla = pd.Series(np.log(pa))
    slb = pd.Series(np.log(pb))
    beta = (sla.rolling(W_BETA).cov(slb) / slb.rolling(W_BETA).var()).values
    alpha = (sla.rolling(W_BETA).mean() - pd.Series(beta) * slb.rolling(W_BETA).mean()).values
    spread = (sla - pd.Series(beta) * slb - pd.Series(alpha)).values
    mu = pd.Series(spread).rolling(W_Z).mean().values
    sd = pd.Series(spread).rolling(W_Z).std().values
    z = np.where(sd > 1e-9, (spread - mu) / np.maximum(sd, 1e-9), 0.0)
    z[:W_BETA + W_Z] = 0.0
    return z, beta


# ----------------------------- signal -----------------------------

def std_pop(v):
    v = np.asarray(v, dtype=float)
    if v.size == 0:
        return 0.0
    return float(np.sqrt(np.mean((v - v.mean()) ** 2)))


def std_of_diffs(logs):
    logs = np.asarray(logs, dtype=float)
    if logs.size < 2:
        return 0.0
    d = np.diff(logs)
    return std_pop(d)


def scan(pa, pb, z, beta, trees, leg_id, n):
    """Run the WATCH scan using the first n bars. z/beta are precomputed full-series
    arrays; only indices < n are used (no lookahead)."""
    out = {"z_now": 0.0, "z_sig": 0.0, "zrec": 0.0, "pxdist": 0.0,
           "prob": 0.0, "watch": False, "arm": None, "live_arm": False}
    if n < W_BETA + W_Z + OBS:
        return out
    arm = None
    for i in range(W_BETA + W_Z, max(W_BETA + W_Z, n - OBS)):
        if z[i] < Z_ARM:
            arm = i   # keep overwriting -> ends at the true latest arm
    if arm is None:
        return out
    a = arm
    e = a + OBS
    segz = z[a:e + 1]
    segp = pa[a:e + 1]
    zm = float(np.min(segz))
    dzm = int(np.argmin(segz))
    pmin = float(np.min(segp))
    dpm = int(np.argmin(segp))
    zrec = z[e] - zm
    pxdist = pa[e] / pmin - 1.0
    out["z_now"] = z[n - 1] if n >= W_BETA + W_Z else 0.0
    out["live_arm"] = out["z_now"] < Z_ARM
    out["z_sig"] = z[e]
    if not (zrec >= max(GATE_ZREC, 0.3 * abs(zm)) and pxdist <= GATE_PX):
        out["zrec"] = zrec
        out["pxdist"] = pxdist
        return out
    logs_a = np.log(pa[:n])
    vf = std_of_diffs(logs_a[a:a + 6])
    vl = std_of_diffs(logs_a[e - 5:e + 1])
    feats = [z[a], z[e], zm, zrec, zrec / max(dzm, 1), dzm,
             (z[e] - z[a]) / OBS, z[e] - z[e - 2], pxdist,
             pa[e] / pa[a] - 1, pa[e] / pa[e - 2] - 1,
             pa[e] / pa[e - 3] - 1, pa[e] / pa[e - 5] - 1, dpm,
             max(0.0, zrec) * max(0.0, pa[a] / pmin - 1),
             (z[e] - segz[dzm]) / max(OBS - dzm, 1),
             (pa[e] - segp[dpm]) / max(OBS - dpm, 1) / max(pmin, 1e-9),
             zrec / max(pxdist, 1e-4), abs(zm),
             vl / max(vf, 1e-9), std_pop(logs_a[max(0, e - 19):e + 1]),
             beta[e], leg_id]
    prob = predict(feats, trees)
    out["zrec"] = zrec
    out["pxdist"] = pxdist
    out["prob"] = prob
    out["watch"] = prob >= THRESH
    out["arm"] = a
    return out


def leg_id_of(name, leg_cfgs):
    for k, c in enumerate(leg_cfgs):
        if c[0] == name:
            return float(c[1])
    return 0.0
