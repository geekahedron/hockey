import json, urllib.request, os, time, glob
from concurrent.futures import ThreadPoolExecutor
ids=[]
for y in (2023,2024,2025,2026):
    for l in open(f'raw/box_{y}.jsonl'): ids.append(json.loads(l)['id'])
os.makedirs('pbp',exist_ok=True)
def tsec(s): m,s=s.split(':'); return int(m)*60+int(s)
def one(gid):
    p=f'pbp/{gid}.json'
    if os.path.exists(p): return 0
    for k in range(4):
        try:
            d=json.load(urllib.request.urlopen(urllib.request.Request(f'https://api-web.nhle.com/v1/gamecenter/{gid}/play-by-play',headers={'User-Agent':'Mozilla/5.0'}),timeout=30)); break
        except Exception: time.sleep(3)
    else: return 1
    hid=d['homeTeam']['id']; out=[]
    for e in d['plays']:
        t=e['typeDescKey']
        if t not in ('goal','shot-on-goal','missed-shot','blocked-shot'): continue
        pd_=e['periodDescriptor']
        if pd_.get('periodType')=='SO': continue
        de=e.get('details',{})
        sh=de.get('shootingPlayerId') or de.get('scoringPlayerId')
        out.append([sh,de.get('xCoord'),de.get('yCoord'),de.get('zoneCode'),de.get('shotType'),e.get('situationCode'),pd_['number'],
                    pd_['number']*1200+tsec(e['timeInPeriod']), t[0], int(de.get('eventOwnerTeamId')==hid), de.get('goalieInNetId')])
    json.dump(dict(home=hid,shots=out),open(p,'w')); return 0
with ThreadPoolExecutor(8) as ex: fails=sum(ex.map(one,ids))
print('done',len(ids),'fails',fails)
