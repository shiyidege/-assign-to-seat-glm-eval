import collections
import json
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
from scipy.optimize import linprog
from scipy.sparse import csc_matrix

from best_pop100_policy import decide as glm_e097_decide
from problem_core import (
    apply_maximal_transition,
    build_arrival_schedule,
    feasible_intervals,
    myopic_policy,
    paper_prices,
    precompute_remaining_expected_demand,
    sample_path,
    seat_maximal_sequences,
    solve_hindsight_optimum_empty_train,
    tie_breaking_key,
)


# =============================================================================
# 1. 论文原版 LP 算法精确复现 (SciPy HiGHS): BPC-S, BPC-M, RDP
# =============================================================================

class PaperLPBenchmarks:
    """严格按 Zhu et al. Section 4 复现 BPC-M (Eq. 12) 和 RDP (Eq. 14+15)。"""

    def __init__(self, M: int, prices: Dict[Tuple[int, int], int]):
        self.M = M
        self.prices = prices
        self.pairs = [(u, v) for u in range(1, M + 1) for v in range(u, M + 1)]
        self.pair_idx = {p: idx for idx, p in enumerate(self.pairs)}
        self.n_pairs = len(self.pairs)

        # 所有合法四元组 (u, i, j, v): 1 <= u <= i <= j <= v <= M
        self.quads = [
            (u, i, j, v)
            for u in range(1, M + 1)
            for i in range(u, M + 1)
            for j in range(i, M + 1)
            for v in range(j, M + 1)
        ]
        self.quad_idx = {q: idx for idx, q in enumerate(self.quads)}
        self.n_quads = len(self.quads)

        # 预构建 BPC-M (Eq. 12) 稀疏约束矩阵:
        # 变量: [z_{ij} (0..P-1), beta_{uv} (P..2P-1)]
        # 约束: z_{ij} + beta_{uv} - beta_{u, i-1} - beta_{j+1, v} >= p_{ij}
        # 即 -z_{ij} - beta_{uv} + beta_{u, i-1} + beta_{j+1, v} <= -p_{ij}
        rows, cols, vals = [], [], []
        b_ub = np.zeros(self.n_quads, dtype=float)
        P = self.n_pairs
        for q_i, (u, i, j, v) in enumerate(self.quads):
            b_ub[q_i] = -float(prices[(i, j)])
            rows.append(q_i); cols.append(self.pair_idx[(i, j)]); vals.append(-1.0)
            rows.append(q_i); cols.append(P + self.pair_idx[(u, v)]); vals.append(-1.0)
            if u < i:
                rows.append(q_i); cols.append(P + self.pair_idx[(u, i - 1)]); vals.append(1.0)
            if j < v:
                rows.append(q_i); cols.append(P + self.pair_idx[(j + 1, v)]); vals.append(1.0)
        self.bpcm_A_ub = csc_matrix((vals, (rows, cols)), shape=(self.n_quads, 2 * P))
        self.bpcm_b_ub = b_ub

        # 预构建 RDP (Eq. 14) 稀疏约束矩阵:
        # 变量: [gamma_{uijv} (0..Q-1), gamma0_{ij} (Q..Q+P-1)]
        # 目标: maximize sum p_{ij} * gamma_{uijv} -> minimize -p_{ij}
        Q = self.n_quads
        self.rdp_c = np.zeros(Q + P, dtype=float)
        for q_i, (u, i, j, v) in enumerate(self.quads):
            self.rdp_c[q_i] = -float(prices[(i, j)])

        # 等式约束 (P 条): sum_{u<=i<=j<=v} gamma_{uijv} + gamma0_{ij} = d_{ij}
        eq_r, eq_c, eq_v = [], [], []
        for q_i, (u, i, j, v) in enumerate(self.quads):
            p_i = self.pair_idx[(i, j)]
            eq_r.append(p_i); eq_c.append(q_i); eq_v.append(1.0)
        for p_i in range(P):
            eq_r.append(p_i); eq_c.append(Q + p_i); eq_v.append(1.0)
        self.rdp_A_eq = csc_matrix((eq_v, (eq_r, eq_c)), shape=(P, Q + P))

        # 不等式约束 (P 条, 对应每个 [u, v]):
        # sum_{u<=i<=j<=v} gamma_{uijv}
        # - sum_{v+1<=k<=l} gamma_{u, v+1, k, l}   (消费 [u, l] 放 v+1..k 会产生 [u, v])
        # - sum_{l<=k<=u-1} gamma_{l, k, u-1, v}   (消费 [l, v] 放 k..u-1 会产生 [u, v])
        # <= A_{uv}
        ub_r, ub_c, ub_v = [], [], []
        for q_i, (u, i, j, v) in enumerate(self.quads):
            # 消耗 [u, v]
            ub_r.append(self.pair_idx[(u, v)]); ub_c.append(q_i); ub_v.append(1.0)
            # 产生 [u, i-1] (若 u < i)
            if u < i:
                ub_r.append(self.pair_idx[(u, i - 1)]); ub_c.append(q_i); ub_v.append(-1.0)
            # 产生 [j+1, v] (若 j < v)
            if j < v:
                ub_r.append(self.pair_idx[(j + 1, v)]); ub_c.append(q_i); ub_v.append(-1.0)
        self.rdp_A_ub = csc_matrix((ub_v, (ub_r, ub_c)), shape=(P, Q + P))

        # 预索引每个 (i, j) 对应的所有四元组索引，便于加 Eq.(15) 上界
        self.quads_by_ij: Dict[Tuple[int, int], List[Tuple[int, int, int]]] = collections.defaultdict(list)
        for q_i, (u, i, j, v) in enumerate(self.quads):
            self.quads_by_ij[(i, j)].append((q_i, u, v))

    def bpcm_decide(
        self,
        t: int,
        T: int,
        M: int,
        counts: Dict[Tuple[int, int], int],
        req_i: int,
        req_j: int,
        prices: Dict[Tuple[int, int], int],
        rem_exp: Dict[Tuple[int, int], float],
    ) -> Optional[Tuple[int, int]]:
        cands = feasible_intervals(counts, req_i, req_j)
        if not cands:
            return None
        P = self.n_pairs
        c = np.zeros(2 * P, dtype=float)
        for p_i, ij in enumerate(self.pairs):
            c[p_i] = float(rem_exp.get(ij, 0.0))
            c[P + p_i] = float(counts.get(ij, 0))
        res = linprog(c, A_ub=self.bpcm_A_ub, b_ub=self.bpcm_b_ub, bounds=(0, None), method="highs")
        if not res.success:
            return cands[0]
        beta = res.x[P:]
        p_val = float(prices[(req_i, req_j)])

        best_gain = -1e18
        best_uv = None
        for (u, v) in cands:  # cands 已按论文 Tie-Breaking 排好序
            b_uv = beta[self.pair_idx[(u, v)]]
            b_left = beta[self.pair_idx[(u, req_i - 1)]] if u < req_i else 0.0
            b_right = beta[self.pair_idx[(req_j + 1, v)]] if req_j < v else 0.0
            gain = p_val + b_left + b_right - b_uv
            if gain > best_gain + 1e-7:
                best_gain = gain
                best_uv = (u, v)
        if best_uv is not None and best_gain >= -1e-7:
            return best_uv
        return None

    def rdp_decide(
        self,
        t: int,
        T: int,
        M: int,
        counts: Dict[Tuple[int, int], int],
        req_i: int,
        req_j: int,
        prices: Dict[Tuple[int, int], int],
        rem_exp: Dict[Tuple[int, int], float],
    ) -> Optional[Tuple[int, int]]:
        cands = feasible_intervals(counts, req_i, req_j)
        if not cands:
            return None
        P = self.n_pairs
        Q = self.n_quads
        b_eq = np.array([float(rem_exp.get(ij, 0.0)) for ij in self.pairs], dtype=float)
        b_ub = np.array([float(counts.get(uv, 0)) for uv in self.pairs], dtype=float)

        # Eq.(15) 对当前请求 (req_i, req_j) 的上界约束: gamma_{u, req_i, req_j, v} <= A_{uv}
        bounds = [(0.0, None)] * (Q + P)
        for q_i, u, v in self.quads_by_ij[(req_i, req_j)]:
            bounds[q_i] = (0.0, float(counts.get((u, v), 0)))

        res = linprog(
            self.rdp_c,
            A_ub=self.rdp_A_ub,
            b_ub=b_ub,
            A_eq=self.rdp_A_eq,
            b_eq=b_eq,
            bounds=bounds,
            method="highs",
        )
        if not res.success:
            return cands[0]

        x = res.x
        best_val = -1.0
        best_uv: Optional[Tuple[int, int]] = None

        # cands 已按论文 Section 5.1 Tie-Breaking 排好序，且优先接单再拒单
        for (u, v) in cands:
            q_i = self.quad_idx[(u, req_i, req_j, v)]
            val = float(x[q_i])
            if val > best_val + 1e-7:
                best_val = val
                best_uv = (u, v)

        rej_val = float(x[Q + self.pair_idx[(req_i, req_j)]])
        if rej_val > best_val + 1e-7:
            return None
        return best_uv


