import pickle, numpy as np, pandas as pd, warnings; warnings.filterwarnings('ignore')
from evalm_lib import *
R,H,P=pickle.load(open('eval_all.pkl','rb'))
S=pd.read_csv('feats_slots.csv.gz')
def per_group(ts,p):
    ts=ts.assign(p=p); out={}
    for g,gg in ts.groupby('group'):
        h=[x[x.p==x.p.max()].scored.mean() for _,x in gg.groupby('slot_date')]; out[g]=round(np.sum(h),1)
    return out
for fn,te in (('A_test_2025-26',2025),('B_test_2026-27',2026)):
    ts=S[S.season==te]
    for v in ['current','lr+ixg+role','gbm_current','gbm+all','lr+form']: print(fn,v,per_group(ts,P[(fn,v)]))
    print(fn,'random',per_group(ts,np.random.default_rng(1).random(len(ts))*0+0.15))
    ens=(P[(fn,'current')]+P[(fn,'gbm_current')])/2; sm,h=slot_metrics(ts,ens); print(fn,'ens lr+gbm',sm, 'diff',h.sum()-H[(fn,'current')].sum())
    ens=(P[(fn,'lr+ixg+role')]+P[(fn,'gbm+all')])/2; sm,h=slot_metrics(ts,ens); print(fn,'ens all',sm,'diff',h.sum()-H[(fn,'current')].sum())
# slot-trained second stage: train on earlier slots, test on later
S['lp']=np.nan
EX=['x60','f60','fin','r_g60','r_s60','role_pp1','role_l1','opp_xga','pp_share','toi_hat','cur_gp']
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
def stage(trs, tes, ptr, pte, ex):
    def F(d,p): 
        x=pd.DataFrame({'lp':np.log(p/(1-p))},index=d.index)
        for c in ex: x[c]=d[c].values
        return x
    m=make_pipeline(StandardScaler(),LogisticRegression(C=0.1,max_iter=2000)).fit(F(trs,ptr),trs.scored)
    return m.predict_proba(F(tes,pte))[:,1]
# B: train stage-2 on 2025 slots (using fold A predictions = out-of-sample from 2024-trained model), test on 2026 slots
s25=S[S.season==2025]; s26=S[S.season==2026]
for ex in ([],['role_pp1','role_l1'],['x60','fin'],['r_g60','r_s60'],EX):
    p=stage(s25,s26,P[('A_test_2025-26','current')],P[('B_test_2026-27','current')],ex)
    sm,h=slot_metrics(s26,p); print('stage2 B',ex,sm,'diff',h.sum()-H[('B_test_2026-27','current')].sum())
# A rolling: train stage2 on 2025 slots before Jan 1, test from Jan 1
pa=P[('A_test_2025-26','current')]; m1=(s25.slot_date<'2026-01-01').values
base=slot_metrics(s25[~m1],pa[~m1])[1].sum()
for ex in ([],['role_pp1','role_l1'],['x60','fin'],['r_g60','r_s60'],EX):
    p=stage(s25[m1],s25[~m1],pa[m1],pa[~m1],ex); sm,h=slot_metrics(s25[~m1],p); print('stage2 A-late',ex,sm,'diff',h.sum()-base)
