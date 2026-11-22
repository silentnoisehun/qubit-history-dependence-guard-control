# TOY, assumed numbers, NOT physics validation. Question: how much does a predecessor-arm carryover leak into D under NULL (no intrinsic history effect)?
import numpy as np, math, itertools, random
RESTS=(0,16,64); CELLS=('E0','G0','GT','ET','ET','ET')
SEGS=[(a,r,c) for a in 'SI' for r in RESTS for c in CELLS]
G0=1/219.4; KE=5.0; FX=0.999; P10,P01=0.02,0.01; T=220.0
GAM={'S':1/300.0,'I':1/300.0*1.4}   # assumed, same per arm in time-> constant Lambda across rests under null
def mcell(e,rest,gam,cell):
    e=e*math.exp(-KE*G0*rest)
    prep,probe=cell[0],cell[1]; t=T if probe=='T' else 0
    if prep=='E': p=(1-e)*FX*math.exp(-gam*t)+e*(1-FX)*math.exp(-KE*G0*t)
    else: p=e*math.exp(-KE*G0*t)
    return p*(1-P10)+(1-p)*P01
def D_expected(e_by_group):
    # e_by_group[(arm,rest)] = list of initial excitation per cell instance (mean over instances per cell type)
    L={}
    for r in RESTS:
        s={}
        for a in 'SI':
            m={c:np.mean([mcell(e,r,GAM[a],c) for e in e_by_group[(a,r,c)]]) for c in ('E0','G0','GT','ET')}
            s[a]=(m['ET']-m['GT'])/(m['E0']-m['G0'])
        L[r]=math.log(math.log(s['I'])/math.log(s['S']))
    return L[0]-0.5*(L[16]+L[64]), L
def predecessor_e(variants, eb, cS, cI, factor):
    acc={}
    for order in variants:
        for i,(a,r,c) in enumerate(order):
            prev=order[i-1][0] if i>0 else None
            carry=0.0 if prev is None else (cS if prev=='S' else cI)*factor
            acc.setdefault((a,r,c),[]).append(eb+carry)
    return acc
def imbalance(variants):
    # share of S predecessors per (arm,rest) group, pooled over variants
    sh={}
    for order in variants:
        for i,(a,r,c) in enumerate(order):
            if i==0: continue
            sh.setdefault((a,r),[]).append(1 if order[i-1][0]=='S' else 0)
    return max(abs(np.mean(v)-0.5) for v in sh.values())
def blocked():  return [sorted(SEGS,key=lambda x:(x[0]!='S'))]
def alternating():
    S=[s for s in SEGS if s[0]=='S']; I=[s for s in SEGS if s[0]=='I']
    return [[x for p in zip(S,I) for x in p]]
def search(V,seed=1,n=4000):
    rng=random.Random(seed); best=None
    for _ in range(n):
        vs=[rng.sample(SEGS,len(SEGS)) for _ in range(V)]
        im=imbalance(vs)
        if best is None or im<best[0]: best=(im,vs)
    return best