#!/usr/bin/env python3
"""
qubit-gumija2-history-contrast / analyzer3.py

Campaign analyzer for the 3-rest survival-contrast design (Section 1):
  - Offline herald=0 filtering (Qiskit little-endian bitstring: bs[-1] == c0, bs[-2] == c1).
  - Pools the 4 slot occurrences per (session, arm, rest, cell).
  - Computes survival ratio s_a(r) = (m_ET - m_GT) / (m_E0 - m_G0) for a in {'S', 'I'}.
  - Computes Lambda_k(r) = ln(ln(s_I(r)) / ln(s_S(r))) when 0 < s_S < 1 and 0 < s_I < 1, else NaN.
  - Computes D_k = Lambda_k(0) - 0.5 * (Lambda_k(16) + Lambda_k(64)).
  - Campaign decision:
      * If ANY D_k is NaN -> status = 'ERVENYTELEN' (reports exact NaN count; never imputes).
      * Otherwise -> D_bar, se = std(D, ddof=1) / sqrt(16), two-sided t(0.975; 15) CI.
      * 'JEL' iff 0 is excluded from the CI.
      * No state gate, no variance multiplier, no curvature test.
"""

import math
from typing import Any
import numpy as np
from scipy import stats


def filter_herald_bitstrings(bitstrings: list[str]) -> tuple[int, int]:
    """
    Filters Qiskit 2-bit little-endian bitstrings on c0 == '0' (rightmost char bs[-1]).
    Counts c1 == '1' (second char from right bs[-2]) among retained shots.
    Returns (retained_c1_ones, retained_total).
    """
    retained = 0
    ones = 0
    for bs in bitstrings:
        s = bs.strip()
        if len(s) < 2:
            raise ValueError(f"Expected 2-bit bitstring, got '{bs}'")
        c0 = s[-1]
        c1 = s[-2]
        if c0 == "0":
            retained += 1
            if c1 == "1":
                ones += 1
    return ones, retained


def parse_counts_dict(counts: dict[str, int]) -> tuple[int, int]:
    """
    Aggregates a Qiskit counts dictionary {'00': n00, '10': n10, '01': n01, '11': n11}
    under offline herald=0 filtering (c0 == '0' -> keys ending with '0').
    Returns (retained_c1_ones, retained_total).
    """
    retained = 0
    ones = 0
    for bs, cnt in counts.items():
        s = bs.strip()
        if len(s) < 2:
            raise ValueError(f"Expected 2-bit key in counts dict, got '{bs}'")
        c0 = s[-1]
        c1 = s[-2]
        if c0 == "0":
            retained += int(cnt)
            if c1 == "1":
                ones += int(cnt)
    return ones, retained


def compute_survival_ratio_s(cell_filtered_counts: dict[str, tuple[int, int]]) -> float:
    """
    Computes G-corrected survival ratio:
      s_a = (m_ET - m_GT) / (m_E0 - m_G0)
    where cell_filtered_counts maps each cell in {'E0', 'G0', 'GT', 'ET'} to
    (retained_c1_ones, retained_total) pooled across all 4 slot occurrences.
    """
    m: dict[str, float] = {}
    for cell in ("E0", "G0", "GT", "ET"):
        ones, total = cell_filtered_counts[cell]
        if total <= 0:
            return float("nan")
        m[cell] = ones / total

    denom = m["E0"] - m["G0"]
    if abs(denom) <= 1e-12:
        return float("nan")
    return float((m["ET"] - m["GT"]) / denom)


def compute_lambda_r(s_S: float, s_I: float) -> float:
    """
    Computes Lambda_k(r) = ln(ln(s_I) / ln(s_S)).
    Valid iff both s_S and s_I lie strictly inside (0, 1); otherwise returns NaN.
    """
    if math.isnan(s_S) or math.isnan(s_I):
        return float("nan")
    if not (0.0 < s_S < 1.0 and 0.0 < s_I < 1.0):
        return float("nan")
    return float(math.log(math.log(s_I) / math.log(s_S)))


def analyze_session(session_counts: dict[str, dict[float, dict[str, dict[str, int]]]]) -> dict[str, Any]:
    """
    Analyzes one session's pooled Qiskit counts dictionaries:
      session_counts[arm][rest_us][cell] = {'00': ..., '10': ..., '01': ..., '11': ...}
    Returns per-rest s_S, s_I, Lambda(r), and D_k = Lambda(0) - 0.5*(Lambda(16) + Lambda(64)).
    """
    rest_grid = (0.0, 16.0, 64.0)
    s_by_arm_rest: dict[str, dict[float, float]] = {"S": {}, "I": {}}
    lambda_by_rest: dict[float, float] = {}

    for r in rest_grid:
        for arm in ("S", "I"):
            pooled_cells = {
                cell: parse_counts_dict(session_counts[arm][r][cell])
                for cell in ("E0", "G0", "GT", "ET")
            }
            s_by_arm_rest[arm][r] = compute_survival_ratio_s(pooled_cells)
        lambda_by_rest[r] = compute_lambda_r(s_by_arm_rest["S"][r], s_by_arm_rest["I"][r])

    if any(math.isnan(lambda_by_rest[r]) for r in rest_grid):
        d_k = float("nan")
    else:
        d_k = float(lambda_by_rest[0.0] - 0.5 * (lambda_by_rest[16.0] + lambda_by_rest[64.0]))

    return {
        "s_S": {str(r): s_by_arm_rest["S"][r] for r in rest_grid},
        "s_I": {str(r): s_by_arm_rest["I"][r] for r in rest_grid},
        "Lambda": {str(r): lambda_by_rest[r] for r in rest_grid},
        "D_k": d_k,
    }


def analyze_campaign(
    sessions_data: list[dict[str, dict[float, dict[str, dict[str, int]]]]],
    alpha: float = 0.05,
) -> dict[str, Any]:
    """
    Analyzes a 16-session campaign.
    If any session yields NaN for D_k, returns status='ERVENYTELEN' along with the exact
    count of NaN sessions (never drops or imputes invalid sessions).
    """
    session_results = [analyze_session(s) for s in sessions_data]
    d_vals = np.array([res["D_k"] for res in session_results], dtype=np.float64)
    nan_count = int(np.isnan(d_vals).sum())
    n_sessions = len(d_vals)

    if nan_count > 0 or n_sessions < 2:
        return {
            "scope_note": "16 sessionos kampanyban realizalt rest-fuggo kontraszt (nincs mechanizmus-allitas)",
            "status": "ERVENYTELEN",
            "n_sessions": n_sessions,
            "nan_D_count": nan_count,
            "D_bar": float("nan"),
            "se": float("nan"),
            "ci_95": [float("nan"), float("nan")],
            "signal_detected": False,
            "sessions": session_results,
        }

    d_bar = float(np.mean(d_vals))
    se = float(np.std(d_vals, ddof=1) / math.sqrt(n_sessions))
    t_crit = float(stats.t.ppf(1.0 - alpha / 2.0, df=n_sessions - 1))
    ci_lo = d_bar - t_crit * se
    ci_hi = d_bar + t_crit * se
    signal = bool((ci_lo > 0.0) or (ci_hi < 0.0))

    return {
        "scope_note": "16 sessionos kampanyban realizalt rest-fuggo kontraszt (nincs mechanizmus-allitas)",
        "status": "JEL" if signal else "NINCS_JEL",
        "n_sessions": n_sessions,
        "nan_D_count": 0,
        "D_bar": d_bar,
        "se": se,
        "t_crit": t_crit,
        "ci_95": [float(ci_lo), float(ci_hi)],
        "signal_detected": signal,
        "sessions": session_results,
    }