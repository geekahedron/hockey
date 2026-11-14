"""Phase-3 feature test: do HCH-style data points add anything?
Variants: base (current model) | +role (PP1/PP2/top-line proxies from NHL TOI ranks = HCH line/ppLine analogue)
| +raw (HCH raw season stats: goals/GP, shots/GP, S%) | +role+raw.
Validation: train 2024-25 -> test 2025-26 (all skater-games). Backtest: fit 2024+2025 -> real Tims groups Oct 2-Nov 1 2026."""
import json, numpy as np, pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.metrics import log_loss, roc_auc_score
import features as F
from train_utils import X as X0
A='/workspace/tims-analysis'
def raw(df):
    df=df.copy(); gp=df.cur_gp.clip(1)
    df['gpg_raw']=df.cur_g/gp; df['spg_raw']=df.cur_sog/gp; df['spct_raw']=df.cur_g/df.cur_sog.clip(1)
    return df
VAR={'base':[], 'role':F.ROLE, 'raw':['gpg_raw','spg_raw','spct_raw'], 'role+raw':F.ROLE+['gpg_raw','spg_raw','spct_raw']}
def X(df,extra):
    x=X0(df)
    for c in extra: x[c]=df[c].values
    return x
def mk(): return make_pipeline(StandardScaler(),LogisticRegression(C=0.5,max_iter=2000))
d=raw(pd.read_csv('data/skater_games_features.csv.gz'))
tr,va,full=d[d.season==2024],d[d.season==2025],d[d.season.isin([2024,2025])]
# group players for backtest (features rebuilt with role proxies)
sk,tg,gk=F.load(); fb=F.FeatureBuilder(sk,tg,gk)
rows=json.load(open(f'{A}/hch_rows.json'))
home={(r.team,r.date):r.home for r in tg[tg.season==2026].itertuples()}
teams={}
for r in rows:
    if r['date'] not in teams:
        h=json.load(open(f"{A}/hch_history/{r['date']}.json"))
        teams[r['date']]={p['nhlPlayerId']:(p['team'],p['opponent']) for L in h['playerLists'] for p in L['players']}
out=[]
for r in rows:
    if not ('2026-10-02'<=r['date']<='2026-11-01'): continue
    t,o=teams[r['date']][r['pid']]
    f=fb.build(r['pid'],t,o,home.get((t,r['date']),0),r['date'],2026)
    f.update(date=r['date'],group=r['group'],name=r['player'],scored=int(r['scored']),pid=r['pid'])
    out.append(f)
G=raw(pd.DataFrame(out))
keys=list(G.groupby(['date','group']).groups)
def pairs(df,col):
    out={}
    for k,gr in df.groupby(['date','group']):
        s=gr[gr.scored==1][col].values; n=gr[gr.scored==0][col].values
        if len(s) and len(n): out[k]=((s[:,None]>n[None,:]).sum()+0.5*(s[:,None]==n[None,:]).sum(), len(s)*len(n))
    return out
def top1(df,col):
    return {k:gr[gr[col]==gr[col].max()].scored.mean() for k,gr in df.groupby(['date','group'])}
res={}; PR={}; T1={}
for v,ex in VAR.items():
    m=mk().fit(X(tr,ex),tr.scored); p=m.predict_proba(X(va,ex))[:,1]
    mf=mk().fit(X(full,ex),full.scored); G['p_'+v]=mf.predict_proba(X(G,ex))[:,1]
    PR[v]=pairs(G,'p_'+v); T1[v]=top1(G,'p_'+v)
    pw=sum(a for a,b in PR[v].values())/sum(b for a,b in PR[v].values())
    res[v]=dict(val_logloss=round(log_loss(va.scored,p),5),val_auc=round(roc_auc_score(va.scored,p),4),
                bt_pairwise=round(pw,4),bt_top1=round(sum(T1[v].values()),2),n_groupdays=len(T1[v]),
                coefs={c:round(float(w),3) for c,w in zip(X(full,ex).columns,mf[-1].coef_[0]) if c in ex})
# bootstrap paired differences vs base over group-days
rng=np.random.default_rng(0); K=list(PR['base'])
for v in VAR:
    if v=='base': continue
    dp=[];dt=[]
    for _ in range(2000):
        s=[K[i] for i in rng.integers(0,len(K),len(K))]
        a=sum(PR[v][k][0] for k in s)/sum(PR[v][k][1] for k in s); b=sum(PR['base'][k][0] for k in s)/sum(PR['base'][k][1] for k in s)
        dp.append(a-b)
        s2=[keys[i] for i in rng.integers(0,len(keys),len(keys))]
        dt.append(sum(T1[v][k]-T1['base'][k] for k in s2))
    res[v]['bt_pairwise_diff_ci95']=[round(float(np.percentile(dp,q)),4) for q in (2.5,50,97.5)]
    res[v]['bt_top1_diff_ci95']=[round(float(np.percentile(dt,q)),2) for q in (2.5,50,97.5)]
print(json.dumps(res,indent=1))
json.dump(res,open('data/feature_test_hch_fields.json','w'),indent=1)
G.to_csv('data/feature_test_group_players.csv',index=False)
