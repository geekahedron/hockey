"""Simple shot xG model trained on 2024-25 unblocked shots only; per player-game ixG for all seasons."""
import json, glob, math, numpy as np, pandas as pd, joblib
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss, roc_auc_score
rows=[]
for f in glob.glob('pbp/*.json'):
    gid=int(f.split('/')[-1][:-5]); d=json.load(open(f)); prev=None
    for s in d['shots']:
        sh,x,y,z,st,sc,per,t,typ,ishome,gl=s
        if typ=='b': prev=(t,ishome); continue  # blocked: shooter coords are block location, skip
        if sh is None or x is None or y is None or sc is None or len(sc)!=4: prev=(t,ishome); continue
        ag,ask,hsk,hg=int(sc[0]),int(sc[1]),int(sc[2]),int(sc[3])
        my,their=(hsk,ask) if ishome else (ask,hsk)
        opp_goalie=(hg if not ishome else ag)
        nx=89 if (x>=0)==(z!='D') else -89
        if z=='N': nx=89 if x>=0 else -89
        dist=math.hypot(nx-x,y); ang=abs(math.degrees(math.atan2(abs(y),max(abs(nx-x),0.1))))
        reb=int(prev is not None and prev[1]==ishome and 0<=t-prev[0]<=3)
        rows.append(dict(gid=gid,season=int(str(gid)[:4]),pid=sh,goal=int(typ=='g'),dist=dist,ang=ang,st=st or 'unk',
            pp=int(my>their),sh_=int(my<their),en=int(opp_goalie==0),reb=reb,ishome=ishome))
        prev=(t,ishome)
S=pd.DataFrame(rows); print(len(S), S.groupby('season').goal.mean())
def X(S):
    x=pd.DataFrame(dict(ld=np.log1p(S.dist),d=S.dist,ang=S.ang,ang2=(S.ang/90)**2,pp=S.pp,sh=S.sh_,en=S.en,reb=S.reb,dreb=S.reb*S.dist))
    for t in ['wrist','snap','slap','backhand','tip-in','deflected','wrap-around','bat','between-legs','poke','cradle']: x['t_'+t]=(S.st==t).astype(int)
    return x
tr=S[S.season.isin([2023,2024])]; m=LogisticRegression(C=1,max_iter=3000).fit(X(tr),tr.goal)
for s in (2025,2026):
    te=S[S.season==s]; p=m.predict_proba(X(te))[:,1]; print(s,'xG AUC',round(roc_auc_score(te.goal,p),4),'ll',round(log_loss(te.goal,p),4),'sum xg',p.sum().round(),'goals',te.goal.sum())
S['xg']=m.predict_proba(X(S))[:,1]
S['xg_noen']=np.where(S.en==1,0,S.xg)
agg=S.groupby(['gid','pid']).agg(ixg=('xg_noen','sum'),fen=('goal','size'),ppxg=('xg',lambda v: 0)).reset_index()
pp=S[S.pp==1].groupby(['gid','pid']).xg.sum().rename('ppixg')
agg=agg.drop(columns='ppxg').merge(pp,on=['gid','pid'],how='left').fillna({'ppixg':0})
# blocked attempts per player (shot attempts incl. blocked)
b=[]
for f in glob.glob('pbp/*.json'):
    gid=int(f.split('/')[-1][:-5])
    for s in json.load(open(f))['shots']:
        if s[8]=='b' and s[0]: b.append((gid,s[0]))
bb=pd.DataFrame(b,columns=['gid','pid']).groupby(['gid','pid']).size().rename('blk')
agg=agg.merge(bb,on=['gid','pid'],how='left').fillna({'blk':0})
# team-level xGF/xGA per game
S['team_home']=S.ishome
tx=S.groupby(['gid','ishome']).xg_noen.sum().rename('txg').reset_index()
agg.to_csv('ixg_player_game.csv.gz',index=False); tx.to_csv('txg_team_game.csv.gz',index=False)
joblib.dump(m,'xg_model.joblib')
print(agg.describe())
