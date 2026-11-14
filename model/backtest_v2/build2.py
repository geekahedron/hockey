import pandas as pd, json, glob, time, sys
sys.path.insert(0,'/workspace/tims-bt')
from features2 import load, FB2
sk,tg,gk=load(); fb=FB2(sk,tg,gk)
t=time.time(); rows=[]
for r in sk[sk.season>=2024].itertuples():
    f=fb.build(r.pid,r.team,r.opp,r.home,r.date,r.season)
    f['scored']=int(r.goals>0); f['name']=r.name; f['gid']=r.gid
    rows.append(f)
pd.DataFrame(rows).to_csv('feats_all.csv.gz',index=False); print('all',len(rows),time.time()-t)
# slot rows from HCH morning lists
home={(r.team,r.date):(r.home,r.opp) for r in tg.itertuples()}
scored={(r.date,r.pid):int(r.goals>0) for r in sk.itertuples()}
played=set(scored)
rows=[]
for f in sorted(glob.glob('hch/*.json'))+[]:
    H=json.load(open(f)); date=f.split('/')[-1][:10]
    if not H.get('playerLists'): continue
    t0=(H.get('availableTimes') or ['12:00 AM'])[0]
    season=int(date[:4]) if int(date[5:7])>=8 else int(date[:4])-1
    for L in H['playerLists']:
        for p in L['players']:
            if p.get('availableTimes') is not None and t0 not in p['availableTimes']: continue
            t=p['team']; h,o=home.get((t,date),(None,p.get('opponent')))
            if h is None: h=0
            fe=fb.build(p['nhlPlayerId'],t,p.get('opponent') or o,h,date,season)
            fe.update(group=L['id'],name=p['fullName'],slot_date=date,hch_scored=int(bool(p.get('scored'))),
                      scored=scored.get((date,p['nhlPlayerId']),0),played=int((date,p['nhlPlayerId']) in played))
            rows.append(fe)
S=pd.DataFrame(rows); S.to_csv('feats_slots.csv.gz',index=False)
print('slots',len(S),S.groupby('season').size(), 'days',S.slot_date.nunique(), 'agree hch scored',(S.hch_scored==S.scored).mean())