def simulate_bpcs_exact(
    N: int,
    M: int,
    path: List[Optional[Tuple[int, int]]],
    prices: Dict[Tuple[int, int], int],
    suffix_expected: List[Dict[Tuple[int, int], float]],
    resolve_every: int = 1,
) -> Dict[str, float]:
    """严格复现论文 Algorithm 1: BPC-S (Eq. 6)，按唯一座位行类型聚合加速，数学完全等价。"""
    pairs = [(i, j) for i in range(1, M + 1) for j in range(i, M + 1)]
    P = len(pairs)
    # 维护每个座位的可用行 bitmask，用 Counter 统计每种唯一行型的座位数
    full_row = tuple([1] * M)
    row_counts: Dict[Tuple[int, ...], int] = {full_row: N}
    revenue = 0

    for idx, req in enumerate(path):
        if req is None:
            continue
        req_i, req_j = req
        # 找所有可行唯一行型
        feasible_rows = [
            r for r, cnt in row_counts.items()
            if cnt > 0 and all(r[l] == 1 for l in range(req_i - 1, req_j))
        ]
        if not feasible_rows:
            continue

        # 求解 Eq. (6) 聚合版: 对每个唯一行型 g (数量 m_g)，变量 beta_{g, l} >= 0
        # min sum λ_ij z_ij + sum_g m_g * sum_{l: g_l=1} beta_{g, l}
        # s.t. z_ij + sum_{l=i..j} beta_{g, l} >= p_ij  (for each g that can serve i..j)
        rem_exp = suffix_expected[idx]
        active_rows = [r for r, cnt in row_counts.items() if cnt > 0]
        G = len(active_rows)
        n_vars = P + G * M
        c = np.zeros(n_vars, dtype=float)
        for p_i, ij in enumerate(pairs):
            c[p_i] = float(rem_exp.get(ij, 0.0))
        for g_i, r in enumerate(active_rows):
            cnt = float(row_counts[r])
            for l in range(M):
                if r[l] == 1:
                    c[P + g_i * M + l] = cnt

        ub_r, ub_c, ub_v, b_ub = [], [], [], []
        row_id = 0
        for g_i, r in enumerate(active_rows):
            for p_i, (i, j) in enumerate(pairs):
                # 只要该座位类型支持 (i, j)，加入约束
                if all(r[l] == 1 for l in range(i - 1, j)):
                    ub_r.append(row_id); ub_c.append(p_i); ub_v.append(-1.0)
                    for l in range(i - 1, j):
                        ub_r.append(row_id); ub_c.append(P + g_i * M + l); ub_v.append(-1.0)
                    b_ub.append(-float(prices[(i, j)]))
                    row_id += 1

        if row_id == 0:
            continue
        A_ub = csc_matrix((ub_v, (ub_r, ub_c)), shape=(row_id, n_vars))
        res = linprog(c, A_ub=A_ub, b_ub=np.array(b_ub), bounds=(0, None), method="highs")

        p_val = float(prices[(req_i, req_j)])
        best_gain = -1e18
        best_row = None
        best_tb = None
        for g_i, r in enumerate(active_rows):
            if not all(r[l] == 1 for l in range(req_i - 1, req_j)):
                continue
            bid = sum(res.x[P + g_i * M + l] for l in range(req_i - 1, req_j)) if res.success else 0.0
            gain = p_val - bid
            # 找该行包含 [req_i, req_j] 的最大连续区间做 Tie-Breaking
            u = req_i
            while u > 1 and r[u - 2] == 1:
                u -= 1
            v = req_j
            while v < M and r[v] == 1:
                v += 1
            tb = tie_breaking_key(u, v)
            if gain > best_gain + 1e-7 or (abs(gain - best_gain) <= 1e-7 and (best_tb is None or tb < best_tb)):
                best_gain = gain
                best_row = r
                best_tb = tb

        if best_row is not None and best_gain >= -1e-7:
            row_counts[best_row] -= 1
            if row_counts[best_row] == 0:
                del row_counts[best_row]
            nxt = list(best_row)
            for l in range(req_i - 1, req_j):
                nxt[l] = 0
            nxt_t = tuple(nxt)
            row_counts[nxt_t] = row_counts.get(nxt_t, 0) + 1
            revenue += prices[(req_i, req_j)]

    return {"revenue": revenue}


