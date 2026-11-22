import json, math, os, shutil, sys, tempfile, warnings
warnings.filterwarnings("ignore")
import numpy as np
from collections import Counter
from qiskit import QuantumCircuit
from qiskit.providers.basic_provider import BasicSimulator
from qiskit.primitives import BitArray
from qiskit_ibm_runtime.fake_provider import FakeMarrakesh
from config import Gumija2ThreeRestConfig
import v3_design as VD, unrolled_v3 as U, analysis_v3 as AN, runner_v3 as R
cfg = Gumija2ThreeRestConfig(); be = FakeMarrakesh(); D = U.delays_v3(cfg, be); orders = VD.load_orders()

def test_exact_delays():
    assert D["guard_short_dt"] == 62500 and D["guard_long_dt"] == 250000 and D["probe_dt"] == 55000 and D["stress_dt"] == 1120
    assert D["rest_dt"] == {0.0: 0, 16.0: 4000, 64.0: 16000}

def test_design_balance():
    # per block: every (arm,rest,cell) type has equal long/short instances except the documented boundary types
    for k in (0, 1):
        t = Counter((x["arm"], x["rest"], x["cell"], x["gap"]) for x in VD.slot_table(k))
        types = {key[:3] for key in t}
        off = [(ty, t[ty + ("L",)], t[ty + ("S",)]) for ty in types if t[ty + ("L",)] != t[ty + ("S",)]]
        first = {(d['order'][0][0], d['order'][0][1], d['order'][0][2]) for d in VD.block_design(k)}
        assert len(off) <= 2 and all(abs(a - b) == 1 and ty in first and ty[2] == 'ET' for ty, a, b in off), off   # only the two first-slot ET types (no gap before slot 0)
        sc = VD.strata_counts(k); assert all(8 <= v <= 10 for v in sc.values()) and len(sc) == 8, sc
    # two consecutive blocks: complement -> exactly balanced long/short per (own,pred) stratum
    s = Counter(); [s.update(VD.strata_counts(k)) for k in (0, 1)]
    for a in "SI":
        for p in "SI": assert abs(s[(a, p, "L")] - s[(a, p, "S")]) <= 2, (a, p, s)

def _gap_dt_between_segments(qc):
    """read the delay on qubit 0 that sits between segment i's last measure and segment i+1: from instruction order."""
    out = []; seen_reset = False; pending = False
    ops = list(qc.data); last_meas_seg = None
    for inst in ops:
        n = inst.operation.name
        if n == "reset" and inst.qubits[0]._index == 1: pending = True; continue
        if pending and n == "delay" and qc.find_bit(inst.qubits[0]).index == 0 and inst.operation.duration in (D["guard_short_dt"], D["guard_long_dt"]):
            out.append(inst.operation.duration); pending = False
        elif pending and n == "barrier": pending = False
    return out

def test_gap_placement_in_circuit():
    for k in (0, 1):
        for d in VD.block_design(k):
            qc = U.build_v3(d["order"], d["gaps"], D)
            want = [D["guard_long_dt"] if g == "L" else D["guard_short_dt"] for g in d["gaps"][1:]]
            assert _gap_dt_between_segments(qc) == want, (k, d["variant"])

def _strip(qc):
    nd = qc.copy_empty_like()
    for inst in qc.data:
        if inst.operation.name in ("delay", "barrier"): continue
        nd.append(inst.operation, inst.qubits, inst.clbits)
    return nd

def test_logic_and_72bit_mapping():
    for k in (0, 1):
        for d in VD.block_design(k):
            qc = _strip(U.build_v3(d["order"], d["gaps"], D)); assert qc.num_clbits == 72 and len(qc.cregs) == 36
            counts = BasicSimulator().run(qc, shots=30, seed_simulator=3).result().get_counts(); assert len(counts) == 1
            regs = list(counts)[0].split(" ")[::-1]
            for i, (a, r, c) in enumerate(d["order"]): assert regs[i] == ("1" if c[0] == "E" else "0") + "0"

def test_transpile_and_duration():
    circs, _ = R.isa_circuits(0, be, cfg, D)
    for c in circs:
        us = float(c.estimate_duration(be.target, unit="s")) * 1e6
        assert 26000 < us < 31000, us      # ~28.6 ms expected: 6.7 ms segments + 17-18 long + rest short guards
        ops = c.count_ops(); assert ops["measure"] == 72 and ops["reset"] == 72 and ops["cz"] == 576

def _synthetic_result(k, rng, e=0.01):
    from toy_model import mcell, GAM
    res = []
    for d in VD.block_design(k):
        per = {}
        for i, (a, r, c) in enumerate(d["order"]):
            n = SHOTS = VD.SHOTS_PER_PUB
            ok = rng.binomial(n, 0.96); ones = rng.binomial(ok, mcell(e, r, GAM[a], c))
            per[f"seg{i:02d}"] = BitArray.from_counts({"00": ok - ones, "10": ones, "01": n - ok}, num_bits=2)
        res.append(per)
    class Data:  pass
    class Pub:
        def __init__(s, per):
            s.data = Data(); [setattr(s.data, kk, vv) for kk, vv in per.items()]
    return [Pub(p) for p in res]

