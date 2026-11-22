#!/usr/bin/env python3
"""
qubit-gumija2-history-contrast / circuits3.py

Circuit builder and 12-slot / 96-instance session planner for the 3-rest design.
Assumptions:
  - Logical qubit 0 maps to cfg.target_qubit (q21), logical qubit 1 maps to cfg.neighbor_qubit (q20).
  - Classical register has 2 bits: c[0] = mid-circuit herald, c[1] = final readout.
  - Delay quantization uses backend target constraints (dt, granularity, min_length,
    pulse_alignment) according to cfg.delay_rounding_mode; no fixed 16 dt rule is hardcoded.
  - In live mode (allow_fallback_dt=False), missing target.dt raises RuntimeError immediately;
    cfg.fallback_dt_sec is permitted ONLY in explicitly marked offline mode.
  - Scheduled stress_delay_dt is computed strictly from the history interval
    (from the start of the first history operation to the start of the 'end_history'
    barrier via op_start_times), never from Instruction.duration or Circuit.duration.
"""

from dataclasses import dataclass
import math
from typing import Any
from qiskit import QuantumCircuit, transpile
from qiskit.circuit import Delay

from config import Gumija2ThreeRestConfig


@dataclass(frozen=True)
class QuantizedDelayInfo:
    """Records requested vs. quantized hardware delay values in both dt and us."""
    requested_us: float
    actual_dt: int
    actual_us: float
    delta_us: float
    dt_sec: float
    step_dt: int
    min_length_dt: int


def _read_constraint_field(tc_obj: Any, name: str) -> Any:
    """Reads a timing constraint field from either an object attribute or a dict."""
    if tc_obj is None:
        return None
    if isinstance(tc_obj, dict):
        return tc_obj.get(name, None)
    return getattr(tc_obj, name, None)


def extract_timing_constraints(
    backend: Any,
    cfg: Gumija2ThreeRestConfig,
    allow_fallback_dt: bool = True,
) -> dict[str, Any]:
    """
    Extracts timing constraints (dt, granularity, min_length, pulse_alignment, acquire_alignment)
    from a Qiskit BackendV2 target without inventing missing values.
    Supports both attribute and callable method forms of target.timing_constraints.
    When allow_fallback_dt is False (live mode), raises RuntimeError if target.dt is missing.
    """
    target = getattr(backend, "target", None)
    dt_sec = getattr(target, "dt", None) if target is not None else None
    if dt_sec is None:
        if not allow_fallback_dt:
            raise RuntimeError(
                "Live target.dt is missing; refusing to substitute offline fallback_dt_sec."
            )
        dt_sec = cfg.fallback_dt_sec
        dt_source = "FALLBACK_OFFLINE_MODEL"
    else:
        dt_sec = float(dt_sec)
        dt_source = "BACKEND_TARGET"

    tc_attr = getattr(target, "timing_constraints", None) if target is not None else None
    if callable(tc_attr):
        tc_obj = tc_attr()
    else:
        tc_obj = tc_attr

    granularity = _read_constraint_field(tc_obj, "granularity")
    min_length = _read_constraint_field(tc_obj, "min_length")
    pulse_alignment = _read_constraint_field(tc_obj, "pulse_alignment")
    acquire_alignment = _read_constraint_field(tc_obj, "acquire_alignment")

    g_val = int(granularity) if granularity is not None else 1
    p_val = int(pulse_alignment) if pulse_alignment is not None else 1
    step_dt = math.lcm(max(g_val, 1), max(p_val, 1))
    min_len_dt = int(min_length) if min_length is not None else step_dt

    return {
        "dt_sec": dt_sec,
        "dt_source": dt_source,
        "granularity": int(granularity) if granularity is not None else "MISSING",
        "min_length": int(min_length) if min_length is not None else "MISSING",
        "pulse_alignment": int(pulse_alignment) if pulse_alignment is not None else "MISSING",
        "acquire_alignment": int(acquire_alignment) if acquire_alignment is not None else "MISSING",
        "effective_step_dt": step_dt,
        "effective_min_length_dt": min_len_dt,
    }


