import os, sys, pandas as pd, numpy as np, warnings; warnings.filterwarnings('ignore')
import features_p as F
from evalm_lib import slot_metrics, lr, LOGS
from sklearn.metrics import log_loss
sk,tg,gk=F.load(); fb=F.FeatureBuilder(sk,tg,gk)
S=pd.read_csv('feats_slots.csv.gz')
rows=[]
for r in sk[sk.season>=2024].itertuples():
    f=fb.build(r.pid,r.team,r.opp,r.home,r.date,r.season); f['scored']=int(r.goals>0); rows.append(f)
A=pd.DataFrame(rows)
home={(r.team,r.date):r.home for r in tg.itertuples()}
srows=[]
for r in S.itertuples():
    f=fb.build(r.pid,r.team,r.opp,r.home,r.slot_date,r.season); f.update(scored=r.scored,slot_date=r.slot_date,group=r.group); srows.append(f)
SS=pd.DataFrame(srows)
def Xb(df):
    x=df[F.FEATS].copy()
    for c in LOGS: x['log_'+c]=np.log(x[c].clip(1e-3))
    x['log_p_base']=np.log(df.p_base.clip(1e-3)); x['cur_gp']=np.log1p(x['cur_gp']); x['prev_gp']=np.log1p(x['prev_gp']); return x
out=[os.environ.get(k,'def') for k in ('KG','KS','WG','WS')]
for trs,te in (([2024],2025),([2024,2025],2026)):
    tr=A[A.season.isin(trs)]; ta=A[A.season==te]; ts=SS[SS.season==te]
    m=lr().fit(Xb(tr),tr.scored); pa=m.predict_proba(Xb(ta))[:,1]; sm,_=slot_metrics(ts,m.predict_proba(Xb(ts))[:,1])
    out+= [round(log_loss(ta.scored,pa),5), sm['hits'], sm['within_auc']]
print(*out, flush=True)
