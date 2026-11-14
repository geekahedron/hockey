import pandas as pd, numpy as np, json, sys, warnings; warnings.filterwarnings('ignore')
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.metrics import log_loss, roc_auc_score, brier_score_loss
import lightgbm as lgb
from features import FEATS, ROLE
A=pd.read_csv('feats_all.csv.gz'); S=pd.read_csv('feats_slots.csv.gz')
LOGS=['g60','s60','xg60','prior_g60','prior_s60','lam_g','lam_x','sh']
def Xb(df, extra=()):
    x=df[FEATS].copy()
    for c in LOGS: x['log_'+c]=np.log(x[c].clip(1e-3))
    x['log_p_base']=np.log(df.p_base.clip(1e-3)); x['cur_gp']=np.log1p(x['cur_gp']); x['prev_gp']=np.log1p(x['prev_gp'])
    for c in extra:
        if c in ('x60','f60','prior_x60','lam_ix','r_g60','r_s60','r_x60'): x['log_'+c]=np.log(df[c].clip(1e-3))
        else: x[c]=df[c]
    return x
G={'ixg':['x60','f60','prior_x60','lam_ix','fin'],'form':['r_g60','r_s60','r_x60'],'role':ROLE,
   'teamxg':['opp_xga','opp_xga10','tm_xgf','opp_sv10'],'pp':['pp_share']}
def lr(C=0.5): return make_pipeline(StandardScaler(),LogisticRegression(C=C,max_iter=3000))
def gbm(): return lgb.LGBMClassifier(n_estimators=400,learning_rate=0.02,num_leaves=15,min_child_samples=300,subsample=0.8,subsample_freq=1,colsample_bytree=0.8,reg_lambda=5,verbose=-1)
def slot_metrics(df,p):
    df=df.assign(p=p); hits=[];top3=[];pairs=[0,0]
    for _,g in df.groupby(['slot_date','group']):
        b=g.p.max(); hits.append(g[g.p==b].scored.mean())
        top3.append(g.nlargest(3,'p').scored.sum())
        s=g[g.scored==1].p.values; ns=g[g.scored==0].p.values
        for v in s: pairs[0]+=(ns<v).sum()+0.5*(ns==v).sum(); pairs[1]+=len(ns)
    return dict(slots=len(hits),hits=round(float(np.sum(hits)),1),hit_rate=round(float(np.mean(hits)),4),top3_per_slot=round(float(np.mean(top3)),3),
                within_auc=round(pairs[0]/max(pairs[1],1),4),ll=round(log_loss(df.scored,df.p.clip(1e-6,1-1e-6)),5),brier=round(brier_score_loss(df.scored,df.p.clip(0,1)),5)), np.array(hits)
