import pickle, numpy as np, pandas as pd
R,H,P=pickle.load(open('eval_all.pkl','rb'))
S=pd.read_csv('feats_slots.csv.gz')
for fn,te in (('A_test_2025-26',2025),('B_test_2026-27',2026)):
    ts=S[S.season==te].copy(); ts['p']=P[(fn,'current')]
    ts['bin']=pd.cut(ts.p,[0,.1,.15,.2,.25,.3,.35,.4,1])
    print(fn,'slot rows',len(ts),'actual',ts.scored.mean().round(4),'pred',ts.p.mean().round(4),'played',ts.played.mean().round(3))
    print(ts.groupby('bin',observed=True).agg(n=('scored','size'),pred=('p','mean'),act=('scored','mean')).round(3).to_string())
    print(ts.groupby('group').agg(n=('scored','size'),pred=('p','mean'),act=('scored','mean')).round(3).to_string())
    # bootstrap vs current
    base=H[(fn,'current')]
    for v in ['lr+ixg','lr+form','lr+role','lr+ixg+role','lr+all','gbm_current','gbm+all','p_base','gpg_proxy','random']:
        d=H[(fn,v)]-base; rng=np.random.default_rng(0); bs=[rng.choice(d,len(d)).sum() for _ in range(2000)]
        print(f'  {v:18s} diff {d.sum():+.1f}  95% CI {np.percentile(bs,2.5):+.1f}..{np.percentile(bs,97.5):+.1f}')