def run_maximal_sim(N, M, path, prices, suffix, fn):
    T = len(path)
    counts = {(1, M): N}
    rev = 0
    for idx, req in enumerate(path):
        if req is None:
            continue
        i, j = req
        cands = feasible_intervals(counts, i, j)
        if not cands:
            continue
        dec = fn(idx + 1, T, M, dict(counts), i, j, prices, suffix[idx])
        if dec is not None and (int(dec[0]), int(dec[1])) in cands:
            counts = apply_maximal_transition(counts, int(dec[0]), int(dec[1]), i, j)
            rev += prices[(i, j)]
    return rev


def main():
    M = 6
    prices = paper_prices(M)
    lp_solver = PaperLPBenchmarks(M, prices)

    report = {}

    # =========================================================================
    # 基准 1：M=6, N=20, T=100（60 条全新留出路径：30 Case 1 + 30 Case 2）
    # =========================================================================
    print("==================== 基准 1：小规模留出集 (M=6, N=20, T=100, 30+30 路径) ====================")
    N, T = 20, 100
    bench1 = {}
    for case, cname, seed0 in [(1, "Case1_平稳到达", 5000), (2, "Case2_短途先来", 6000)]:
        sched = build_arrival_schedule(M, T, case=case)
        suf = precompute_remaining_expected_demand(sched)
        paths = [sample_path(sched, seed0 + s) for s in range(30)]
        hos = [
            solve_hindsight_optimum_empty_train(
                N, M, dict(collections.Counter(x for x in p if x is not None)), prices
            )
            for p in paths
        ]

        methods = [
            ("MP (Myopic)", lambda p: run_maximal_sim(N, M, p, prices, suf, myopic_policy)),
            ("BPC-S (论文 Eq.6 LP)", lambda p: simulate_bpcs_exact(N, M, p, prices, suf)["revenue"]),
            ("BPC-M (论文 Eq.12 LP)", lambda p: run_maximal_sim(N, M, p, prices, suf, lp_solver.bpcm_decide)),
            ("RDP (论文 Eq.14+15 LP)", lambda p: run_maximal_sim(N, M, p, prices, suf, lp_solver.rdp_decide)),
            ("GLM-5 E097 (无求解器)", lambda p: run_maximal_sim(N, M, p, prices, suf, glm_e097_decide)),
        ]
        res_c = {}
        print(f"\n--- {cname} (平均 HO={sum(hos)/len(hos):.2f}) ---")
        for mname, runner in methods:
            t0 = time.perf_counter()
            revs = [runner(p) for p in paths]
            dt_ms = round((time.perf_counter() - t0) * 1000, 1)
            ratio = sum(r / h for r, h in zip(revs, hos)) / len(paths) * 100
            res_c[mname] = {
                "avg_rev": round(sum(revs) / len(paths), 2),
                "ratio_pct": round(ratio, 2),
                "gap_pct": round(100.0 - ratio, 2),
                "elapsed_ms": dt_ms,
            }
            print(f"  {mname:24s} | {ratio:6.2f}% (Gap {100-ratio:5.2f}%) | 30路径耗时 {dt_ms:7.1f} ms")
        bench1[cname] = res_c
    report["bench1_N20_heldout"] = bench1

    # =========================================================================
    # 基准 2：仿论文 Table 1 大列车三档稀缺度零样本泛化测试
    # 固定 M=6, T=1000（Case 2 短途先来长途后来，10 条随机路径），
    # 改变座位数 N ∈ {320 (资源较宽), 220 (中等紧张), 140 (极度紧张)}，
    # 使 MP 收益比对应论文 Table 1 的 ~96% / ~92% / ~87% 三档！
    # 同时测「准确需求估计」与「带 15% 估计误差（仿真实数据）」
    # =========================================================================
    print("\n==================== 基准 2：仿论文 Table 1 大列车三档稀缺度 (M=6, T=1000, Case 2, 10路径) ====================")
    T_big = 1000
    sched_big = build_arrival_schedule(M, T_big, case=2)
    suf_big_exact = precompute_remaining_expected_demand(sched_big)
    paths_big = [sample_path(sched_big, 9000 + s) for s in range(10)]

    # 构造带 ±15% 系统预测误差的期望需求（仿论文真实数据里的估计误差）
    rng_err = np.random.default_rng(2026)
    noise_mult = {
        (i, j): float(rng_err.uniform(0.85, 1.15))
        for i in range(1, M + 1)
        for j in range(i, M + 1)
    }
    suf_big_noisy = [
        {od: val * noise_mult[od] for od, val in d.items()} for d in suf_big_exact
    ]

    bench2 = {}
    for N_big, label in [(320, "N=320_资源较宽"), (220, "N=220_中等紧张"), (140, "N=140_极度紧张")]:
        hos = [
            solve_hindsight_optimum_empty_train(
                N_big, M, dict(collections.Counter(x for x in p if x is not None)), prices
            )
            for p in paths_big
        ]
        bench2[label] = {}
        for mode_name, suf_use in [("准确需求", suf_big_exact), ("带15%预测误差", suf_big_noisy)]:
            print(f"\n--- {label} | {mode_name} (平均 HO={sum(hos)/len(hos):.1f}) ---")
            methods = [
                ("MP (Myopic)", lambda p: run_maximal_sim(N_big, M, p, prices, suf_use, myopic_policy)),
                ("BPC-M (论文 Eq.12 LP)", lambda p: run_maximal_sim(N_big, M, p, prices, suf_use, lp_solver.bpcm_decide)),
                ("RDP (论文 Eq.14+15 LP)", lambda p: run_maximal_sim(N_big, M, p, prices, suf_use, lp_solver.rdp_decide)),
                ("GLM-5 E097 (无求解器)", lambda p: run_maximal_sim(N_big, M, p, prices, suf_use, glm_e097_decide)),
            ]
            res_m = {}
            for mname, runner in methods:
                t0 = time.perf_counter()
                revs = [runner(p) for p in paths_big]
                dt_ms = round((time.perf_counter() - t0) * 1000, 1)
                ratio = sum(r / h for r, h in zip(revs, hos)) / len(paths_big) * 100
                res_m[mname] = {
                    "avg_rev": round(sum(revs) / len(paths_big), 1),
                    "ratio_pct": round(ratio, 2),
                    "gap_pct": round(100.0 - ratio, 2),
                    "elapsed_ms": dt_ms,
                }
                print(f"  {mname:24s} | {ratio:6.2f}% (Gap {100-ratio:5.2f}%) | 10路径耗时 {dt_ms:7.1f} ms")
            bench2[label][mode_name] = res_m
    report["bench2_large_train_scarcity"] = bench2

    out_path = Path(__file__).parent / "results" / "vs_paper_methods.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✅ 与论文原版 LP 方法对决完成，结果已保存至: {out_path}")


if __name__ == "__main__":
    main()
