"""Grade one Tims Hockey Challenge day: did our model's #1, DDH's #1 and HCH's #1 score?

Usage:  python grade_date.py 2026-11-02 [--dry-run] [--tracking DIR] [--hch FILE] [--ddh FILE]
Inputs (defaults, relative to tims-hockey/):
  model/picks/DATE.json          our picks (from score_date.py)
  snapshots/DATE_hch.json        HCH morning list -> HCH #1 = highest goals/game among available players (ties share the pick)
  snapshots/DATE_ddh.json        DDH list [{pick_group, player, probability}] -> DDH #1 = highest probability
Scorers: api-web.nhle.com/v1/score/DATE, all non-shootout goals. A group is graded only when every game involving
its players is final (OFF/FINAL); otherwise the row is written with status "pending" (picks only, hits null)
and a later run replaces it with the graded row.
Writes/replaces that date's rows in tracking/results.jsonl (one row per group). random = share of the group's
available players who scored (= expected hit rate of a random pick)."""
import sys, os, json, argparse, unicodedata, urllib.request, datetime as dt
HERE=os.path.dirname(os.path.abspath(__file__)); ROOT=os.path.join(HERE,'..')
UA={'User-Agent':'Mozilla/5.0'}
def get(u):
    with urllib.request.urlopen(urllib.request.Request(u,headers=UA),timeout=30) as r: return json.load(r)
def norm(s): return ''.join(c for c in unicodedata.normalize('NFKD',s or '') if not unicodedata.combining(c)).lower().replace('.','').replace("'",'').strip()
def top(players,key):
    """players: list of (pid,name,value) -> list of tied leaders"""
    v=[p for p in players if p[2] is not None]
    if not v: return []
    b=max(p[2] for p in v); return [p for p in v if p[2]==b]
def main():
    ap=argparse.ArgumentParser(); ap.add_argument('date'); ap.add_argument('--dry-run',action='store_true')
    ap.add_argument('--tracking',default=os.path.join(ROOT,'tracking')); ap.add_argument('--hch'); ap.add_argument('--ddh'); ap.add_argument('--picks')
    a=ap.parse_args(); ds=a.date
    picks=json.load(open(a.picks or os.path.join(HERE,'picks',f'{ds}.json')))
    hp=a.hch or os.path.join(ROOT,'snapshots',f'{ds}_hch.json'); H=json.load(open(hp)) if os.path.exists(hp) else None
    dp=a.ddh or os.path.join(ROOT,'snapshots',f'{ds}_ddh.json'); D=json.load(open(dp)) if os.path.exists(dp) else None
    sc=get(f'https://api-web.nhle.com/v1/score/{ds}')
    scorers=set(); final={}; 
    for g in sc.get('games',[]):
        st=g.get('gameState'); fin=st in ('OFF','FINAL')
        for t in (g['homeTeam']['abbrev'],g['awayTeam']['abbrev']): final[t]=fin
        for gl in g.get('goals',[]) or []:
            if (gl.get('periodDescriptor') or {}).get('periodType')!='SO': scorers.add(gl['playerId'])
    rows=[]; pending=[]
    for g,pl in picks['groups'].items():
        g=int(g); pids={p['pid'] for p in pl}; byname={norm(p['name']):p for p in pl}
        teams={p['team'] for p in pl}
        not_final=[t for t in teams if not final.get(t,False)]
        is_pending=bool([t for t in not_final if t in final]) or not final
        if is_pending: pending.append(g)
        hit=(lambda pid: None) if is_pending else (lambda pid: int(pid in scorers))
        S=lambda xs: None if is_pending else sum(xs)
        avail=[p for p in pl if p['team'] in final]   # players whose game was played
        rnd=None if is_pending else sum(hit(p['pid']) for p in avail)/max(len(avail),1)
        m=pl[0]; mt=[p for p in pl if p['p']==m['p']]
        R=lambda x,k: None if x is None else round(x/k,4)
        rec=dict(date=ds,group=g,status='pending' if is_pending else 'graded',n=len(avail),
                 scorers_in_group=None if is_pending else [p['name'] for p in avail if hit(p['pid'])],random=None if rnd is None else round(rnd,4),
                 model_pick=' / '.join(p['name'] for p in mt),model_p=m['p'],model_hit=R(S(hit(p['pid']) for p in mt),len(mt)),
                 model_top3_hits=S(hit(p['pid']) for p in pl[:3]))
        # HCH #1: highest goals/game (snapshot value if present, else NHL goals/GP stored in picks)
        hv={}
        if H:
            for L in H['playerLists']:
                if L['id']==g:
                    for p in L['players']:
                        if not p.get('unavailable') and p.get('goalsPerGame') is not None: hv[p['nhlPlayerId']]=(p.get('fullName'),p['goalsPerGame'])
        src='hch_snapshot'
        if not hv: hv={p['pid']:(p['name'],round(p['goals']/p['gp'],2) if p['gp'] else 0) for p in pl}; src='nhl_goals_per_gp'
        ht=top([(k,v[0],v[1]) for k,v in hv.items() if k in pids],None)
        if ht: rec.update(hch_pick=' / '.join(t[1] for t in ht),hch_gpg=ht[0][2],hch_hit=R(S(hit(t[0]) for t in ht),len(ht)),hch_source=src)
        if D:
            dl=[(byname.get(norm(d['player']),{}).get('pid'),d['player'],d['probability']) for d in D if int(d['pick_group'])==g]
            dt_=top(dl,None)
            if dt_: rec.update(ddh_pick=' / '.join(t[1] for t in dt_),ddh_p=dt_[0][2],ddh_hit=R(S(hit(t[0]) for t in dt_ if t[0]),len(dt_)),
                               ddh_unmatched=[t[1] for t in dt_ if not t[0]] or None)
        rec['graded_at']=dt.datetime.now().astimezone().isoformat(timespec='seconds')
        rows.append(rec)
    for r in rows:
        if r['status']=='pending':
            print(f"{r['date']} G{r['group']}: PENDING | model {r['model_pick']} {r['model_p']:.3f} | HCH {r.get('hch_pick')} | DDH {r.get('ddh_pick')}"); continue
        print(f"{r['date']} G{r['group']}: model {r['model_pick']} {'HIT' if r['model_hit'] else 'miss'} | "
              f"HCH {r.get('hch_pick')} {('HIT' if r.get('hch_hit') else 'miss') if 'hch_hit' in r else 'n/a'} | "
              f"DDH {r.get('ddh_pick','n/a')} {('HIT' if r.get('ddh_hit') else 'miss') if 'ddh_hit' in r else ''} | random {r['random']:.2f} | scorers: {', '.join(r['scorers_in_group']) or '-'}")
    if pending: print(f'pending (games not final): groups {pending} - picks recorded, re-run after the games to grade')
    if a.dry_run or not rows: return
    os.makedirs(a.tracking,exist_ok=True); fp=os.path.join(a.tracking,'results.jsonl')
    old=[json.loads(l) for l in open(fp)] if os.path.exists(fp) else []
    done={r['group'] for r in rows}
    keep=[r for r in old if not (r['date']==ds and r['group'] in done)]
    with open(fp,'w') as f:
        for r in sorted(keep+rows,key=lambda r:(r['date'],r['group'])): f.write(json.dumps(r,ensure_ascii=False)+'\n')
    print(f'wrote {len(rows)} rows -> {fp}')
if __name__=='__main__': main()
