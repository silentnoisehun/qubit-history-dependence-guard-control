#!/usr/bin/env python3
"""Gumija-2 v3 runner. Modes (exactly one):
  --plan                 offline FakeMarrakesh snapshot (add --live to read the live target; still NO job): builds + transpiles
                         both gap patterns, prints durations and the circuit-time budget. No submission.
  --submit --block K     (needs --live) submits EXACTLY ONE Sampler job (block K, 2 circuits x 166 shots), waits, writes
                         runs/block_KK.json. Only the next unrun block index is accepted. One job per invocation, no loop.
  --collect JOBID --block K   (needs --live) fetches the result of an already submitted block job and writes the log.
  --analyze              offline: reads runs/block_*.json; full report only when exactly blocks 0..15 are present, else descriptive only.
  --refresh-usage        (needs --live) re-reads job metrics for logged blocks whose usage was still pending.
Account: the owner's saved account (QiskitRuntimeService()). Nothing is printed or stored about keys/instances.
Parameters guard 250 us (S) / 1000 us (L), 166 shots/PUB, plain measure, default rep_delay/init_qubits are PROPOSALS (prereg pending)."""
import argparse, glob, json, os, sys, time, warnings
warnings.filterwarnings("ignore")
from datetime import datetime, timezone
from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager
from config import Gumija2ThreeRestConfig
from v3_design import block_design, N_BLOCKS, SHOTS_PER_PUB, load_orders
from unrolled_v3 import delays_v3, build_v3, GUARD_LONG_US
from unrolled_proto import GUARD_US

RUNS = "runs"
def log_path(k): return os.path.join(RUNS, f"block_{k:02d}.json")
def existing_blocks():
    return sorted(int(os.path.basename(p)[6:8]) for p in glob.glob(os.path.join(RUNS, "block_*.json")))

def isa_circuits(k, backend, cfg, D=None):
    D = D or delays_v3(cfg, backend)
    pm = generate_preset_pass_manager(optimization_level=cfg.optimization_level, backend=backend,
                                      initial_layout=list(cfg.initial_layout), scheduling_method=cfg.scheduling_method)
    return [pm.run(build_v3(d["order"], d["gaps"], D)) for d in block_design(k)], D

def plan(backend, cfg):
    tot = 0.0; rows = []
    for k in (0, 1):
        circs, D = isa_circuits(k, backend, cfg)
        for v, c in enumerate(circs):
            us = float(c.estimate_duration(backend.target, unit="s")) * 1e6
            rows.append((k, v, round(us, 3)))
    avg = sum(r[2] for r in rows) / len(rows)
    per_block_s = 2 * SHOTS_PER_PUB * avg * 1e-6
    print("guard_short_dt", D["guard_short_dt"], "guard_long_dt", D["guard_long_dt"], "stress/probe/rest", D["stress_dt"], D["probe_dt"], D["rest_dt"])
    for r in rows: print("pattern block%d variant%d duration_us=%s" % r)
    print("circuit time per block ~ %.2f s ; %d blocks ~ %.1f s (circuit execution only; per-job overhead, chunking, rep_delay NOT included)" % (per_block_s, N_BLOCKS, per_block_s * N_BLOCKS))
    return rows

def extract(result):
    counts = []
    for p in range(2):
        data = result[p].data
        counts.append([dict(getattr(data, f"seg{i:02d}").get_counts()) for i in range(36)])
    return counts

def default_submit(backend, circuits, shots):
    from qiskit_ibm_runtime import SamplerV2 as Sampler
    sampler = Sampler(mode=backend)
    return sampler.run([(c,) for c in circuits], shots=shots)

def write_log(k, job, counts, extra):
    os.makedirs(RUNS, exist_ok=True)
    rec = dict(block=k, k=k, job_id=job.job_id() if callable(getattr(job, "job_id", None)) else str(job),
               written_utc=datetime.now(timezone.utc).isoformat(), shots_per_pub=SHOTS_PER_PUB, counts=counts, **extra)
    p = log_path(k)
    assert not os.path.exists(p), "log exists, refusing to overwrite"
    json.dump(rec, open(p, "w")); return p

def _spans(result):
    try:
        sp = result.metadata["execution"]["execution_spans"]
    except Exception as e:
        return f"UNAVAILABLE ({type(e).__name__})"
    out = []
    try:
        for i in range(len(sp)):
            s = sp[i]
            try: out.append(dict(start=str(s.start), stop=str(s.stop), duration_s=float(s.duration), size=int(s.size)))
            except Exception: out.append(str(s))
    except Exception as e:
        return f"UNAVAILABLE ({type(e).__name__})"
    return out

def usage_info(job, result=None, polls=6, wait_s=10):
    """Source: RuntimeJobV2.metrics() (usage dict incl. status and qpu_charge_time_seconds; usage() itself returns 0 while pending)
    and result.metadata['execution']['execution_spans'] where present. Missing parts are recorded as UNAVAILABLE, never guessed."""
    info = {"metrics": None, "usage_status": "UNAVAILABLE", "usage_seconds": None}
    for n in range(polls):
        try:
            m = json.loads(json.dumps(job.metrics(), default=str)); info["metrics"] = m
            u = (m or {}).get("usage", {}) or {}
            info["usage_status"] = u.get("status", "UNAVAILABLE")
            info["usage_seconds"] = u.get("qpu_charge_time_seconds")
            if info["usage_status"] not in ("pending", "UNAVAILABLE"): break
        except Exception as e:
            info["metrics_error"] = type(e).__name__
        if n < polls - 1: time.sleep(wait_s)
    try: res = result if result is not None else job.result(); info["execution_spans"] = _spans(res)
    except Exception as e: info["execution_spans"] = f"UNAVAILABLE ({type(e).__name__})"
    return info