def quantize_delay_us(
    requested_us: float,
    timing: dict[str, Any],
    rounding_mode: str = "nearest",
) -> QuantizedDelayInfo:
    """
    Converts requested_us into an integer number of dt ticks obeying effective_step_dt
    and effective_min_length_dt under the configured rounding_mode ('nearest', 'ceil', 'floor').
    If requested_us <= 0.0, returns 0 dt (no delay instruction inserted).
    """
    dt_sec = float(timing["dt_sec"])
    step_dt = int(timing["effective_step_dt"])
    min_len_dt = int(timing["effective_min_length_dt"])

    if requested_us <= 0.0:
        return QuantizedDelayInfo(
            requested_us=0.0,
            actual_dt=0,
            actual_us=0.0,
            delta_us=0.0,
            dt_sec=dt_sec,
            step_dt=step_dt,
            min_length_dt=min_len_dt,
        )

    raw_steps = ((requested_us * 1e-6) / dt_sec) / step_dt
    if rounding_mode == "nearest":
        steps = int(round(raw_steps))
    elif rounding_mode == "ceil":
        steps = int(math.ceil(raw_steps - 1e-12))
    elif rounding_mode == "floor":
        steps = int(math.floor(raw_steps + 1e-12))
    else:
        raise ValueError(f"Unsupported delay_rounding_mode: {rounding_mode}")

    actual_dt = max(min_len_dt, steps * step_dt)
    if actual_dt % step_dt != 0:
        actual_dt = ((actual_dt + step_dt - 1) // step_dt) * step_dt

    actual_us = actual_dt * dt_sec * 1e6
    return QuantizedDelayInfo(
        requested_us=float(requested_us),
        actual_dt=int(actual_dt),
        actual_us=float(actual_us),
        delta_us=float(actual_us - requested_us),
        dt_sec=dt_sec,
        step_dt=step_dt,
        min_length_dt=min_len_dt,
    )


def extract_history_interval_dt(transpiled_qc: QuantumCircuit) -> dict[str, Any]:
    """
    Computes the scheduled history interval length in dt units from op_start_times:
      interval_dt = start_time('end_history' barrier) - start_time(first history operation).
    Does NOT use absolute barrier timestamps, Instruction.duration, or Circuit.duration.
    Also reports whether any prefix operations exist prior to the history block.
    """
    start_times = getattr(transpiled_qc, "op_start_times", None)
    if start_times is None:
        raise RuntimeError(
            "Transpiled circuit lacks op_start_times; ensure scheduling_method='alap' was used."
        )

    barrier_idx = None
    for idx, inst in enumerate(transpiled_qc.data):
        if inst.operation.name == "barrier" and getattr(inst.operation, "label", "") == "end_history":
            barrier_idx = idx
            break

    if barrier_idx is None:
        raise RuntimeError("Missing 'end_history' barrier in transpiled circuit.")

    first_hist_idx = None
    has_prefix = False
    for idx in range(barrier_idx):
        op_name = transpiled_qc.data[idx].operation.name
        if op_name in ("reset", "initialize"):
            has_prefix = True
            first_hist_idx = None
            continue
        if op_name == "barrier":
            if first_hist_idx is None:
                has_prefix = True
            continue
        if first_hist_idx is None:
            first_hist_idx = idx

    end_history_start = int(start_times[barrier_idx])
    if first_hist_idx is None:
        first_hist_start = end_history_start
    else:
        first_hist_start = int(start_times[first_hist_idx])

    interval_dt = end_history_start - first_hist_start
    return {
        "first_hist_op_idx": first_hist_idx,
        "end_history_barrier_idx": barrier_idx,
        "first_hist_start_dt": first_hist_start,
        "end_history_start_dt": end_history_start,
        "history_interval_dt": int(interval_dt),
        "has_prefix_ops": has_prefix,
    }


def build_circuit(
    cfg: Gumija2ThreeRestConfig,
    arm: str,
    rest_us: float,
    cell: str,
    stress_delay_dt: int,
    rest_delay_dt: int = 0,
    probe_delay_dt: int = 0,
) -> QuantumCircuit:
    """
    Builds one logical circuit for (arm, rest_us, cell) on 2 logical qubits and 2 classical bits:
      - Logical 0 -> target_qubit (q21), Logical 1 -> neighbor_qubit (q20).
      - Classical c[0] = mid-circuit herald, c[1] = final readout.
      - Steps 1..7 strictly follow Section 1 of the specification.
    """
    if arm not in cfg.arms:
        raise ValueError(f"Unknown arm '{arm}', expected one of {cfg.arms}")
    if cell not in cfg.cells:
        raise ValueError(f"Unknown cell '{cell}', expected one of {cfg.cells}")

    prep = cell[0]
    probe = cell[1]

    qc = QuantumCircuit(2, 2, name=f"{arm}_r{int(rest_us)}_{cell}")

    # 1. History stage
    if arm == "S":
        for _ in range(cfg.n_stress_units):
            qc.x(0)
            qc.cz(0, 1)
            qc.x(0)
    else:
        if stress_delay_dt > 0:
            qc.append(Delay(int(stress_delay_dt), unit="dt"), [0])
            qc.append(Delay(int(stress_delay_dt), unit="dt"), [1])

    # 2. Barrier label "end_history"
    qc.barrier(0, 1, label="end_history")

    # 3. Herald: measure target qubit (0) into c[0], followed by barrier
    qc.measure(0, 0)
    qc.barrier(0, 1)

    # 4. Rest stage: Delay r on both qubits (no delay if rest_us == 0), followed by barrier
    if rest_us > 0.0 and rest_delay_dt > 0:
        qc.append(Delay(int(rest_delay_dt), unit="dt"), [0])
        qc.append(Delay(int(rest_delay_dt), unit="dt"), [1])
    qc.barrier(0, 1)

    # 5. State preparation: E -> X(q21), G -> no gate, followed by barrier
    if prep == "E":
        qc.x(0)
    qc.barrier(0, 1)

    # 6. Probe stage: 0 or T Delay on q21 (no delay if probe == '0'), followed by barrier
    if probe == "T" and probe_delay_dt > 0:
        qc.append(Delay(int(probe_delay_dt), unit="dt"), [0])
    qc.barrier(0, 1)

    # 7. Final measurement of target qubit (0) into c[1]
    qc.measure(0, 1)
    return qc


def compute_stress_delay_dt(cfg: Gumija2ThreeRestConfig, backend: Any) -> tuple[int, dict[str, Any]]:
    """
    Transpiles an S-arm circuit with initial_layout=[21, 20], optimization_level=0,
    scheduling_method='alap' and computes the exact scheduled history-interval length
    in dt units via op_start_times.
    """
    probe_qc = build_circuit(
        cfg=cfg,
        arm="S",
        rest_us=0.0,
        cell="G0",
        stress_delay_dt=0,
        rest_delay_dt=0,
        probe_delay_dt=0,
    )
    t_qc = transpile(
        probe_qc,
        backend=backend,
        initial_layout=list(cfg.initial_layout),
        optimization_level=cfg.optimization_level,
        scheduling_method=cfg.scheduling_method,
    )
    interval_info = extract_history_interval_dt(t_qc)
    return int(interval_info["history_interval_dt"]), interval_info


def build_all_24_logical_circuits(
    cfg: Gumija2ThreeRestConfig,
    backend: Any,
    allow_fallback_dt: bool = True,
) -> tuple[dict[tuple[str, float, str], QuantumCircuit], dict[str, Any]]:
    """
    Builds all 24 logical circuits (2 arms x 3 rests x 4 cells) using quantized delays
    derived from the backend target and the scheduled S-arm history interval.
    When allow_fallback_dt is False, missing target.dt raises RuntimeError.
    Returns (circuits_map, timing_report).
    """
    timing = extract_timing_constraints(backend, cfg, allow_fallback_dt=allow_fallback_dt)
    stress_dt, hist_info = compute_stress_delay_dt(cfg, backend)
    stress_us = stress_dt * timing["dt_sec"] * 1e6

    rest_q_map = {
        r: quantize_delay_us(r, timing, cfg.delay_rounding_mode)
        for r in cfg.rest_grid_us
    }
    probe_q = quantize_delay_us(cfg.probe_time_us, timing, cfg.delay_rounding_mode)

    circuits_map: dict[tuple[str, float, str], QuantumCircuit] = {}
    for arm in cfg.arms:
        for r in cfg.rest_grid_us:
            r_dt = rest_q_map[r].actual_dt
            for cell in cfg.cells:
                p_dt = probe_q.actual_dt if cell[1] == "T" else 0
                circuits_map[(arm, r, cell)] = build_circuit(
                    cfg=cfg,
                    arm=arm,
                    rest_us=r,
                    cell=cell,
                    stress_delay_dt=stress_dt,
                    rest_delay_dt=r_dt,
                    probe_delay_dt=p_dt,
                )

    timing_report = {
        "constraints": timing,
        "stress_history": {
            "scheduled_dt": stress_dt,
            "scheduled_us": stress_us,
            "interval_details": hist_info,
        },
        "rest_delays": {
            str(r): {
                "requested_us": q.requested_us,
                "actual_dt": q.actual_dt,
                "actual_us": q.actual_us,
                "delta_us": q.delta_us,
            }
            for r, q in rest_q_map.items()
        },
        "probe_delay_T": {
            "requested_us": probe_q.requested_us,
            "actual_dt": probe_q.actual_dt,
            "actual_us": probe_q.actual_us,
            "delta_us": probe_q.delta_us,
        },
    }
    return circuits_map, timing_report


def validate_shot_splits(cfg: Gumija2ThreeRestConfig) -> None:
    """Verifies that per-cell shot splits sum to 333/333/334/1000 and 12,000 per session."""
    expected_cell_sums = {"E0": 333, "G0": 333, "GT": 334, "ET": 1000}
    for cell, exp_sum in expected_cell_sums.items():
        splits = cfg.shot_splits_per_cell[cell]
        if len(splits) != 4:
            raise ValueError(f"Cell {cell} must have 4 occurrence splits, got {len(splits)}")
        if sum(splits) != exp_sum:
            raise ValueError(f"Cell {cell} shot split sum {sum(splits)} != {exp_sum}")

    session_total = 2 * len(cfg.rest_grid_us) * sum(sum(v) for v in cfg.shot_splits_per_cell.values())
    if session_total != cfg.expected_shots_per_session:
        raise ValueError(
            f"Session total shots {session_total} != expected {cfg.expected_shots_per_session}"
        )


def build_session_plan(
    cfg: Gumija2ThreeRestConfig,
    session_idx: int,
    logical_circuits: dict[tuple[str, float, str], QuantumCircuit] | None = None,
) -> list[dict[str, Any]]:
    """
    Constructs the 12-slot / 96-instance execution plan for one session (12,000 attempted shots).
    Each slot corresponds to one rest label ('A', 'B', or 'C') and contains 8 instances
    ordered by cfg.intra_slot_instance_order (NYITOTT / unsimulated proposal).
    The n-th occurrence (0..3) of a rest label receives the n-th element of shot_splits_per_cell[cell].
    """
    validate_shot_splits(cfg)
    if len(cfg.slot_order_labels) != 12:
        raise ValueError(f"Expected 12 slots in slot_order_labels, got {len(cfg.slot_order_labels)}")

    occurrence_counter = {label: 0 for label in cfg.label_to_rest_us}
    plan_instances: list[dict[str, Any]] = []

    for slot_idx, rest_label in enumerate(cfg.slot_order_labels):
        rest_us = cfg.label_to_rest_us[rest_label]
        occ_idx = occurrence_counter[rest_label]
        if occ_idx >= 4:
            raise ValueError(f"Rest label '{rest_label}' appears more than 4 times in slot_order_labels")
        occurrence_counter[rest_label] += 1

        for arm, cell in cfg.intra_slot_instance_order:
            shots = int(cfg.shot_splits_per_cell[cell][occ_idx])
            qc = logical_circuits.get((arm, rest_us, cell)) if logical_circuits is not None else None
            plan_instances.append({
                "session_idx": int(session_idx),
                "slot_idx": int(slot_idx),
                "rest_label": rest_label,
                "rest_occurrence_idx": int(occ_idx),
                "rest_us": float(rest_us),
                "arm": arm,
                "cell": cell,
                "shots": shots,
                "circuit": qc,
            })

    if len(plan_instances) != 96:
        raise RuntimeError(f"Expected 96 instances per session, built {len(plan_instances)}")
    if sum(item["shots"] for item in plan_instances) != cfg.expected_shots_per_session:
        raise RuntimeError("Session instance shot sum mismatch.")

    return plan_instances