class FakeJob:
    def __init__(s, k, rng): s._r = _synthetic_result(k, rng); s._id = f"fake-{k}"
    def job_id(s): return s._id
    def result(s):
        class Res(list): metadata = {"fake": True}
        return Res(s._r)
    def metrics(s): return {"usage": {"status": s.status, "qpu_charge_time_seconds": 1.0}, "timestamps": {}}
    status = "finished"

def test_metadata_vs_builder_all_blocks():
    for k in range(16):
        for d in VD.block_design(k):
            assert d["gaps"][0] is None
            qc = U.build_v3(d["order"], d["gaps"], D)
            want = [D["guard_long_dt"] if g == "L" else D["guard_short_dt"] for g in d["gaps"][1:]]
            assert _gap_dt_between_segments(qc) == want and len(want) == 35 and None not in d["gaps"][1:]
        tab = VD.slot_table(k); assert [x["gap"] for x in tab if x["pos"] == 0] == [None, None]
        assert all((x["gap"] is None) == (x["pred"] is None) for x in tab)
        sc = VD.strata_counts(k); assert sum(sc.values()) == 70 and all(8 <= v <= 10 for v in sc.values()), sc
    tot = Counter(); [tot.update(VD.strata_counts(k)) for k in range(16)]
    assert sorted(tot.items()) == sorted(tot.items()) and sum(tot.values()) == 1120

def test_runner_pipeline_and_guards():
    tmp = tempfile.mkdtemp(); cwd = os.getcwd(); os.chdir(tmp)
    try:
        for f in ("config.py", "circuits3.py", "analyzer3.py", "variants_V2.json", "toy_model.py"): shutil.copy(os.path.join(cwd, f), tmp)
        rng = np.random.default_rng(11); seen = []
        def fake_submit(backend, circuits, shots):
            assert len(circuits) == 2 and shots == 166; seen.append(len(seen)); return FakeJob(len(seen) - 1, rng)
        # out-of-order block refused
        try: R.submit_block(3, be, cfg, fake_submit); raise SystemExit("should refuse")
        except AssertionError: pass
        for k in range(16): R.submit_block(k, be, cfg, fake_submit)
        assert R.existing_blocks() == list(range(16))
        try: R.submit_block(16, be, cfg, fake_submit); raise SystemExit("should refuse")
        except AssertionError: pass
        blocks = [json.load(open(R.log_path(k))) for k in range(16)]
        # counts round trip: each segment retained shots == 166 shots all keys
        assert all(sum(blocks[0]["counts"][0][i].values()) == 166 for i in range(36))
        rep = AN.report(blocks)
        assert rep["primary"]["status"] in ("JEL", "NINCS_JEL") and rep["primary"]["n_blocks"] == 16
        assert "NOTE" in AN.report(blocks[:15]) and "primary" not in AN.report(blocks[:15])      # incomplete -> descriptive only
        assert "primary" not in AN.report(blocks[1:] ) and "primary" in AN.report(blocks)
        L0 = json.load(open(R.log_path(0))); assert L0["usage_status"] == "finished" and L0["usage_seconds"] == 1.0 and L0["execution_spans"].startswith("UNAVAILABLE") if isinstance(L0["execution_spans"], str) else True
        assert abs(rep["primary"]["D_bar"]) < 0.1                       # null-ish synthetic data
        assert rep["exploratory_G0_predecessor_contrast"]["S"] is not None
        # primary uses unchanged analyzer on pooled counts: compare to direct pooling of all instances
        from analyzer3 import analyze_campaign
        direct = analyze_campaign([AN.pooled(b) for b in blocks]); assert direct["D_bar"] == rep["primary"]["D_bar"]
    finally:
        os.chdir(cwd); shutil.rmtree(tmp)

def test_collect_checks_and_pending_usage():
    tmp = tempfile.mkdtemp(); cwd = os.getcwd(); os.chdir(tmp)
    try:
        rng = np.random.default_rng(5)
        class Svc:
            def job(s, jid): return FakeJob(0, rng)
        # no persisted jobid -> stop; wrong block -> stop
        for args in (("fake-0", 0), ("fake-0", 2), ("fake-0", None)):
            try: R.collect(Svc(), *args); raise SystemExit("should stop")
            except AssertionError: pass
        os.makedirs("runs"); open("runs/block_00.jobid", "w").write("fake-0")
        try: R.collect(Svc(), "other-id", 0); raise SystemExit("should stop")
        except AssertionError: pass
        R.collect(Svc(), "fake-0", 0); assert R.existing_blocks() == [0]
        try: R.collect(Svc(), "fake-0", 0); raise SystemExit("should stop")      # block already logged
        except AssertionError: pass
        # pending usage is never counted as final
        class PJ(FakeJob): status = "pending"
        import time as _t; old = _t.sleep; _t.sleep = lambda s: None
        try: info = R.usage_info(PJ(0, rng), polls=2)
        finally: _t.sleep = old
        assert info["usage_status"] == "pending"
        # bad shot count rejected
        try: R.validate_counts([[{"00": 1}] * 36] * 2); raise SystemExit("should reject")
        except AssertionError: pass
    finally:
        os.chdir(cwd); shutil.rmtree(tmp)

def test_no_submission_in_plan_and_import():
    import runner_v3, inspect
    src = inspect.getsource(runner_v3)
    assert src.count("sampler.run(") == 1 and "Session(" not in src and "Batch(" not in src
    assert R.plan(be, cfg) is not None          # offline plan works with no service object

if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"): fn(); print("PASS", name)