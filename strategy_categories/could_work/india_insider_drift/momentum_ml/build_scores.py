#!/usr/bin/env python3
"""Train a cross-sectional momentum-onset model and publish latest scores.

Target: next-open -> close after 20 sessions is >= +8%.
Features are price/volume/market-state only (no insider features), because the
prior MANINFRA test showed insider features did not improve OOS ranking.

Usage:
  python momentum_ml/build_scores.py
Outputs:
  momentum_ml/model.pkl
  momentum_ml/scores.csv
  web/public/momentum_ml_scores.json
"""
from __future__ import annotations
import glob, json, pickle, re, warnings
from datetime import datetime, timezone
from pathlib import Path
import numpy as np, pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.metrics import roc_auc_score
warnings.filterwarnings('ignore')

APP=Path(__file__).resolve().parents[1]
CACHE=APP/'data/app_cache'
NIFTY=Path(__file__).resolve().parent/'data/nifty.csv'
PUB=APP/'web/public/momentum_ml_scores.json'
TARGET=0.08; H=20; SEED=42; DIR_THRESHOLD=0.40

def longest_price(sym):
    fs=glob.glob(str(CACHE/f'price_{sym}_*y.json'))
    if not fs: return None
    fs.sort(key=lambda p:int(re.search(r'_(\d+)y\.json$',p).group(1)))
    for f in reversed(fs):
        try:
            obj=json.load(open(f))
            bars=obj.get('bars') or []
            if len(bars)>=280: return bars
        except Exception: pass
    return None

def features(df):
    c=df.close; o=df.open; h=df.high; l=df.low; v=df.volume.replace(0,np.nan)
    r=c.pct_change(); F=pd.DataFrame(index=df.index)
    F['close']=c
    for n in [1,3,5,10,20,60,120,250]: F[f'r{n}']=c/c.shift(n)-1
    F['vol20']=r.rolling(20).std(); F['vol60']=r.rolling(60).std(); F['vol_ratio']=F.vol20/F.vol60
    F['atr14']=(h-l).rolling(14).mean()/c
    for n in [20,50,200]:
        ma=c.rolling(n).mean(); F[f'dist_sma{n}']=c/ma-1; F[f'sma{n}_slope']=ma/ma.shift(5)-1
    def rsi(s,n=14):
        d=s.diff(); up=d.clip(lower=0).ewm(alpha=1/n,adjust=False).mean(); dn=(-d.clip(upper=0)).ewm(alpha=1/n,adjust=False).mean()
        return 100-100/(1+up/dn.replace(0,np.nan))
    F['rsi14']=rsi(c); F['rsi2']=rsi(c,2)
    F['dd60']=c/c.rolling(60).max()-1; F['dd250']=c/c.rolling(250).max()-1
    F['dist_hi20']=c/h.rolling(20).max()-1; F['dist_hi60']=c/h.rolling(60).max()-1; F['dist_hi250']=c/h.rolling(250).max()-1
    F['range20']=(h.rolling(20).max()-l.rolling(20).min())/c; F['range60']=(h.rolling(60).max()-l.rolling(60).min())/c
    F['up20']=(r>0).rolling(20).mean(); F['gap']=o/c.shift(1)-1; F['intraday']=c/o-1
    F['vol5_20']=v.rolling(5).mean()/v.rolling(20).mean(); F['vol20_60']=v.rolling(20).mean()/v.rolling(60).mean(); F['log_volume']=np.log1p(v)
    return F

