"""Fetch NHL regular-season boxscores (api-web.nhle.com) into compact player-game rows.
Usage: python fetch_boxscores.py SEASON_START_YEAR [SEASON_START_YEAR ...]
Writes raw/box_{season}.jsonl (one line per game, compacted)."""
import json, sys, os, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
UA={'User-Agent':'Mozilla/5.0'}
def get(url, tries=4):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url,headers=UA),timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code==404: return None
            time.sleep(1+2*i)
        except Exception:
            time.sleep(1+2*i)
    return None
def toi(s):
    m,s2=s.split(':'); return int(m)*60+int(s2)
def compact(d):
    if not d or d.get('gameType')!=2 or d.get('gameState') not in ('OFF','FINAL'): return None
    g={'id':d['id'],'date':d['gameDate'],'home':d['homeTeam']['abbrev'],'away':d['awayTeam']['abbrev'],
       'hs':d['homeTeam'].get('score'),'as':d['awayTeam'].get('score'),
       'lastPeriod':(d.get('gameOutcome') or {}).get('lastPeriodType'),'sk':[],'gk':[]}
    for side,team in (('homeTeam',g['home']),('awayTeam',g['away'])):
        p=d['playerByGameStats'][side]
        for pos in ('forwards','defense'):
            for x in p.get(pos,[]):
                g['sk'].append([x['playerId'],team,x['position'],x['goals'],x.get('sog',0),toi(x['toi']),x.get('powerPlayGoals',0),x.get('shifts',0),x['name']['default']])
        for x in p.get('goalies',[]):
            g['gk'].append([x['playerId'],team,int(bool(x.get('starter'))),x.get('shotsAgainst',0),x.get('saves',0),toi(x['toi']),x['name']['default']])
    return g
def season(y):
    out=f'raw/box_{y}.jsonl'
    have=set()
    if os.path.exists(out):
        for l in open(out): have.add(json.loads(l)['id'])
    ids=[int(f'{y}02{n:04d}') for n in range(1,1313)]
    ids=[i for i in ids if i not in have]
    with ThreadPoolExecutor(16) as ex, open(out,'a') as f:
        for d in ex.map(lambda i: get(f'https://api-web.nhle.com/v1/gamecenter/{i}/boxscore'), ids):
            c=compact(d)
            if c: f.write(json.dumps(c)+'\n')
    print(y, sum(1 for _ in open(out)), 'games')
if __name__=="__main__":
    for y in sys.argv[1:]: season(int(y))
