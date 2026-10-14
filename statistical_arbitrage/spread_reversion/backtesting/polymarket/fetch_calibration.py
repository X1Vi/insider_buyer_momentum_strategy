"""
Polymarket calibration dataset.

THE BINDING CONSTRAINT, verified 17 Sep 2026: the CLOB /prices-history endpoint
serves a price series only for markets closed in roughly the last SIX WEEKS.
Everything older returns an empty series — including the $1.5bn Trump-2024 market —
under interval=max, interval=1m and explicit startTs/endTs alike. Gamma still lists
25,361 resolved binaries with >=$25k volume back to 2020, but their prices are gone.

So the sample is the retrievable window, not the resolved population, and a long
calibration history can only be built by RECORDING FORWARD. That is what the
recorder is for, and it is why it being down matters.

Sampling design
---------------
Gamma caps `limit` at 100 and fails on deep `offset`, so the population is walked
in MONTHLY windows via end_date_min/end_date_max, filtered by volume (a price with
no volume behind it is not a forecast). Stage 2 then keeps only the window where
price history actually exists.

Output
------
  pm_markets.jsonl  one row per resolved binary market: question, outcome, volume,
                    category, event slug, and the hourly YES-price history.
"""
import json, urllib.request, urllib.error, ast, time, os, sys
from datetime import datetime, timedelta, timezone

OUT_DIR = os.path.dirname(os.path.abspath(__file__))
UA = {'User-Agent': 'quant-research/1.0'}
VOL_MIN = 25_000          # a price with no volume behind it is not a forecast
START = datetime(2021, 1, 1, tzinfo=timezone.utc)
END = datetime(2026, 9, 18, tzinfo=timezone.utc)


def get(url, tries=4):
    for k in range(tries):
        try:
            r = urllib.request.Request(url, headers=UA)
            return json.load(urllib.request.urlopen(r, timeout=45))
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(2 * (k + 1)); continue
            return None
        except Exception:
            time.sleep(1.5 * (k + 1))
    return None


def months(a, b):
    cur = a
    while cur < b:
        nxt = (cur.replace(day=1) + timedelta(days=32)).replace(day=1)
        yield cur, min(nxt, b)
        cur = nxt


def outcome(m):
    """1 if YES resolved true, 0 if false, None if void/ambiguous/non-binary."""
    try:
        op = ast.literal_eval(m.get('outcomePrices') or '[]')
        oc = ast.literal_eval(m.get('outcomes') or '[]')
    except Exception:
        return None
    if len(op) != 2 or len(oc) != 2:
        return None
    if [o.lower() for o in oc] != ['yes', 'no']:
        return None
    a, b = float(op[0]), float(op[1])
    return int(a == 1.0) if {a, b} == {1.0, 0.0} else None


# ---------- stage 1: metadata, walked in monthly windows ----------
META = f'{OUT_DIR}/pm_meta.json'
if not os.path.exists(META):
    seen, mk = set(), []
    for a, b in months(START, END):
        got = 0
        for off in range(0, 1200, 100):
            u = ('https://gamma-api.polymarket.com/markets?closed=true&limit=100'
                 f'&offset={off}&volume_num_min={VOL_MIN}'
                 f"&end_date_min={a.strftime('%Y-%m-%dT%H:%M:%SZ')}"
                 f"&end_date_max={b.strftime('%Y-%m-%dT%H:%M:%SZ')}")
            d = get(u)
            if not d:
                break
            for m in d:
                if m.get('id') not in seen:
                    seen.add(m.get('id')); mk.append(m); got += 1
            if len(d) < 100:
                break
            time.sleep(0.2)
        print(f"  {a:%Y-%m}  +{got:>4}  total {len(mk)}", flush=True)
    json.dump(mk, open(META, 'w'))
mk = json.load(open(META))
print(f'markets in window sweep: {len(mk)}', flush=True)

rows = []
for m in mk:
    y = outcome(m)
    if y is None:
        continue
    try:
        toks = ast.literal_eval(m['clobTokenIds'])
    except Exception:
        continue
    if len(toks) != 2:
        continue
    ev = (m.get('events') or [{}])
    rows.append(dict(
        id=m.get('id'), q=(m.get('question') or '')[:200], tok=toks[0], y=y,
        vol=float(m.get('volumeNum') or 0), liq=float(m.get('liquidityNum') or 0),
        cat=(m.get('category') or ''),
        slug=(ev[0].get('slug') if ev else '') or '',
        event=(ev[0].get('title') if ev else '') or '',
        closed=(m.get('closedTime') or m.get('endDate') or ''),
        created=(m.get('createdAt') or '')))
print(f'clean resolved binaries, >=${VOL_MIN:,} volume: {len(rows)}', flush=True)
print(f'  base rate (YES resolves true): {sum(r["y"] for r in rows)/max(len(rows),1):.3f}',
      flush=True)

# ---------- stage 2: price history ----------
OUT = f'{OUT_DIR}/pm_markets.jsonl'
done = set()
if os.path.exists(OUT):
    for line in open(OUT):
        try:
            done.add(json.loads(line)['id'])
        except Exception:
            pass
# CLOB /prices-history only serves markets closed in roughly the last six weeks.
# Verified 17 Sep 2026: the $1.5bn Trump-2024 market returns an empty series, and so
# does everything before 2026-08, under interval=max, interval=1m and explicit
# startTs/endTs. So the retrievable window - not the resolved population - is the
# sample. Everything older needs a recorder, which is what yesterday's note said.
HIST_FROM = '2026-08-01'
rows = [r for r in rows if (r.get('closed') or '') >= HIST_FROM]
rows.sort(key=lambda r: (r.get('closed') or ''), reverse=True)
print(f'retrievable window (closed >= {HIST_FROM}): {len(rows)} markets', flush=True)
todo = [r for r in rows if r['id'] not in done]
print(f'have {len(done)}, fetching {len(todo)}', flush=True)

with open(OUT, 'a') as f:
    for i, r in enumerate(todo):
        h = get('https://clob.polymarket.com/prices-history'
                f"?market={r['tok']}&interval=max&fidelity=60")
        hist = (h or {}).get('history') or []
        if hist:
            rec = dict(r)
            rec['hist'] = [[p['t'], round(float(p['p']), 4)] for p in hist]
            f.write(json.dumps(rec) + '\n')
        if i % 200 == 0:
            f.flush()
            print(f'  {i}/{len(todo)}', flush=True)
        time.sleep(0.1)
print('done', flush=True)