def main():
    syms=sorted({re.sub(r'^price_|_\d+y\.json$','',Path(f).name) for f in glob.glob(str(CACHE/'price_*.json'))})
    nif=pd.read_csv(NIFTY,parse_dates=['date']).set_index('date').sort_index()
    nif=nif[~nif.index.duplicated()]; nc=nif.close; nr=nc.pct_change()
    frames=[]; used=[]
    for sym in syms:
        bars=longest_price(sym)
        if not bars: continue
        df=pd.DataFrame(bars)
        df['date']=pd.to_datetime(df['date'],errors='coerce'); df=df.dropna(subset=['date']).set_index('date').sort_index()
        for col in ['open','high','low','close','volume']:
            df[col]=pd.to_numeric(df[col],errors='coerce')
        df=df.dropna(subset=['open','high','low','close']); df=df[df.close>0]
        if len(df)<300: continue
        F=features(df)
        F['mkt_r1']=nr.reindex(F.index,method='ffill'); F['mkt_r5']=nc.reindex(F.index,method='ffill')/nc.reindex(F.index,method='ffill').shift(5)-1
        F['mkt_r20']=nc.reindex(F.index,method='ffill')/nc.reindex(F.index,method='ffill').shift(20)-1
        F['mkt_r60']=nc.reindex(F.index,method='ffill')/nc.reindex(F.index,method='ffill').shift(60)-1
        ncr=nc.reindex(F.index,method='ffill'); F['mkt_above200']=(ncr>ncr.rolling(200).mean()).astype(float); F['mkt_dist200']=ncr/ncr.rolling(200).mean()-1
        o=df.open; c=df.close
        fwd=np.full(len(df),np.nan); fwd2=np.full(len(df),np.nan)
        for i in range(len(df)-H-1):
            entry=o.iloc[i+1]; fwd[i]=c.iloc[i+H]/entry-1
            fwd2[i]=c.iloc[i+1:i+1+H].max()/entry-1
        F['fwd20']=fwd; F['fwd_max20']=fwd2
        F['y']=(fwd>=TARGET).astype(float); F['y_down']=(fwd<=-TARGET).astype(float)
        F.loc[~np.isfinite(fwd),['y','y_down']]=np.nan
        F['symbol']=sym; F['date']=F.index
        frames.append(F.reset_index(drop=True)); used.append(sym)
    P=pd.concat(frames,ignore_index=True)
    # Cross-sectional percentile ranks (the model can learn relative strength).
    for col in ['r20','r60','vol20','dist_hi250']:
        P[f'xs_{col}']=P.groupby('date')[col].rank(pct=True)
    feature_cols=[c for c in P.columns if c not in ('symbol','date','close','fwd20','fwd_max20','y','y_down')]
    print('symbols',len(used),'rows',len(P),
          'up base',round(P.y.mean()*100,2),'down base',round(P.y_down.mean()*100,2))
    def make(): return Pipeline([('imp',SimpleImputer(strategy='median')),('m',HistGradientBoostingClassifier(max_iter=350,learning_rate=.05,max_leaf_nodes=31,min_samples_leaf=100,l2_regularization=1.0,random_state=SEED))])
    train=P[P.date<'2025-01-01'].dropna(subset=['y','y_down'])
    test=P[P.date>='2025-01-01'].dropna(subset=['y','y_down']).copy()
    metrics={}
    for label,col in [('up','y'),('down','y_down')]:
        m=make().fit(train[feature_cols],train[col])
        pred=m.predict_proba(test[feature_cols])[:,1]
        auc=roc_auc_score(test[col],pred)
        test[f'pred_{label}']=pred
        daily=[]
        for _,g in test.groupby('date'):
            if len(g)>=5 and g[col].nunique()==2:
                daily.append(roc_auc_score(g[col],g[f'pred_{label}']))
        cs_auc=float(np.mean(daily)) if daily else float('nan')
        k=max(1,int(len(test)*.10)); idx=np.argsort(pred)[-k:]
        hit=float(test[col].iloc[idx].mean()); base_rate=float(test[col].mean())
        metrics[label]={'auc':float(auc),'cs_auc':cs_auc,'hit':hit,'base':base_rate,
                        'rows':len(test),'days':len(daily)}
        print(f'OOS {label}: rows {len(test)} base {base_rate*100:.2f}% AUC {auc:.3f} '
              f'daily-CS {cs_auc:.3f} ({len(daily)}d) top10 {hit*100:.2f}% '
              f'lift {hit/base_rate:.2f}')
    # Refit on all labelled rows for the latest cross-section.
    full=P.dropna(subset=['y','y_down'])
    model_up=make().fit(full[feature_cols],full.y)
    model_down=make().fit(full[feature_cols],full.y_down)
    latest=P.sort_values('date').groupby('symbol').tail(1).copy()
    latest['p_up']=model_up.predict_proba(latest[feature_cols])[:,1]
    latest['p_down']=model_down.predict_proba(latest[feature_cols])[:,1]
    latest['score']=latest.p_up
    latest['score_down']=latest.p_down
    latest['strength']=latest[['p_up','p_down']].max(axis=1)
    latest['direction']=np.select(
        [(latest.p_up>=DIR_THRESHOLD)&(latest.p_up>=latest.p_down),
         (latest.p_down>=DIR_THRESHOLD)&(latest.p_down>latest.p_up)],
        ['long','short'],default='neutral')
    out={}
    for _,r in latest.iterrows():
        out[r.symbol]={
            'symbol':r.symbol,'date':str(pd.Timestamp(r.date).date()),
            'direction':r.direction,'strength':round(float(r.strength),4),
            'p_up':round(float(r.p_up),4),'p_down':round(float(r.p_down),4),
            'score':round(float(r.p_up),4),'score_down':round(float(r.p_down),4),
            'close':round(float(r.close),3),'ret20':round(float(r.r20),4) if pd.notna(r.r20) else None,
            'ret60':round(float(r.r60),4) if pd.notna(r.r60) else None,
            'dist52w':round(float(r.dist_hi250),4) if pd.notna(r.dist_hi250) else None,
        }
    up,down=metrics['up'],metrics['down']
    payload={'generated_at':datetime.now(timezone.utc).isoformat(timespec='seconds'),
             'target':'20-session forward return >= +8% (long) or <= -8% (short) from next open',
             'target_up':'20-session forward return >= +8% from next open',
             'target_down':'20-session forward return <= -8% from next open',
             'model':'two HistGradientBoosting classifiers; cross-sectional panel; price/volume/market features',
             'direction_threshold':DIR_THRESHOLD,
             'symbols':len(used),'rows':int(len(P)),
             'oos_rows':int(up['rows']),'oos_days':int(up['days']),
             'oos_auc':round(up['auc'],3),'oos_cs_auc':round(up['cs_auc'],3),
             'oos_base_rate':round(up['base'],4),'oos_top10_hit':round(up['hit'],4),
             'oos_auc_up':round(up['auc'],3),'oos_cs_auc_up':round(up['cs_auc'],3),
             'oos_base_rate_up':round(up['base'],4),'oos_top10_hit_up':round(up['hit'],4),
             'oos_auc_down':round(down['auc'],3),'oos_cs_auc_down':round(down['cs_auc'],3),
             'oos_base_rate_down':round(down['base'],4),'oos_top10_hit_down':round(down['hit'],4),
             'direction_counts':latest.direction.value_counts().to_dict(),
             'scores':out}
    PUB.parent.mkdir(parents=True,exist_ok=True)
    PUB.write_text(json.dumps(payload,indent=2,sort_keys=True))
    frame=pd.DataFrame(out.values()).sort_values('strength',ascending=False)
    frame.to_csv(Path(__file__).resolve().parent/'scores.csv',index=False)
    with open(Path(__file__).resolve().parent/'model.pkl','wb') as f:
        pickle.dump({'model_up':model_up,'model_down':model_down,'features':feature_cols,
                     'target_up':TARGET,'target_down':-TARGET,
                     'direction_threshold':DIR_THRESHOLD},f)
    print('wrote',PUB)
    print('directions',payload['direction_counts'])
    print(frame.head(15).to_string(index=False))
    print('latest date counts',latest.date.dt.date.value_counts().head().to_dict())

if __name__=='__main__': main()
