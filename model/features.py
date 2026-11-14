"""Pre-game feature builder from raw NHL boxscores + TOI splits.
Every feature for (player, date) uses only games played strictly before that date."""
import json, glob, os, bisect, math
import numpy as np, pandas as pd, datetime as _dt
def _d(x): return _dt.date.fromisoformat(str(x)[:10])
HERE=os.path.dirname(os.path.abspath(__file__))
RAW=os.path.join(HERE,'raw')

def load():
    sk=[];tg=[];gk=[]
    for f in sorted(glob.glob(f'{RAW}/box_*.jsonl')):
        y=int(f.split('_')[-1][:4])
        toi=json.load(open(f'{RAW}/toi_{y}.json')) if os.path.exists(f'{RAW}/toi_{y}.json') else {}
        for l in open(f):
            g=json.loads(l)
            so = g.get('lastPeriod')=='SO'
            hs,as_=g['hs'],g['as']
            # boxscore team score includes the shootout winner's +1; goals excluding SO:
            gf={g['home']:0,g['away']:0}
            for r in g['sk']: gf[r[1]]+=r[3]
            sa={g['home']:0,g['away']:0}; sv={g['home']:0,g['away']:0}
            for x in g['gk']:
                sa[x[1]]+=x[3]; sv[x[1]]+=x[4]
            for t,o,h in ((g['home'],g['away'],1),(g['away'],g['home'],0)):
                tg.append(dict(season=y,date=g['date'],gid=g['id'],team=t,opp=o,home=h,gf=gf[t],ga=gf[o],sf=sa[o],sa=sa[t]))
            for x in g['gk']:
                gk.append(dict(season=y,date=g['date'],gid=g['id'],pid=x[0],team=x[1],starter=x[2],sa=x[3],sv=x[4]))
            for r in g['sk']:
                pp,ev,sh=toi.get(f"{g['id']}_{r[0]}",[np.nan,np.nan,np.nan])
                o=g['away'] if r[1]==g['home'] else g['home']
                sk.append(dict(season=y,date=g['date'],gid=g['id'],pid=r[0],team=r[1],opp=o,home=int(r[1]==g['home']),
                               pos='D' if r[2]=='D' else 'F',goals=r[3],sog=r[4],toi=r[5],ppg=r[6],pptoi=pp,name=r[8]))
    sk=pd.DataFrame(sk); tg=pd.DataFrame(tg); gk=pd.DataFrame(gk)
    sk['pptoi']=sk['pptoi'].fillna(0)
    return sk,tg,gk

