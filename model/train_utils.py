import numpy as np
from features import FEATS
def X(df):
    x=df[FEATS].copy()
    for c in ['g60','s60','xg60','prior_g60','prior_s60','lam_g','lam_x','sh']: x['log_'+c]=np.log(x[c].clip(1e-3))
    x['log_p_base']=np.log(df.p_base.clip(1e-3)); x['cur_gp']=np.log1p(x['cur_gp']); x['prev_gp']=np.log1p(x['prev_gp'])
    return x
