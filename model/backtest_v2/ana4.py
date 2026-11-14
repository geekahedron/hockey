import pickle, numpy as np, pandas as pd, json, unicodedata, warnings; warnings.filterwarnings('ignore')
from evalm_lib import slot_metrics
R,H,P=pickle.load(open('eval_all.pkl','rb'))
S=pd.read_csv('feats_slots.csv.gz')
s25=S[S.season==2025]; pa=P[('A_test_2025-26','current')]
for lo,hi in (('2025-10-01','2025-11-10'),('2025-11-10','2026-01-01'),('2026-01-01','2026-03-01'),('2026-03-01','2026-05-01')):
    m=((s25.slot_date>=lo)&(s25.slot_date<hi)).values
    for v in ['current','gbm_current','lr+ixg+role']:
        sm,_=slot_metrics(s25[m],P[('A_test_2025-26',v)][m]); print(lo,v,sm['slots'],sm['hits'],sm['hit_rate'],sm['within_auc'])
# DDH days in 2026
def norm(s): return ''.join(c for c in unicodedata.normalize('NFKD',s).encode('ascii','ignore').decode().lower() if c.isalpha())
ddh={}
D=json.load(open('/workspace/tims-analysis/reminders/ddh_results.json'))
for d in D['daily']:
    for g in (1,2,3): ddh[(d['date'],g)]=(d[f'g{g}']['ddh'],d[f'g{g}']['ddh_hit'])
for l in open('/cursor/stores/store-463f10b1-930b-4f2f-aa56-9ca342544d00/tims-hockey/tracking/results.jsonl'):
    r=json.loads(l)
    if r['status']=='graded' and r.get('ddh_pick'): ddh[(r['date'],r['group'])]=(r['ddh_pick'],r['ddh_hit'])
s26=S[S.season==2026].reset_index(drop=True)
keys=sorted(k for k in ddh if k[0]>='2026-10-01')
print('ddh slots',len(keys))
tot={'ddh':0,'n':0}
for v in ['current','gbm_current','lr+ixg+role','lr+form','gbm+all']:
    p=P[('B_test_2026-27',v)]; t=s26.assign(p=p); hits=0; n=0
    for k in keys:
        g=t[(t.slot_date==k[0])&(t.group==k[1])]
        if not len(g): continue
        hits+=g[g.p==g.p.max()].scored.mean(); n+=1
    print('DDH days',v,round(hits,1),n)
print('DDH',sum(ddh[k][1] for k in keys),len(keys))
