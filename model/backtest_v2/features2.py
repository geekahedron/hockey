"""Extended pre-game features: base model features + shot quality (ixG from play-by-play), recent form, roles, team xG.
Uses only games strictly before the date."""
import json, os, bisect, math, numpy as np, pandas as pd
from features import FeatureBuilder, load as load_base
HERE=os.path.dirname(os.path.abspath(__file__))
def load(ixg_path=None, txg_path=None):
    sk,tg,gk=load_base()
    ix=pd.read_csv(ixg_path or os.path.join(HERE,'raw','ixg_player_game.csv.gz'))
    sk=sk.merge(ix,on=['gid','pid'],how='left')
    for c in ['ixg','fen','ppixg','blk']: sk[c]=sk[c].fillna(0)
    tx=pd.read_csv(txg_path or os.path.join(HERE,'raw','txg_team_game.csv.gz'))
    tg=tg.merge(tx.rename(columns={'ishome':'home','txg':'xgf'}),on=['gid','home'],how='left')
    tx2=tx.copy(); tx2['ishome']=1-tx2.ishome
    tg=tg.merge(tx2.rename(columns={'ishome':'home','txg':'xga'}),on=['gid','home'],how='left')
    tg[['xgf','xga']]=tg[['xgf','xga']].fillna(tg[['xgf','xga']].mean())
    return sk,tg,gk
class FB2(FeatureBuilder):
    def __init__(self, sk, tg, gk):
        super().__init__(sk,tg,gk)
        self.X={}
        for pid,d in self.sk.groupby('pid'):
            self.X[pid]=d[['ixg','fen','blk','ppixg','goals','sog','toi']].values.astype(float)
        self.TX={}
        for t,d in self.tg.groupby('team'):
            self.TX[t]=d[['xgf','xga','ga','sa']].values.astype(float)
        self.LX={}
        for (s,pos),d in self.sk.groupby(['season','pos']):
            self.LX[(s,pos)]=dict(x60=d.ixg.sum()/d.toi.sum()*3600, f60=d.fen.sum()/d.toi.sum()*3600)
        self.TL={s:dict(xg=d.xgf.mean()) for s,d in self.tg.groupby('season')}
    def build(self, pid, team, opp, home, date, season, pos_hint='F', role_override=None):
        f=super().build(pid,team,opp,home,date,season,pos_hint,role_override)
        pos='D' if f['is_d'] else 'F'
        lx=self.LX.get((season-1,pos)) or self.LX.get((season,pos))
        P=self.P.get(pid); A=self.X.get(pid)
        z=np.zeros(7)
        if P is None:
            cur=prev=prev2=l10=z; n10=0
        else:
            d=P['date']; s=P['season']; i=bisect.bisect_left(d,date)
            cm=(s[:i]==season); C=A[:i][cm]
            cur=C.sum(0) if len(C) else z; l10=C[-10:].sum(0) if len(C) else z; n10=min(len(C),10)
            prev=A[s==season-1].sum(0) if (s==season-1).any() else z
            prev2=A[s==season-2].sum(0) if (s==season-2).any() else z
        ptoi=prev[6]+0.5*prev2[6]; px=prev[0]+0.5*prev2[0]; pf=prev[1]+0.5*prev2[1]
        K=300*60
        prior_x60=(px+K*lx['x60']/3600)/(ptoi+K)*3600
        prior_f60=(pf+K*lx['f60']/3600)/(ptoi+K)*3600
        W=400*60
        x60=(cur[0]+W*prior_x60/3600)/(cur[6]+W)*3600
        f60=(cur[1]+W*prior_f60/3600)/(cur[6]+W)*3600
        # finishing: goals minus ixG per unit ixG over prev2 + prev + cur, shrunk with 15 xG pseudo
        tg_=cur[4]+prev[4]+0.5*prev2[4]; tx_=cur[0]+prev[0]+0.5*prev2[0]
        fin=(tg_+15)/(tx_+15)
        # recent form: last 10 games, shrunk to season-blended rate with 150 min pseudo
        RW=150*60
        r_g60=(l10[4]+RW*f['g60']/3600)/(l10[6]+RW)*3600
        r_s60=(l10[5]+RW*f['s60']/3600)/(l10[6]+RW)*3600
        r_x60=(l10[0]+RW*x60/3600)/(l10[6]+RW)*3600
        # team / opponent xG per game, shrunk to league with 10 games
        tl=self.TL.get(season-1) or self.TL.get(season)
        def tx(t, col, last=None):
            M=self.TM.get(t); TX=self.TX.get(t)
            if M is None: return tl['xg'], tl['xg']
            i=bisect.bisect_left(M['date'],date); cm=M['season'][:i]==season; R=TX[:i][cm]
            v=(R[:,col].sum()+10*tl['xg'])/(len(R)+10)
            R10=R[-10:]; v10=(R10[:,col].sum()+10*v)/(len(R10)+10)
            return v, v10
        opp_xga,opp_xga10=tx(opp,1); tm_xgf,_=tx(team,0)
        # opponent recent save% (last 10 games), shrunk
        M=self.TM.get(opp)
        if M is not None:
            i=bisect.bisect_left(M['date'],date); cm=M['season'][:i]==season; R=self.TX[opp][:i][cm][-10:]
            opp_sv10=1-(R[:,2].sum()+300*(1-f['opp_sv']))/(R[:,3].sum()+300)
        else: opp_sv10=f['opp_sv']
        opp_xf=opp_xga/tl['xg']
        lam_ix=x60*f['toi_hat']/60*opp_xf*(1.03 if home else 0.97)*fin
        f.update(x60=x60,f60=f60,prior_x60=prior_x60,fin=fin,r_g60=r_g60,r_s60=r_s60,r_x60=r_x60,n10=n10,
                 opp_xga=opp_xga,opp_xga10=opp_xga10,tm_xgf=tm_xgf,opp_sv10=opp_sv10,lam_ix=lam_ix,
                 pp_share=f['pp_hat']/max(f['toi_hat'],1))
        return f
