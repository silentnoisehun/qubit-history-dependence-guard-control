"""Offline analysis for v3 block logs. PRIMARY = unchanged analyzer3.analyze_campaign on counts pooled over all slots
(closed Scope-A endpoint). Everything else is DESCRIPTIVE / EXPLORATORY, no decision rule, no mechanism claim.
block = {'k': int, 'counts': [ [ {'c1c0': n} x36 ] for variant 0, same for variant 1 ]}  (c1 = final readout, c0 = herald)"""
import math
import numpy as np
from scipy import stats
from analyzer3 import analyze_session, analyze_campaign
from v3_design import slot_table

def _inst(block):
    """yields (slot_dict, counts_dict) for every segment instance of the block."""
    tab = slot_table(block["k"]); it = iter(tab)
    for v in (0, 1):
        for i in range(36):
            yield next(it), block["counts"][v][i]

def pooled(block, sel=lambda x: True):
    sc = {a: {} for a in "SI"}
    for x, cnt in _inst(block):
        if not sel(x): continue
        d = sc[x["arm"]].setdefault(float(x["rest"]), {}).setdefault(x["cell"], {"00": 0, "10": 0, "01": 0, "11": 0})
        for k, n in cnt.items(): d[k] += int(n)
    return sc

def primary(blocks):
    return analyze_campaign([pooled(b) for b in blocks])

def d_by_gap(blocks):
    """Descriptive: per-block D_k from instances with long / short preceding gap (about half the shots each)."""
    out = {}
    for g in ("S", "L"):
        ds = []
        for b in blocks:
            try: ds.append(analyze_session(pooled(b, lambda x, g=g: x["gap"] == g))["D_k"])
            except Exception: ds.append(float("nan"))
        ds = np.array(ds, float); ok = ds[~np.isnan(ds)]
        m = float(ok.mean()) if len(ok) else float("nan")
        se = float(ok.std(ddof=1) / math.sqrt(len(ok))) if len(ok) > 1 else float("nan")
        t = stats.t.ppf(.975, len(ok) - 1) if len(ok) > 1 else float("nan")
        out[g] = dict(n_valid=int(len(ok)), n_nan=int(np.isnan(ds).sum()), mean=m, se=se, ci95=[m - t * se, m + t * se])
    return out

def g0_pred_contrast(blocks):
    """Descriptive: G0-cell final-readout rate after predecessor S minus after predecessor I, stratified by (own arm, rest),
    inverse-variance combined per gap class. Positive = more '1' after an S predecessor. Normal-approximation z, not a test rule."""
    acc = {}
    for b in blocks:
        for x, cnt in _inst(b):
            if x["cell"] != "G0" or x["pred"] is None: continue
            ones = int(cnt.get("10", 0)); ret = ones + int(cnt.get("00", 0))
            a = acc.setdefault((x["arm"], x["rest"], x["gap"], x["pred"]), [0, 0]); a[0] += ones; a[1] += ret
    res = {}
    for g in ("S", "L"):
        num = den = 0.0
        for arm in "SI":
            for r in (0.0, 16.0, 64.0):
                a = acc.get((arm, r, g, "S")); b = acc.get((arm, r, g, "I"))
                if not a or not b or a[1] == 0 or b[1] == 0: continue
                pa, pb = a[0] / a[1], b[0] / b[1]
                v = max(pa * (1 - pa), 1e-4) / a[1] + max(pb * (1 - pb), 1e-4) / b[1]
                num += (pa - pb) / v; den += 1 / v
        res[g] = dict(delta=num / den, se=math.sqrt(1 / den), z=num / den * math.sqrt(den)) if den else None
    if res["S"] and res["L"]:
        dd = res["S"]["delta"] - res["L"]["delta"]; se = math.sqrt(res["S"]["se"] ** 2 + res["L"]["se"] ** 2)
        res["short_minus_long"] = dict(delta=dd, se=se, z=dd / se)
    return res

def descriptive_only(blocks):
    """Incomplete or non-contiguous campaign: NO preregistered CI/categorisation. Point values only."""
    ds = []
    for b in blocks:
        try: ds.append(analyze_session(pooled(b))["D_k"])
        except Exception: ds.append(float("nan"))
    return dict(NOTE="INCOMPLETE campaign: descriptive only, NOT the preregistered analysis; no CI, no A/B/C category",
                blocks_present=[b["k"] for b in blocks], per_block_D_k=[float(x) for x in ds],
                exploratory_G0_predecessor_contrast_point_values=g0_pred_contrast(blocks))

def is_complete(blocks):
    return sorted(b["k"] for b in blocks) == list(range(16))

def report(blocks):
    if not is_complete(blocks): return descriptive_only(blocks)
    blocks = sorted(blocks, key=lambda b: b["k"])
    p = primary(blocks)
    lo, hi = p["ci_95"]
    return dict(primary=dict(status=p["status"], n_blocks=p["n_sessions"], D_bar=p["D_bar"], ci_95=p["ci_95"]),
                interpretation_proposal=("A: CI excludes 0 (nonzero contrast observed in this run; mechanism/carryover/population not established)" if lo > 0 or hi < 0 else
                                         "B: CI includes 0 and upper bound < +0.08 (no evidence of an effect as large as +0.08 in this run)" if hi < 0.08 else
                                         "C: CI includes 0 and +0.08 (inconclusive)") if p["status"] != "ERVENYTELEN" else "INVALID (NaN D_k), see primary",
                exploratory_D_by_gap_class=d_by_gap(blocks), exploratory_G0_predecessor_contrast=g0_pred_contrast(blocks))