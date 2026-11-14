"""Out-of-sample backtest on this season's real Tims pick groups (HCH history morning lists, Oct 2 - Nov 1 2026).
Models were trained on 2024-25 and 2025-26 only; features use only games before each date."""
import json, numpy as np, pandas as pd, joblib, random
from features import load, FeatureBuilder
from train_utils import X
A='/workspace/tims-analysis'
sk,tg,gk=load(); fb=FeatureBuilder(sk,tg,gk)
M=joblib.load('data/models.joblib')
rows=json.load(open(f'{A}/hch_rows.json'))
home={(r.team,r.date):r.home for r in tg[tg.season==2026].itertuples()}
teams={}
for r in rows:
    if r['date'] in teams: continue
    h=json.load(open(f"{A}/hch_history/{r['date']}.json"))
    teams[r['date']]={p['nhlPlayerId']:(p['team'],p['opponent']) for L in h['playerLists'] for p in L['players']}
out=[]
for r in rows:
    if not ('2026-10-02'<=r['date']<='2026-11-01'): continue
    t,o=teams[r['date']][r['pid']]
    f=fb.build(r['pid'],t,o,home.get((t,r['date']),0),r['date'],2026)
    f.update(group=r['group'],name=r['player'],scored=int(r['scored']),hch_rank=r['rank_lo'],n=r['n'],in_box=int(r['pid'] in fb.P))
    out.append(f)
df=pd.DataFrame(out); x=X(df)
df['p_logit']=M['logistic'].predict_proba(x)[:,1]; df['p_gbm']=M['gbm'].predict_proba(x)[:,1]
df.to_csv('data/backtest_group_players.csv',index=False)
# top-pick comparison
top1={d['date']:d for d in json.load(open(f'{A}/daily_top1.json'))}
ddh={d['date']:d for d in json.load(open(f'{A}/reminders/ddh_results.json'))['daily']}
res=[]
for (date,g),gr in df.groupby(['date','group']):
    rec=dict(date=date,group=g,n=len(gr),random=gr.scored.mean())
    for c,lab in (('p_logit','model'),('p_base','baseline'),('p_gbm','gbm')):
        b=gr[c].max(); w=gr[gr[c]==b]
        rec[lab]=w.scored.mean(); rec[lab+'_name']=' / '.join(w.name); rec[lab+'_p']=float(b)
    rec['hch']=top1[date][f'g{g}_hit']; rec['hch_name']=top1[date][f'g{g}']
    if date in ddh: rec['ddh']=ddh[date][f'g{g}']['ddh_hit']; rec['ddh_name']=ddh[date][f'g{g}']['ddh']
    res.append(rec)
R=pd.DataFrame(res); R.to_csv('data/backtest_top_picks.csv',index=False)
def summ(R):
    s={}
    for g,gr in list(R.groupby('group'))+[('all',R)]:
        s[str(g)]={k:[round(gr[k].sum(),2),len(gr)] for k in ['model','baseline','gbm','hch','random']}
        s[str(g)]['model_expected']=round(gr.model_p.sum(),2)
        dd=gr.dropna(subset=['ddh'])
        s[str(g)]['ddh_days']={k:[round(dd[k].sum(),2),len(dd)] for k in ['model','hch','ddh','random']}
    return s
S=summ(R); print(json.dumps(S,indent=1))
# calibration on group players and on all skater-games this season
def cal(p,y,edges=(0,.1,.15,.2,.25,.3,.35,.4,1)):
    b=pd.cut(p,edges); t=pd.DataFrame(dict(p=p,y=y,b=b)).groupby('b',observed=True).agg(n=('y','size'),pred=('p','mean'),act=('y','mean'),hits=('y','sum'))
    return t
print(cal(df.p_logit,df.scored))
d=pd.read_csv('data/skater_games_features.csv.gz'); d26=d[d.season==2026]
p26=M['logistic'].predict_proba(X(d26))[:,1]
print('all 2026 skater-games',len(d26),'pred',p26.mean(),'act',d26.scored.mean()); print(cal(p26,d26.scored.values))
from sklearn.metrics import roc_auc_score, log_loss
print('group players AUC logit',roc_auc_score(df.scored,df.p_logit),'base',roc_auc_score(df.scored,df.p_base),'hch(rank)',roc_auc_score(df.scored,-df.hch_rank/df.n))
# within-group discrimination
pairs=[0,0,0]
for _,gr in df.groupby(['date','group']):
    s=gr[gr.scored==1]; ns=gr[gr.scored==0]
    for a in s.itertuples():
        pairs[0]+=(ns.p_logit<a.p_logit).sum()+0.5*(ns.p_logit==a.p_logit).sum(); pairs[1]+=(ns.hch_rank>a.hch_rank).sum()+0.5*(ns.hch_rank==a.hch_rank).sum(); pairs[2]+=len(ns)
print('within-group AUC model',pairs[0]/pairs[2],'hch',pairs[1]/pairs[2])
json.dump(dict(summary=S,cal_groups=cal(df.p_logit,df.scored).reset_index().astype(str).to_dict('records'),
  cal_all2026=cal(p26,d26.scored.values).reset_index().astype(str).to_dict('records'),
  within_auc=dict(model=pairs[0]/pairs[2],hch=pairs[1]/pairs[2]),n_players=len(df),missing_history=int((df.in_box==0).sum())),open('data/backtest_summary.json','w'),indent=1)
