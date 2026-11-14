"""Score one day's Tims Hockey Challenge pick groups with the raw-NHL-data model.

Usage:  python score_date.py 2026-11-02 [--groups path/to/groups.json] [--no-update]
Groups JSON: HCH-style {"playerLists":[{"id":1,"players":[{"nhlPlayerId":..,"team":..,"opponent"|"opponentTeam":..,"homeAway":..}]}]}
Default groups file: ../snapshots/{date}_hch.json, else the HCH history API.
Before scoring it pulls any newly finished games of the current season from api-web.nhle.com (boxscores + TOI splits).
Writes picks/{date}.json and prints the pick per group. Probabilities = chance of >=1 non-shootout goal."""
import sys, os, json, datetime as dt, urllib.request, argparse
HERE=os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0,HERE); os.chdir(HERE)
import numpy as np, pandas as pd, joblib
from features import load, FeatureBuilder
from train_utils import X
UA={'User-Agent':'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36',
    'Referer':'https://hockeychallengehelper.com/','Origin':'https://hockeychallengehelper.com'}
def get(u):
    with urllib.request.urlopen(urllib.request.Request(u,headers=UA),timeout=30) as r: return json.load(r)
HCH_KEEP=['line','ppLine','linemates','ppLinemates','goalsPerGame','shotsPerGame','shootingPercentage',
          'timeOnIcePerGame','powerPlayTimeOnIcePerGame','opponentGAA','gamesPlayed','goals']
def season_of(d): return d.year if d.month>=8 else d.year-1
def update(date):
    from fetch_boxscores import compact, get as bget
    from fetch_pptoi import window
    y=season_of(date); path=f'raw/box_{y}.jsonl'
    have={}; last=None
    if os.path.exists(path):
        for l in open(path):
            g=json.loads(l); have[g['id']]=1; last=max(last or g['date'],g['date'])
    d=dt.date.fromisoformat(last)-dt.timedelta(days=1) if last else dt.date(y,9,20)
    new=0
    with open(path,'a') as f:
        while d<date:
            for gm in get(f'https://api-web.nhle.com/v1/score/{d}').get('games',[]):
                if gm['id'] in have or gm.get('gameType')!=2: continue
                c=compact(bget(f"https://api-web.nhle.com/v1/gamecenter/{gm['id']}/boxscore"))
                if c: f.write(json.dumps(c)+'\n'); have[gm['id']]=1; new+=1
            d+=dt.timedelta(days=1)
    if new:
        tp=f'raw/toi_{y}.json'; toi=json.load(open(tp)) if os.path.exists(tp) else {}
        a=dt.date.fromisoformat(last) if last else dt.date(y,9,20)
        toi.update(window((y,(a-dt.timedelta(days=2)).isoformat(),(date-dt.timedelta(days=1)).isoformat())))
        json.dump(toi,open(tp,'w'))
    print(f'update: {new} new games added', file=sys.stderr)
def groups_for(date, path):
    snap=os.path.join(HERE,'..','snapshots',f'{date}_hch.json')
    for c in ([path] if path else [snap]):
        if c and os.path.exists(c): return json.load(open(c))
    # live list (only today's groups; carries line / PP unit / opponent GAA) -> save as the day's snapshot
    try:
        live=get('https://api.hockeychallengehelper.com/api/picks')
        if str(live.get('dateTimeAvailable','')).startswith(date):
            os.makedirs(os.path.dirname(snap),exist_ok=True); json.dump(live,open(snap,'w'))
            print(f'saved live HCH list -> {snap}', file=sys.stderr); return live
    except Exception as e: print('HCH live fetch failed:',e, file=sys.stderr)
    return get(f'https://api.hockeychallengehelper.com/api/history?datetime={date}T00:00:00')
def main():
    ap=argparse.ArgumentParser(); ap.add_argument('date'); ap.add_argument('--groups'); ap.add_argument('--no-update',action='store_true')
    a=ap.parse_args(); date=dt.date.fromisoformat(a.date); ds=date.isoformat(); S=season_of(date)
    if not a.no_update: update(date)
    G=groups_for(ds,a.groups)
    sched={}
    try:
        for gm in get(f'https://api-web.nhle.com/v1/score/{ds}').get('games',[]):
            sched[gm['homeTeam']['abbrev']]=1; sched[gm['awayTeam']['abbrev']]=0
    except Exception: pass
    sk,tg,gk=load(); fb=FeatureBuilder(sk,tg,gk); M=joblib.load('data/models.joblib')
    rows=[]
    for L in G['playerLists']:
        for p in L['players']:
            if p.get('unavailable'): continue  # HCH marks scratched/injured players
            if G.get('availableTimes') and p.get('availableTimes') is not None and G['availableTimes'][0] not in p['availableTimes']: continue  # history file: keep the morning list only
            t=p['team']; o=p.get('opponent') or p.get('opponentTeam')
            h=sched.get(t, 1 if p.get('homeAway')=='HOME' else 0)
            f=fb.build(p['nhlPlayerId'],t,o,h,ds,S,'D' if p.get('position')=='D' else 'F')
            f.update(group=L['id'],pid=p['nhlPlayerId'],name=p.get('fullName') or f"{p.get('firstName','')} {p.get('lastName','')}".strip(),
                     hch={k:p[k] for k in HCH_KEEP if k in p})
            rows.append(f)
    df=pd.DataFrame(rows); df['p']=M['logistic'].predict_proba(X(df))[:,1]
    out={'date':ds,'model':'logistic on shrunk NHL rates (trained 2024-25 + 2025-26)','groups':{}}
    for g,gr in df.sort_values('p',ascending=False).groupby('group'):
        out['groups'][int(g)]=[dict(name=r.name,team=r.team,opp=r.opp,home=int(r.home),p=round(float(r.p),4),
            toi=round(r.toi_hat,1),pp_toi=round(r.pp_hat,2),g60=round(r.g60,2),gp=int(r.cur_gp),goals=int(r.cur_g),pid=int(r.pid),
            role_pp1=round(r.role_pp1,2),role_l1=round(r.role_l1,2),hch=r.hch) for r in gr.itertuples()]
        top=out['groups'][int(g)][0]
        print(f"Group {g}: {top['name']} ({top['team']} vs {top['opp']}) {top['p']*100:.1f}%  | next: "+', '.join(f"{x['name']} {x['p']*100:.1f}%" for x in out['groups'][int(g)][1:3]))
    out['unavailable']=[dict(pid=p['nhlPlayerId'],name=p.get('fullName'),group=L['id']) for L in G['playerLists'] for p in L['players'] if p.get('unavailable')]
    out['hch_warnings']=G.get('warnings') or []
    os.makedirs('picks',exist_ok=True); json.dump(out,open(f'picks/{ds}.json','w'),indent=1)
if __name__=='__main__': main()
