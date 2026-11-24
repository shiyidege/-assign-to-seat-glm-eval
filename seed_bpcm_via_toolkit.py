#!/usr/bin/env python3
"""
种子策略：通过可选组件 solver_toolkit 调用开源求解器，复现论文 BPC-M（Eq.12）。
AI 进化时也可参考/改造本文件；decide 单步会解一次小 LP。
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import numpy as np
from scipy.sparse import csc_matrix

from solver_toolkit import preferred_lp_solver, solve_lp


class _BPCMCache:
    def __init__(self):
        self.M = None
        self.pairs = None
        self.pair_idx = None
        self.A_ub = None
        self.b_base = None  # will rebuild with prices
        self.prices = None


_CACHE = _BPCMCache()


def _ensure(M: int, prices: Dict[Tuple[int, int], int]):
    if _CACHE.M == M and _CACHE.prices is prices:
        return
    pairs = [(u, v) for u in range(1, M + 1) for v in range(u, M + 1)]
    pair_idx = {p: i for i, p in enumerate(pairs)}
    P = len(pairs)
    quads = [
        (u, i, j, v)
        for u in range(1, M + 1)
        for i in range(u, M + 1)
        for j in range(i, M + 1)
        for v in range(j, M + 1)
    ]
    rows, cols, vals, b_ub = [], [], [], []
    for q_i, (u, i, j, v) in enumerate(quads):
        b_ub.append(-float(prices[(i, j)]))
        rows.append(q_i); cols.append(pair_idx[(i, j)]); vals.append(-1.0)
        rows.append(q_i); cols.append(P + pair_idx[(u, v)]); vals.append(-1.0)
        if u < i:
            rows.append(q_i); cols.append(P + pair_idx[(u, i - 1)]); vals.append(1.0)
        if j < v:
            rows.append(q_i); cols.append(P + pair_idx[(j + 1, v)]); vals.append(1.0)
    _CACHE.M = M
    _CACHE.pairs = pairs
    _CACHE.pair_idx = pair_idx
    _CACHE.A_ub = csc_matrix((vals, (rows, cols)), shape=(len(quads), 2 * P))
    _CACHE.b_base = np.asarray(b_ub, dtype=float)
    _CACHE.prices = prices


def decide(t, T, M, counts, req_i, req_j, prices, remaining_expected, solver: str = "auto"):
    """可选调用开源求解器的 BPC-M 决策；solver 失败时退回最小可行块。"""
    # 找可行 maximal intervals（按长度升序 + 左贴合）
    cands = []
    for (u, v), cnt in counts.items():
        if cnt > 0 and u <= req_i and req_j <= v:
            cands.append((u, v))
    if not cands:
        return None
    cands.sort(key=lambda uv: (uv[1] - uv[0], uv[0], -uv[1]))

    _ensure(M, prices)
    pairs = _CACHE.pairs
    pair_idx = _CACHE.pair_idx
    P = len(pairs)
    c = np.zeros(2 * P, dtype=float)
    for p_i, ij in enumerate(pairs):
        c[p_i] = float(remaining_expected.get(ij, 0.0))
        c[P + p_i] = float(counts.get(ij, 0))

    use = solver if solver != "auto" else preferred_lp_solver()
    res = solve_lp(
        c,
        A_ub=_CACHE.A_ub,
        b_ub=_CACHE.b_base,
        bounds=[(0.0, None)] * (2 * P),
        solver=use,
        time_limit_s=0.5,
    )
    if not res["ok"]:
        return cands[0]

    beta = res["x"][P:]
    p_val = float(prices[(req_i, req_j)])
    best_gain = -1e18
    best_uv = None
    for (u, v) in cands:
        b_uv = beta[pair_idx[(u, v)]]
        b_left = beta[pair_idx[(u, req_i - 1)]] if u < req_i else 0.0
        b_right = beta[pair_idx[(req_j + 1, v)]] if req_j < v else 0.0
        gain = p_val + b_left + b_right - b_uv
        if gain > best_gain + 1e-7:
            best_gain = gain
            best_uv = (u, v)
    if best_uv is not None and best_gain >= -1e-7:
        return best_uv
    return None
