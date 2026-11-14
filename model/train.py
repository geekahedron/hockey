"""Compare baseline / logistic / gradient boosting on season 2025-26 (trained on 2024-25),
then fit final models on 2024-25 + 2025-26 and save them."""
import pandas as pd, numpy as np, json, joblib
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.metrics import log_loss, roc_auc_score, brier_score_loss
import lightgbm as lgb
from features import FEATS
d=pd.read_csv('data/skater_games_features.csv.gz')
from train_utils import X
def models():
    return {'logistic':make_pipeline(StandardScaler(),LogisticRegression(C=0.5,max_iter=2000)),
            'gbm':lgb.LGBMClassifier(n_estimators=300,learning_rate=0.03,num_leaves=15,min_child_samples=200,subsample=0.8,subsample_freq=1,colsample_bytree=0.8,reg_lambda=5,verbose=-1)}
tr=d[d.season==2024]; va=d[d.season==2025]
res={}
def ev(name,y,p): res[name]=dict(logloss=round(log_loss(y,p),5),auc=round(roc_auc_score(y,p),4),brier=round(brier_score_loss(y,p),5),mean_pred=round(float(np.mean(p)),4),actual=round(float(np.mean(y)),4))
ev('constant',va.scored,np.full(len(va),tr.scored.mean()))
ev('baseline_shrinkage',va.scored,va.p_base)
for k,m in models().items():
    m.fit(X(tr),tr.scored); ev(k,va.scored,m.predict_proba(X(va))[:,1])
print(json.dumps(res,indent=1))
full=d[d.season.isin([2024,2025])]
final={}
for k,m in models().items():
    m.fit(X(full),full.scored); final[k]=m
joblib.dump(final,'data/models.joblib')
json.dump(res,open('data/validation_2025_26.json','w'),indent=1)
g=final['gbm']; imp=sorted(zip(X(full).columns,g.booster_.feature_importance('gain')),key=lambda t:-t[1])
print([(a,round(b)) for a,b in imp[:12]])