class FeatureBuilder:
    def __init__(self, sk, tg, gk):
        sk=add_roles(sk)
        self.sk=sk.sort_values(['pid','date']); self.tg=tg.sort_values(['team','date'])
        # league averages per season (used as prior for the NEXT season)
        L={}
        for (s,pos),d in sk.groupby(['season','pos']):
            L[(s,pos)]=dict(g60=d.goals.sum()/d.toi.sum()*3600, s60=d.sog.sum()/d.toi.sum()*3600,
                            sh=d.goals.sum()/max(d.sog.sum(),1), toi=d.toi.mean(), pp=d.pptoi.mean())
        T={}
        for s,d in tg.groupby('season'):
            T[s]=dict(ga=d.ga.mean(), sa=d.sa.mean(), sv=1-d.ga.sum()/max(d.sa.sum(),1), gf=d.gf.mean())
        self.L=L; self.T=T
        self.P={}
        for pid,d in self.sk.groupby('pid'):
            self.P[pid]=dict(date=d.date.values, season=d.season.values,
                arr=d[['goals','sog','toi','pptoi','ppg']].values.astype(float),
                pos=d.pos.values, team=d.team.values, role=d[['pp1','pp2','l1','l2']].values.astype(float))
        self.TM={}
        for t,d in self.tg.groupby('team'):
            self.TM[t]=dict(date=d.date.values, season=d.season.values, arr=d[['gf','ga','sf','sa']].values.astype(float))
        self.seasons=sorted(L)
    def lg(self, season, pos):
        # league prior = previous season's league average (known before the season); fallback same season
        for s in (season-1, season):
            if (s,pos) in self.L: return self.L[(s,pos)]
    def tlg(self, season):
        for s in (season-1, season):
            if s in self.T: return self.T[s]
    def player(self, pid, season, date, pos_hint='F'):
        P=self.P.get(pid)
        z=np.zeros(5)
        if P is None:
            return dict(pos=pos_hint, cur=z, cur_gp=0, l5=z, l5_gp=0, prev=z, prev_gp=0, prev2=z, prev2_gp=0, last_team=None, role=None)
        d=P['date']; s=P['season']; A=P['arr']
        i=bisect.bisect_left(d, date)  # games strictly before date
        cur_m=(s[:i]==season); cur=A[:i][cur_m]
        prev_m=(s==season-1); prev2_m=(s==season-2)
        l5=cur[-5:]
        pos=P['pos'][i-1] if i>0 else P['pos'][0]
        return dict(pos=pos, cur=cur.sum(0) if len(cur) else z, cur_gp=len(cur), l5=l5.sum(0) if len(l5) else z, l5_gp=len(l5),
                    prev=A[prev_m].sum(0) if prev_m.any() else z, prev_gp=int(prev_m.sum()),
                    prev2=A[prev2_m].sum(0) if prev2_m.any() else z, prev2_gp=int(prev2_m.sum()),
                    last_team=P['team'][i-1] if i>0 else None,
                    role=P['role'][max(0,i-3):i].mean(0) if i>0 else None)
    def team(self, team, season, date):
        M=self.TM.get(team)
        if M is None: return np.zeros(4),0,np.zeros(4),0,None
        d=M['date']; s=M['season']; A=M['arr']
        i=bisect.bisect_left(d,date)
        cm=s[:i]==season; cur=A[:i][cm]
        pm=s==season-1
        last=d[:i][cm][-1] if cm.any() else None
        return (cur.sum(0) if len(cur) else np.zeros(4)), len(cur), (A[pm].sum(0) if pm.any() else np.zeros(4)), int(pm.sum()), last
    def build(self, pid, team, opp, home, date, season, pos_hint='F', role_override=None):
        p=self.player(pid,season,date,pos_hint); pos=p['pos']; lg=self.lg(season,pos); tl=self.tlg(season)
        # --- shrinkage rates (per 60 min); pseudo-TOI weights in seconds
        cur,prev,prev2=p['cur'],p['prev'],p['prev2']
        # prior from previous two seasons (prev2 at half weight), shrunk to league with 400 min pseudo TOI for goals
        ptoi=prev[2]+0.5*prev2[2]; pg=prev[0]+0.5*prev2[0]; ps=prev[1]+0.5*prev2[1]
        K_G=400*60; K_S=150*60
        prior_g60=(pg+K_G*lg['g60']/3600)/(ptoi+K_G)*3600
        prior_s60=(ps+K_S*lg['s60']/3600)/(ptoi+K_S)*3600
        prior_sh=(pg+60*lg['sh'])/(ps+60)
        # current season blended: prior acts like W seconds of TOI
        W_G=600*60; W_S=200*60
        g60=(cur[0]+W_G*prior_g60/3600)/(cur[2]+W_G)*3600
        s60=(cur[1]+W_S*prior_s60/3600)/(cur[2]+W_S)*3600
        sh=(cur[0]+pg+60*lg['sh'])/(cur[1]+ps+60)
        xg60=s60*sh
        # expected TOI and PP TOI per game
        prev_toi=prev[2]/p['prev_gp'] if p['prev_gp'] else lg['toi']*0.85
        prev_pp=prev[3]/p['prev_gp'] if p['prev_gp'] else lg['pp']*0.5
        l5_toi=p['l5'][2]/p['l5_gp'] if p['l5_gp'] else prev_toi
        l5_pp=p['l5'][3]/p['l5_gp'] if p['l5_gp'] else prev_pp
        cur_toi=cur[2]/p['cur_gp'] if p['cur_gp'] else prev_toi
        n=p['cur_gp']; w=n/(n+3)
        toi_hat=w*(0.6*l5_toi+0.4*cur_toi)+(1-w)*prev_toi
        pp_hat=w*l5_pp+(1-w)*prev_pp
        # team/opponent context, shrunk to previous season and league
        oc,on,op,opn,olast=self.team(opp,season,date)
        tc,tn,tp,tpn,tlast=self.team(team,season,date)
        K=10
        opp_ga_prior=(op[1]/opn if opn else tl['ga']); opp_sa_prior=(op[3]/opn if opn else tl['sa'])
        opp_ga=(oc[1]+K*(0.5*opp_ga_prior+0.5*tl['ga']))/(on+K)
        opp_sa=(oc[3]+K*(0.5*opp_sa_prior+0.5*tl['sa']))/(on+K)
        opp_sv_prior=1-(op[1]/op[3]) if opn and op[3] else tl['sv']
        opp_sv=1-(oc[1]+20*30*(1-(0.5*opp_sv_prior+0.5*tl['sv'])))/(oc[3]+20*30)
        tm_gf_prior=(tp[0]/tpn if tpn else tl['gf'])
        tm_gf=(tc[0]+K*(0.5*tm_gf_prior+0.5*tl['gf']))/(tn+K)
        def rest(last):
            if last is None: return 4
            return min((_d(date)-_d(last)).days,4)
        r_t=rest(tlast); r_o=rest(olast)
        opp_factor=opp_ga/tl['ga']
        lam=g60*toi_hat/3600*opp_factor*(1.03 if home else 0.97)
        lam_x=xg60*toi_hat/3600*opp_factor*(1.03 if home else 0.97)
        lam_b=0.5*lam+0.5*lam_x
        return dict(pid=pid,date=date,season=season,team=team,opp=opp,home=int(home),is_d=int(pos=='D'),
            cur_gp=n,prev_gp=p['prev_gp'],cur_g=cur[0],cur_sog=cur[1],
            g60=g60,s60=s60,sh=sh,xg60=xg60,prior_g60=prior_g60,prior_s60=prior_s60,
            cur_g60=(cur[0]/cur[2]*3600 if cur[2] else np.nan),
            toi_hat=toi_hat/60,pp_hat=pp_hat/60,l5_toi=l5_toi/60,prev_toi=prev_toi/60,
            opp_ga=opp_ga,opp_sa=opp_sa,opp_sv=opp_sv,tm_gf=tm_gf,b2b=int(r_t==1),opp_b2b=int(r_o==1),
            rest_t=r_t,rest_o=r_o,opp_factor=opp_factor,
            p_base=1-math.exp(-lam_b), lam_g=lam, lam_x=lam_x,
            **role_feats(p['role'], role_override))

