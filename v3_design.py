"""Gumija-2 v3 design: 36-segment circuits, gap-length classes (S = short guard, L = long guard) per slot.
Blocks alternate a gap pattern and its complement; variant 1 uses the mirror-complement of variant 0, so each segment type
gets (nearly) one long-gap and one short-gap instance per block. OFFLINE ONLY, no backend access."""
import json, os
from collections import Counter
HERE = os.path.dirname(os.path.abspath(__file__))
LONG_MOD8 = (0, 3, 5, 6)      # variant-0 slots i (1..35) whose preceding gap is long when i % 8 in this set
N_BLOCKS = 16
SHOTS_PER_PUB = 166            # 2 PUBs per block -> 332 executions per block, 5312 in total

def load_orders(path=None):
    path = path or os.path.join(HERE, "variants_V2.json")
    return [[(t[0], float(t[1]), t[2]) for t in o] for o in json.load(open(path))]

def gap_classes(compl):
    g0 = [None] + [("L" if i % 8 in LONG_MOD8 else "S") for i in range(1, 36)]
    g1 = [None] * 36
    for i in range(1, 36):
        g1[35 - i] = "S" if g0[i] == "L" else "L"
    g1[0] = None                       # slot 0 has no preceding gap in either variant
    g1[35] = "L" if 35 % 8 in LONG_MOD8 else "S"
    out = [g0, g1]
    if compl:
        out = [[None if x is None else ("L" if x == "S" else "S") for x in g] for g in out]
    return out

def block_design(k, orders=None):
    """Returns [ {'variant':v,'order':[(arm,rest,cell)...],'gaps':[None|'S'|'L' x36]} x2 ] for block k (0-based)."""
    orders = orders or load_orders()
    g = gap_classes(k % 2 == 1)
    return [dict(variant=v, order=orders[v], gaps=g[v]) for v in (0, 1)]

def slot_table(k, orders=None):
    rows = []
    for d in block_design(k, orders):
        o = d["order"]
        for i, (a, r, c) in enumerate(o):
            rows.append(dict(variant=d["variant"], pos=i, arm=a, rest=r, cell=c,
                             pred=(o[i - 1][0] if i else None), gap=d["gaps"][i]))
    return rows

def strata_counts(k, orders=None):
    c = Counter()
    for x in slot_table(k, orders):
        if x["pred"]:
            c[(x["arm"], x["pred"], x["gap"])] += 1
    return dict(c)