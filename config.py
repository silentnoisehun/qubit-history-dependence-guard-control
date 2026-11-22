#!/usr/bin/env python3
"""
qubit-gumija2-history-contrast / config.py

Configuration constants and explicitly marked OPEN ('NYITOTT') parameters for the
three-rest campaign design. Contains no credentials, tokens, or QPU submission flags.
"""

from dataclasses import dataclass, field
from typing import Literal, Optional


@dataclass(frozen=True)
class Gumija2ThreeRestConfig:
    """
    Assumptions and parameters for the 3-rest survival-contrast design:
      - Physical pair: target q21, neighbor q20 on 'ibm_marrakesh'.
      - Transpilation invariants: initial_layout=[21, 20], optimization_level=0,
        scheduling_method='alap'.
      - All items tagged 'NYITOTT' are unapproved design placeholders and must be
        explicitly configured or audited prior to any external execution.
    """

    # --- Fixed design proposal parameters (Section 1) ---
    backend_name: str = "ibm_marrakesh"
    target_qubit: int = 21
    neighbor_qubit: int = 20
    initial_layout: tuple[int, int] = (21, 20)
    optimization_level: int = 0
    scheduling_method: str = "alap"

    arms: tuple[str, str] = ("S", "I")
    n_stress_units: int = 32
    rest_grid_us: tuple[float, float, float] = (0.0, 16.0, 64.0)
    probe_time_us: float = 220.0
    cells: tuple[str, str, str, str] = ("E0", "G0", "GT", "ET")

    # 12-slot balanced schedule: A=0 us, B=16 us, C=64 us
    slot_order_labels: tuple[str, ...] = (
        "A", "B", "C", "C", "B", "A", "B", "C", "A", "A", "C", "B"
    )
    label_to_rest_us: dict[str, float] = field(
        default_factory=lambda: {"A": 0.0, "B": 16.0, "C": 64.0}
    )

    # Proposed integer shot split across the 4 occurrences of each rest per session
    # Sums: E0=333, G0=333, GT=334, ET=1000 -> 2000 per (arm, rest) -> 12,000 per session
    shot_splits_per_cell: dict[str, tuple[int, int, int, int]] = field(
        default_factory=lambda: {
            "E0": (84, 83, 83, 83),
            "G0": (84, 83, 83, 83),
            "GT": (84, 84, 83, 83),
            "ET": (250, 250, 250, 250),
        }
    )

    num_sessions: int = 16
    expected_shots_per_session: int = 12000
    expected_shots_campaign: int = 192000
    alpha: float = 0.05

    # --- NYITOTT (OPEN / UNAPPROVED) PARAMETERS (Section 3) ---
    # NYITOTT (3a): Repetition delay in microseconds (unapproved; None = unset)
    rep_delay_us: Optional[float] = None
    # NYITOTT (3a): Qubit initialization flag (unapproved; None = unset)
    init_qubits: Optional[bool] = None
    # NYITOTT (3b): Delay between sessions in seconds and explicit start timestamps
    inter_session_delay_sec: Optional[float] = None
    session_start_times_utc: Optional[tuple[str, ...]] = None
    # NYITOTT (3c): Shot ordering in Sampler/runtime is an external unknown property
    sampler_shot_order_status: str = "ISMERETLEN_KULSO_RUNTIME_TULAJDONSAG"
    # NYITOTT (3d): Intra-slot order of the 8 circuit instances (proposed, NOT simulated/validated)
    intra_slot_instance_order: tuple[tuple[str, str], ...] = (
        ("S", "E0"), ("I", "E0"),
        ("S", "G0"), ("I", "G0"),
        ("S", "GT"), ("I", "GT"),
        ("S", "ET"), ("I", "ET"),
    )
    # NYITOTT (3e): Delay quantization rule against live target timing constraints
    delay_rounding_mode: Literal["nearest", "ceil", "floor"] = "nearest"
    fallback_dt_sec: float = 4e-9  # Used ONLY in offline dry-run if backend target has no dt
    assumed_base_cycle_us: float = 470.0  # Assumed timing model parameter for schedule center-of-mass report