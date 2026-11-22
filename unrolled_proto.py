#!/usr/bin/env python3
"""Gumija-2 unrolled-segment RESEARCH PROTOTYPE v1 (offline only, NO submission, NO runtime service).
Depends on the v2 project (config.py, circuits3.py). Timing comes from the project's own
extract_timing_constraints / quantize_delay_us / compute_stress_delay_dt on the backend object passed in
(FakeMarrakesh here = a calibration SNAPSHOT, not the live device). Nothing is hardcoded in dt.
Usage (v2 project directory): python unrolled_proto.py variants_V2.json
"""
import sys, json, warnings
from collections import Counter
warnings.filterwarnings("ignore")
from qiskit import QuantumCircuit, ClassicalRegister, QuantumRegister
from qiskit.circuit import Delay
from config import Gumija2ThreeRestConfig
from circuits3 import extract_timing_constraints, quantize_delay_us, compute_stress_delay_dt

GUARD_US = 250.0   # proposal only (approximation of backend default rep_delay between segments), NOT approved

def delays_dt(cfg, backend):
    timing = extract_timing_constraints(backend, cfg, allow_fallback_dt=False)
    q = lambda us: quantize_delay_us(us, timing, cfg.delay_rounding_mode).actual_dt
    stress_dt, _ = compute_stress_delay_dt(cfg, backend)
    return {
        "timing": timing, "stress_dt": int(stress_dt), "probe_dt": q(cfg.probe_time_us),
        "rest_dt": {float(r): q(r) for r in cfg.rest_grid_us}, "guard_dt": q(GUARD_US),
    }

def segment(qc, creg, arm, rest_us, cell, D):
    prep, probe = cell[0], cell[1]
    if arm == "S":
        for _ in range(32): qc.x(0); qc.cz(0, 1); qc.x(0)
    else:
        qc.append(Delay(D["stress_dt"], "dt"), [0]); qc.append(Delay(D["stress_dt"], "dt"), [1])
    qc.barrier(0, 1); qc.measure(0, creg[0]); qc.barrier(0, 1)
    if rest_us > 0:
        qc.append(Delay(D["rest_dt"][float(rest_us)], "dt"), [0]); qc.append(Delay(D["rest_dt"][float(rest_us)], "dt"), [1])
    qc.barrier(0, 1)
    if prep == "E": qc.x(0)
    qc.barrier(0, 1)
    if probe == "T": qc.append(Delay(D["probe_dt"], "dt"), [0])
    qc.barrier(0, 1); qc.measure(0, creg[1])

def build(order, D, guard=True):
    regs = [ClassicalRegister(2, f"seg{i:02d}") for i in range(len(order))]
    qc = QuantumCircuit(QuantumRegister(2, "q"), *regs)
    for i, (a, r, c) in enumerate(order):
        segment(qc, regs[i], a, r, c, D)
        qc.reset(0); qc.reset(1)
        if guard and i < len(order) - 1:
            qc.append(Delay(D["guard_dt"], "dt"), [0]); qc.append(Delay(D["guard_dt"], "dt"), [1])
        qc.barrier(0, 1)
    return qc

def check_variants(vs, cfg):
    types = [(a, float(r), c) for a in "SI" for r in cfg.rest_grid_us for c in cfg.cells]
    for o in vs:
        assert len(o) == 36
        cnt = Counter(tuple(t) for t in o)
        assert all(cnt[t] == (3 if t[2] == "ET" else 1) for t in types), "type multiplicities wrong"
    return True

def load_variants(path):
    return [[(t[0], float(t[1]), t[2]) for t in o] for o in json.load(open(path))]

if __name__ == "__main__":
    from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager
    from qiskit_ibm_runtime.fake_provider import FakeMarrakesh
    cfg = Gumija2ThreeRestConfig(); be = FakeMarrakesh()   # BACKEND OBJECT: replace by a live backend in the owner's environment
    D = delays_dt(cfg, be); print("timing:", D["timing"]); print("delays dt:", {k: D[k] for k in ("stress_dt","probe_dt","rest_dt","guard_dt")})
    vs = load_variants(sys.argv[1]); print("variants ok:", check_variants(vs, cfg), "n:", len(vs))
    pm = generate_preset_pass_manager(optimization_level=0, backend=be, initial_layout=list(cfg.initial_layout), scheduling_method=cfg.scheduling_method)
    for k, o in enumerate(vs):
        tq = pm.run(build(o, D))
        dl = Counter(int(i.operation.duration) for i in tq.data if i.operation.name == "delay")
        print(f"variant {k}: duration_us={tq.estimate_duration(be.target, unit='s')*1e6:.1f} delay_dt_histogram={dict(dl)} ops={dict(tq.count_ops())}")
    print("NOTE: snapshot backend, not live; durations are scheduling estimates, not hardware acceptance; no submission code here.")