FEATS=['home','is_d','cur_gp','prev_gp','g60','s60','sh','xg60','prior_g60','prior_s60','toi_hat','pp_hat','l5_toi',
       'opp_ga','opp_sa','opp_sv','tm_gf','b2b','opp_b2b','lam_g','lam_x']


# ---- usage-role features (NHL-data proxies for HCH's "line" and "ppLine") ----
def add_roles(sk):
    sk=sk.copy()
    sk['ev']=sk.toi-sk.pptoi
    sk['pp_rank']=sk.groupby(['gid','team']).pptoi.rank(ascending=False,method='first')
    sk['ev_rank']=sk.groupby(['gid','team','pos']).ev.rank(ascending=False,method='first')
    has_pp=sk.pptoi>30
    sk['pp1']=((sk.pp_rank<=5)&has_pp).astype(int)
    sk['pp2']=((sk.pp_rank>5)&(sk.pp_rank<=10)&has_pp).astype(int)
    per=np.where(sk.pos=='D',2,3)
    line=np.ceil(sk.ev_rank/per)
    sk['l1']=(line==1).astype(int); sk['l2']=(line==2).astype(int)
    return sk
def role_feats(role, override=None):
    """Share of the last 3 games on PP1 / PP2 / top line / 2nd line. override = dict from HCH live
    (e.g. {'line':'F1','ppLine':'PP1'}) replaces the proxy with today's projected lineup."""
    r=dict(role_pp1=np.nan,role_pp2=np.nan,role_l1=np.nan,role_l2=np.nan) if role is None else dict(role_pp1=role[0],role_pp2=role[1],role_l1=role[2],role_l2=role[3])
    if override:
        pl=override.get('ppLine') or ''; ln=override.get('line') or ''
        if ln: r['role_l1']=float(ln[1:]=='1'); r['role_l2']=float(ln[1:]=='2')
        r['role_pp1']=float(pl=='PP1'); r['role_pp2']=float(pl=='PP2')
    for k in r:
        if r[k] is None or (isinstance(r[k],float) and math.isnan(r[k])): r[k]=0.0
    return r
ROLE=['role_pp1','role_pp2','role_l1','role_l2']