def validate_counts(counts):
    assert len(counts) == 2 and all(len(c) == 36 for c in counts), "unexpected result shape"
    for c in counts:
        for d in c:
            assert sum(d.values()) == SHOTS_PER_PUB, "unexpected shot count in a register"

def submit_block(k, backend, cfg, submit_fn=default_submit, wait=True):
    done = existing_blocks()
    assert k == len(done) and k < N_BLOCKS and done == list(range(len(done))), f"next block must be {len(done)}, got {k}"
    circs, D = isa_circuits(k, backend, cfg)
    jpath = os.path.join(RUNS, f"block_{k:02d}.jobid"); os.makedirs(RUNS, exist_ok=True)
    assert not os.path.exists(jpath), "a job id file already exists for this block: use --collect"
    job = submit_fn(backend, circs, SHOTS_PER_PUB)
    open(jpath, "w").write(job.job_id() if callable(getattr(job, "job_id", None)) else str(job))
    print("submitted block", k, "job", open(jpath).read())
    if not wait: return None
    res = job.result(); counts = extract(res); validate_counts(counts)
    extra = usage_info(job, res); extra["versions"] = _versions(); extra["backend"] = getattr(backend, "name", "?")
    p = write_log(k, job, counts, extra); print("wrote", p, "usage_status:", extra.get("usage_status"), "usage_seconds:", extra.get("usage_seconds"))
    cum = _cumulative_usage(); print("cumulative usage_seconds over logged blocks:", cum)
    return p

def _versions():
    import qiskit; v = {"qiskit": qiskit.__version__}
    try:
        import qiskit_ibm_runtime; v["qiskit_ibm_runtime"] = qiskit_ibm_runtime.__version__
    except Exception: pass
    return v

def _cumulative_usage():
    t = 0.0; ok = True
    for k in existing_blocks():
        L = json.load(open(log_path(k))); u = L.get("usage_seconds")
        if isinstance(u, (int, float)) and L.get("usage_status") not in ("pending", "UNAVAILABLE", None): t += u
        else: ok = False
    return {"seconds": t, "complete": ok}

def analyze():
    from analysis_v3 import report
    blocks = [json.load(open(log_path(k))) for k in existing_blocks()]
    if not blocks: print("no blocks"); return
    print("blocks:", len(blocks), "of", N_BLOCKS, "(the preregistered CI/categories are printed only for exactly", N_BLOCKS, "contiguous complete blocks)")
    print(json.dumps(report(blocks), indent=1, default=str))

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--plan", action="store_true"); g.add_argument("--submit", action="store_true")
    g.add_argument("--collect", metavar="JOBID"); g.add_argument("--analyze", action="store_true"); g.add_argument("--refresh-usage", dest="refresh_usage", action="store_true")
    ap.add_argument("--live", action="store_true"); ap.add_argument("--block", type=int)
    a = ap.parse_args(); cfg = Gumija2ThreeRestConfig()
    if a.analyze: return analyze()
    if a.plan and not a.live:
        from qiskit_ibm_runtime.fake_provider import FakeMarrakesh
        print("[OFFLINE FakeMarrakesh snapshot, no service]"); return plan(FakeMarrakesh(), cfg)
    if not a.live: sys.exit("--submit/--collect need --live")
    from qiskit_ibm_runtime import QiskitRuntimeService
    backend = QiskitRuntimeService().backend(cfg.backend_name)
    if "fake" in type(backend).__name__.lower() or getattr(backend, "simulator", False): sys.exit("not a device backend")
    if a.plan: print("[LIVE target read, no job]"); return plan(backend, cfg)
    if a.refresh_usage: return refresh_usage(QiskitRuntimeService())
    if a.block is None: sys.exit("--block K required")
    if a.submit: return submit_block(a.block, backend, cfg)
    return collect(QiskitRuntimeService(), a.collect, a.block)

def collect(service, jobid, k):
    assert k is not None and 0 <= k < N_BLOCKS, "valid --block required"
    done = existing_blocks()
    jp = os.path.join(RUNS, f"block_{k:02d}.jobid")
    assert k == len(done) and done == list(range(len(done))), f"next unlogged block is {len(done)}, got {k}"
    assert os.path.exists(jp), "no persisted job id for this block: stopping (unknown recovery is not guessed)"
    assert open(jp).read().strip() == jobid, "JOBID does not match the persisted id of this block: stopping"
    job = service.job(jobid); res = job.result(); counts = extract(res); validate_counts(counts)
    extra = usage_info(job, res); extra["versions"] = _versions()
    print("wrote", write_log(k, job, counts, extra))

def refresh_usage(service):
    for k in existing_blocks():
        L = json.load(open(log_path(k)))
        if L.get("usage_status") in ("pending", "UNAVAILABLE", None):
            info = usage_info(service.job(L["job_id"]), polls=1)
            L.update({x: info[x] for x in ("metrics", "usage_status", "usage_seconds")}); json.dump(L, open(log_path(k), "w"))
            print("block", k, info["usage_status"], info["usage_seconds"])
    print("cumulative:", _cumulative_usage())

if __name__ == "__main__":
    main()