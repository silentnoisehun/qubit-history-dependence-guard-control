# OFFLINE ASSUMED-MODEL simulation (not hardware). Carryover toy: residual excitation e_i = eb + c0*[pred==S]*exp(-gap/tau).
import json, math, sys, numpy as np
from scipy import stats
from toy_model import mcell, GAM
from analyzer3 import analyze_session
from v3_design import slot_table
rng=np.random.default_rng(777)
RET=0.96; EB=0.01; SH=166
def block_slots(kind,k):
    s=[slot_table(k)[:36],slot_table(k)[36:]]
    for v in s:
        for x in v:
            if kind=='A': x['g_us']=250.0
            elif kind in('B','C'):
                x['g_us']={'L':1000.0,'S':250.0,None:None}[x['gap']] if kind=='B' else 1000.0
    return s
DT=[0.0]
def gam(arm,rest):
    g=-math.log(0.60)/220.0   # survival 0.60 at probe, as in sim_alloc_332
    return g if arm=='S' else g*math.exp(0.25+(DT[0] if rest==0 else 0.0))
def simblock(kind,k,c0,tau):
    s=block_slots(kind,k); cnt={}; rows=[]
    for v in s:
        for x in v:
            e=EB
            if x['pred']=='S' and x['g_us'] is not None: e+=c0*math.exp(-(x['g_us']+2.7)/tau)
            p=mcell(e,x['rest'],gam(x['arm'],x['rest']),x['cell'])
            n=rng.binomial(SH,RET); ones=rng.binomial(n,p)
            rows.append((x,n,ones))
    return rows
def pool(rows,sel=lambda x:True):
    sc={a:{} for a in 'SI'}
    for x,n,ones in rows:
        if not sel(x): continue
        d=sc[x['arm']].setdefault(x['rest'],{}).setdefault(x['cell'],{'00':0,'10':0,'01':0,'11':0})
        d['10']+=ones; d['00']+=n-ones
    return sc
def Dk(rows,sel=lambda x:True):
    try: return analyze_session(pool(rows,sel))['D_k']
    except Exception: return float('nan')
def diag(allrows):
    # G0 predecessor contrast, stratified (arm,rest,gapclass-by-g_us); returns {gap: (delta,var)}
    acc={}
    for rows in allrows:
        for x,n,ones in rows:
            if x['cell']!='G0' or x['pred'] is None: continue
            key=(x['arm'],x['rest'],x['g_us'],x['pred']); a=acc.setdefault(key,[0,0]); a[0]+=ones; a[1]+=n
    out={}
    gaps=sorted(set(k[2] for k in acc))
    for g in gaps:
        num=den=0
        for arm in 'SI':
            for r in (0.0,16.0,64.0):
                a=acc.get((arm,r,g,'S')); b=acc.get((arm,r,g,'I'))
                if not a or not b or a[1]==0 or b[1]==0: continue
                pa,pb=a[0]/a[1],b[0]/b[1]; v=max(pa*(1-pa),1e-4)/a[1]+max(pb*(1-pb),1e-4)/b[1]
                num+=(pa-pb)/v; den+=1/v
        out[g]=(num/den,1/den) if den else (float('nan'),float('nan'))
    return out
def run(kind,nb,c0,tau,R):
    Ds=[];sig=0;res=[];z1=[];zd=[];Dl=[];Ds_=[];zdiff=[]
    for r in range(R):
        rows=[simblock(kind,k,c0,tau) for k in range(nb)]
        d=np.array([Dk(x) for x in rows])
        if np.isnan(d).any(): continue
        m=d.mean(); se=d.std(ddof=1)/math.sqrt(nb); t=stats.t.ppf(.975,nb-1)
        res.append((m,m-t*se>0 or m+t*se<0,m+t*se<0.08))
        dg=diag(rows); gs=sorted(dg)
        zs=[dg[g][0]/math.sqrt(dg[g][1]) for g in gs]
        z1.append(zs)
        if len(gs)==2:
            zdiff.append((dg[gs[0]][0]-dg[gs[1]][0])/math.sqrt(dg[gs[0]][1]+dg[gs[1]][1]))
    ms=np.array([r_[0] for r_ in res]); sg=np.mean([r_[1] for r_ in res]); up=np.mean([r_[2] for r_ in res])
    out=dict(upper_lt_0p08=float(up),D_mean=float(ms.mean()),D_sd=float(ms.std()),ci_excl0=float(sg),n=len(res))
    zs=np.array(z1); out['diag_z_by_gap']=[float(np.mean(zs[:,i])) for i in range(zs.shape[1])]
    out['diag_detect_rate_by_gap']=[float(np.mean(np.abs(zs[:,i])>1.96)) for i in range(zs.shape[1])]
    if zdiff: out['dose_resp_detect']=float(np.mean(np.abs(zdiff)>1.96))
    return out
def power():
    for kind,nb in (('A',16),('B',16)):
        for Dt in (0.0,0.08,0.15):
            DT[0]=Dt; print('POWER',kind,nb,'Dtrue',Dt,run(kind,nb,0.0,162,600),flush=True)
    DT[0]=0.0
if __name__=="__main__" and len(sys.argv)>2:
    power(); sys.exit()
if __name__=="__main__":
    R=int(sys.argv[1]) if len(sys.argv)>1 else 150
    for kind,nb in (('A',16),('B',16),('C',10)):
        for c0,tau in ((0,162),(0.01,162),(0.03,162),(0.1,162),(0.03,1000),(0.1,1000)):
            print(kind,nb,'c0',c0,'tau',tau,run(kind,nb,c0,tau,R),flush=True)