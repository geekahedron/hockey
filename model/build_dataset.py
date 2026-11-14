"""Build pre-game feature rows for every skater-game (training + this-season calibration)."""
import pandas as pd, time
from features import load, FeatureBuilder
sk,tg,gk=load()
fb=FeatureBuilder(sk,tg,gk)
rows=[]; t=time.time()
for r in sk[sk.season>=2024].itertuples():
    f=fb.build(r.pid,r.team,r.opp,r.home,r.date,r.season)
    f['scored']=int(r.goals>0); f['name']=r.name
    rows.append(f)
df=pd.DataFrame(rows); df.to_csv('data/skater_games_features.csv.gz',index=False)
print(len(df), time.time()-t); print(df.groupby('season').scored.agg(['mean','size']))
