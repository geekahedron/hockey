"""Per player-game TOI split (EV/PP/SH) from api.nhle.com/stats/rest skater/timeonice, weekly windows.
Usage: python fetch_pptoi.py SEASON_START_YEAR ... -> raw/toi_{y}.json  {gameId_playerId: [pp, ev, sh]}"""
import json, sys, time, urllib.request, urllib.parse, datetime as dt
from concurrent.futures import ThreadPoolExecutor
UA={'User-Agent':'Mozilla/5.0'}
SORT=urllib.parse.quote(json.dumps([{"property":"gameId","direction":"ASC"},{"property":"playerId","direction":"ASC"}]))
def get(url):
    for i in range(5):
        try:
            with urllib.request.urlopen(urllib.request.Request(url,headers=UA),timeout=40) as r: return json.load(r)
        except Exception: time.sleep(1+2*i)
    raise RuntimeError(url)
def window(args):
    y,a,b=args; out={}; start=0
    while True:
        exp=urllib.parse.quote(f'seasonId={y}{y+1} and gameTypeId=2 and gameDate>="{a}" and gameDate<="{b} 23:59:59"')
        d=get(f'https://api.nhle.com/stats/rest/en/skater/timeonice?isAggregate=false&isGame=true&start={start}&limit=100&sort={SORT}&cayenneExp={exp}')
        for r in d['data']: out[f"{r['gameId']}_{r['playerId']}"]=[r['ppTimeOnIce'],r['evTimeOnIce'],r['shTimeOnIce']]
        start+=100
        if len(d['data'])<100: break
    return out
if __name__=="__main__":
    for y in map(int,sys.argv[1:]):
        s=dt.date(y,9,25); e=min(dt.date(y+1,6,1),dt.date.today())
        ws=[];d=s
        while d<e: ws.append((y,d.isoformat(),(d+dt.timedelta(days=6)).isoformat())); d+=dt.timedelta(days=7)
        res={}
        with ThreadPoolExecutor(8) as ex:
            for o in ex.map(window,ws): res.update(o)
        json.dump(res,open(f'raw/toi_{y}.json','w')); print(y,len(res),'player-games')
    