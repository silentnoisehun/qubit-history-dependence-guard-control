"""Gumija-2 v3 circuit builder: like unrolled_proto.build, but each inter-segment guard is class S or L.
Needs config.py, circuits3.py, unrolled_proto.py (same folder). No backend access except the object passed in."""
import warnings
warnings.filterwarnings("ignore")
from qiskit import QuantumCircuit, ClassicalRegister, QuantumRegister
from qiskit.circuit import Delay
from circuits3 import extract_timing_constraints, quantize_delay_us, compute_stress_delay_dt
from unrolled_proto import segment, delays_dt, GUARD_US

GUARD_LONG_US = 1000.0   # proposal only, NOT approved

def delays_v3(cfg, backend):
    D = delays_dt(cfg, backend)
    q = lambda us: quantize_delay_us(us, D["timing"], cfg.delay_rounding_mode).actual_dt
    D["guard_short_dt"] = int(q(GUARD_US)); D["guard_long_dt"] = int(q(GUARD_LONG_US))
    return D

def build_v3(order, gaps, D):
    assert len(order) == len(gaps) == 36
    regs = [ClassicalRegister(2, f"seg{i:02d}") for i in range(len(order))]
    qc = QuantumCircuit(QuantumRegister(2, "q"), *regs)
    for i, (a, r, c) in enumerate(order):
        segment(qc, regs[i], a, r, c, D)
        qc.reset(0); qc.reset(1)
        if i < len(order) - 1:
            g = gaps[i + 1]            # class of the gap BEFORE slot i+1
            dt = D["guard_long_dt"] if g == "L" else D["guard_short_dt"]
            qc.append(Delay(dt, "dt"), [0]); qc.append(Delay(dt, "dt"), [1])
        qc.barrier(0, 1)
    return qc