#!/usr/bin/env python3
"""本目录脚本：自动把上级实验仓库加入 sys.path，以便复用 problem_core / glm_client / E097。"""
import sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

"""
把论文全部动态方法（MP / BPC-S / BPC-M / RDP）接到可选开源求解器组件上，
用 SCIP / CBC / GLOP / CLP / HiGHS 全量跑留出集，并与纯 AI E097 对比。
"""

from __future__ import annotations

import collections
import json
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
from scipy.sparse import csc_matrix

from best_pop100_policy import decide as e097_decide
from problem_core import (
    apply_maximal_transition,
    build_arrival_schedule,
    feasible_intervals,
    myopic_policy,
    paper_prices,
    precompute_remaining_expected_demand,
    sample_path,
    solve_hindsight_optimum_empty_train,
    tie_breaking_key,
)
from solver_toolkit import available_solvers, solve_lp


class PaperMethodsViaToolkit:
    def __init__(self, M: int, prices: Dict[Tuple[int, int], int], solver: str = "glop"):
        self.M = M
        self.prices = prices
        self.solver = solver
        self.pairs = [(u, v) for u in range(1, M + 1) for v in range(u, M + 1)]
        self.pair_idx = {p: i for i, p in enumerate(self.pairs)}
        self.n_pairs = len(self.pairs)

        self.quads = [
            (u, i, j, v)
            for u in range(1, M + 1)
            for i in range(u, M + 1)
            for j in range(i, M + 1)
            for v in range(j, M + 1)
        ]
        self.quad_idx = {q: i for i, q in enumerate(self.quads)}
        self.n_quads = len(self.quads)

        P = self.n_pairs
        rows, cols, vals, b_ub = [], [], [], []
        for q_i, (u, i, j, v) in enumerate(self.quads):
            b_ub.append(-float(prices[(i, j)]))
            rows.append(q_i); cols.append(self.pair_idx[(i, j)]); vals.append(-1.0)
            rows.append(q_i); cols.append(P + self.pair_idx[(u, v)]); vals.append(-1.0)
            if u < i:
                rows.append(q_i); cols.append(P + self.pair_idx[(u, i - 1)]); vals.append(1.0)
            if j < v:
                rows.append(q_i); cols.append(P + self.pair_idx[(j + 1, v)]); vals.append(1.0)
        self.bpcm_A_ub = csc_matrix((vals, (rows, cols)), shape=(self.n_quads, 2 * P))
        self.bpcm_b_ub = np.asarray(b_ub, dtype=float)

        Q = self.n_quads
        self.rdp_c = np.zeros(Q + P, dtype=float)
        for q_i, (u, i, j, v) in enumerate(self.quads):
            self.rdp_c[q_i] = -float(prices[(i, j)])

        eq_r, eq_c, eq_v = [], [], []
        for q_i, (u, i, j, v) in enumerate(self.quads):
            eq_r.append(self.pair_idx[(i, j)]); eq_c.append(q_i); eq_v.append(1.0)
        for p_i in range(P):
            eq_r.append(p_i); eq_c.append(Q + p_i); eq_v.append(1.0)
        self.rdp_A_eq = csc_matrix((eq_v, (eq_r, eq_c)), shape=(P, Q + P))

        ub_r, ub_c, ub_v = [], [], []
        for q_i, (u, i, j, v) in enumerate(self.quads):
            ub_r.append(self.pair_idx[(u, v)]); ub_c.append(q_i); ub_v.append(1.0)
            if u < i:
                ub_r.append(self.pair_idx[(u, i - 1)]); ub_c.append(q_i); ub_v.append(-1.0)
            if j < v:
                ub_r.append(self.pair_idx[(j + 1, v)]); ub_c.append(q_i); ub_v.append(-1.0)
        self.rdp_A_ub = csc_matrix((ub_v, (ub_r, ub_c)), shape=(P, Q + P))

        self.quads_by_ij: Dict[Tuple[int, int], List[Tuple[int, int, int]]] = collections.defaultdict(list)
        for q_i, (u, i, j, v) in enumerate(self.quads):
            self.quads_by_ij[(i, j)].append((q_i, u, v))

    def bpcm_decide(self, t, T, M, counts, req_i, req_j, prices, rem_exp):
        cands = feasible_intervals(counts, req_i, req_j)
        if not cands:
            return None
        P = self.n_pairs
        c = np.zeros(2 * P, dtype=float)
        for p_i, ij in enumerate(self.pairs):
            c[p_i] = float(rem_exp.get(ij, 0.0))
            c[P + p_i] = float(counts.get(ij, 0))
        res = solve_lp(
            c,
            A_ub=self.bpcm_A_ub,
            b_ub=self.bpcm_b_ub,
            bounds=[(0.0, None)] * (2 * P),
            solver=self.solver,
            time_limit_s=1.0,
        )
        if not res["ok"]:
            return cands[0]
        beta = res["x"][P:]
        p_val = float(prices[(req_i, req_j)])
        best_gain, best_uv = -1e18, None
        for (u, v) in cands:
            b_uv = beta[self.pair_idx[(u, v)]]
            b_left = beta[self.pair_idx[(u, req_i - 1)]] if u < req_i else 0.0
            b_right = beta[self.pair_idx[(req_j + 1, v)]] if req_j < v else 0.0
            gain = p_val + b_left + b_right - b_uv
            if gain > best_gain + 1e-7:
                best_gain, best_uv = gain, (u, v)
        if best_uv is not None and best_gain >= -1e-7:
            return best_uv
        return None

    def rdp_decide(self, t, T, M, counts, req_i, req_j, prices, rem_exp):
        cands = feasible_intervals(counts, req_i, req_j)
        if not cands:
            return None
        P, Q = self.n_pairs, self.n_quads
        b_eq = np.array([float(rem_exp.get(ij, 0.0)) for ij in self.pairs], dtype=float)
        b_ub = np.array([float(counts.get(uv, 0)) for uv in self.pairs], dtype=float)
        bounds = [(0.0, None)] * (Q + P)
        for q_i, u, v in self.quads_by_ij[(req_i, req_j)]:
            bounds[q_i] = (0.0, float(counts.get((u, v), 0)))
        res = solve_lp(
            self.rdp_c,
            A_ub=self.rdp_A_ub,
            b_ub=b_ub,
            A_eq=self.rdp_A_eq,
            b_eq=b_eq,
            bounds=bounds,
            solver=self.solver,
            time_limit_s=1.0,
        )
        if not res["ok"]:
            return cands[0]
        x = res["x"]
        best_val, best_uv = -1.0, None
        for (u, v) in cands:
            val = float(x[self.quad_idx[(u, req_i, req_j, v)]])
            if val > best_val + 1e-7:
                best_val, best_uv = val, (u, v)
        rej_val = float(x[Q + self.pair_idx[(req_i, req_j)]])
        if rej_val > best_val + 1e-7:
            return None
        return best_uv


def simulate_bpcs_via_toolkit(N, M, path, prices, suffix_expected, solver: str) -> int:
    pairs = [(i, j) for i in range(1, M + 1) for j in range(i, M + 1)]
    P = len(pairs)
    full_row = tuple([1] * M)
    row_counts: Dict[Tuple[int, ...], int] = {full_row: N}
    revenue = 0

    for idx, req in enumerate(path):
        if req is None:
            continue
        req_i, req_j = req
        if not any(
            cnt > 0 and all(r[l] == 1 for l in range(req_i - 1, req_j))
            for r, cnt in row_counts.items()
        ):
            continue

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
                if all(r[l] == 1 for l in range(i - 1, j)):
                    ub_r.append(row_id); ub_c.append(p_i); ub_v.append(-1.0)
                    for l in range(i - 1, j):
                        ub_r.append(row_id); ub_c.append(P + g_i * M + l); ub_v.append(-1.0)
                    b_ub.append(-float(prices[(i, j)]))
                    row_id += 1
        if row_id == 0:
            continue

        A_ub = csc_matrix((ub_v, (ub_r, ub_c)), shape=(row_id, n_vars))
        res = solve_lp(
            c,
            A_ub=A_ub,
            b_ub=b_ub,
            bounds=[(0.0, None)] * n_vars,
            solver=solver,
            time_limit_s=1.0,
        )
        x = res["x"] if res["ok"] else None

        p_val = float(prices[(req_i, req_j)])
        best_gain, best_row, best_tb = -1e18, None, None
        for g_i, r in enumerate(active_rows):
            if not all(r[l] == 1 for l in range(req_i - 1, req_j)):
                continue
            bid = sum(x[P + g_i * M + l] for l in range(req_i - 1, req_j)) if x is not None else 0.0
            gain = p_val - bid
            u = req_i
            while u > 1 and r[u - 2] == 1:
                u -= 1
            v = req_j
            while v < M and r[v] == 1:
                v += 1
            tb = tie_breaking_key(u, v)
            if gain > best_gain + 1e-7 or (abs(gain - best_gain) <= 1e-7 and (best_tb is None or tb < best_tb)):
                best_gain, best_row, best_tb = gain, r, tb

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
    return revenue


def run_maximal_sim(N, M, path, prices, suffix, fn):
    counts = {(1, M): N}
    rev = 0
    for idx, req in enumerate(path):
        if req is None:
            continue
        i, j = req
        cands = feasible_intervals(counts, i, j)
        if not cands:
            continue
        dec = fn(idx + 1, len(path), M, dict(counts), i, j, prices, suffix[idx])
        if dec is not None and (int(dec[0]), int(dec[1])) in cands:
            counts = apply_maximal_transition(counts, int(dec[0]), int(dec[1]), i, j)
            rev += prices[(i, j)]
    return rev


def eval_suite(N, M, paths, hos, prices, suffix, runner):
    t0 = time.perf_counter()
    revs = [runner(p) for p in paths]
    dt = (time.perf_counter() - t0) * 1000
    ratio = sum(r / h for r, h in zip(revs, hos)) / len(paths) * 100
    return {
        "avg_rev": round(sum(revs) / len(paths), 2),
        "ratio_pct": round(ratio, 2),
        "gap_pct": round(100 - ratio, 2),
        "elapsed_ms": round(dt, 1),
    }


def main():
    avail = available_solvers()
    backends = [b for b in ("glop", "clp", "cbc", "scip", "highs") if avail.get(b)]
    print("可用求解器:", backends)

    M, N, T = 6, 20, 100
    prices = paper_prices(M)

    paths, hos, suf = {}, {}, {}
    for case, name, seed0 in [(1, "Case1", 5000), (2, "Case2", 6000)]:
        sched = build_arrival_schedule(M, T, case=case)
        suf[name] = precompute_remaining_expected_demand(sched)
        ps = [sample_path(sched, seed0 + s) for s in range(30)]
        paths[name] = ps
        hos[name] = [
            solve_hindsight_optimum_empty_train(
                N, M, dict(collections.Counter(x for x in p if x is not None)), prices
            )
            for p in ps
        ]

    report = {"available": avail, "backends": backends, "heldout_N20": {}}

    # Baselines without toolkit LP
    print("\n===== 基线：MP / 纯AI E097 =====")
    for bname, fn in [("MP (Myopic)", myopic_policy), ("GLM-5 E097 (纯AI)", e097_decide)]:
        report["heldout_N20"][bname] = {}
        scores = []
        for cname in ("Case1", "Case2"):
            r = eval_suite(
                N, M, paths[cname], hos[cname], prices, suf[cname],
                lambda p, f=fn: run_maximal_sim(N, M, p, prices, suf[cname], f),
            )
            report["heldout_N20"][bname][cname] = r
            scores.append(r["ratio_pct"])
            print(f"  {bname:28s} {cname}: {r['ratio_pct']:6.2f}% | {r['elapsed_ms']:8.1f} ms")
        report["heldout_N20"][bname]["mean"] = round(sum(scores) / 2, 2)

    # Paper methods × backends
    for backend in backends:
        print(f"\n===== 论文方法 via toolkit({backend}) =====")
        lp = PaperMethodsViaToolkit(M, prices, solver=backend)
        for method_name in ("BPC-S", "BPC-M", "RDP"):
            key = f"{method_name} via {backend}"
            report["heldout_N20"][key] = {}
            scores = []
            for cname in ("Case1", "Case2"):
                suf_use = suf[cname]
                if method_name == "BPC-S":
                    runner = lambda p, s=backend, su=suf_use: simulate_bpcs_via_toolkit(N, M, p, prices, su, s)
                elif method_name == "BPC-M":
                    runner = lambda p, f=lp.bpcm_decide, su=suf_use: run_maximal_sim(N, M, p, prices, su, f)
                else:
                    runner = lambda p, f=lp.rdp_decide, su=suf_use: run_maximal_sim(N, M, p, prices, su, f)
                r = eval_suite(N, M, paths[cname], hos[cname], prices, suf[cname], runner)
                report["heldout_N20"][key][cname] = r
                scores.append(r["ratio_pct"])
                print(f"  {key:28s} {cname}: {r['ratio_pct']:6.2f}% | {r['elapsed_ms']:8.1f} ms", flush=True)
            report["heldout_N20"][key]["mean"] = round(sum(scores) / 2, 2)

    # Compact ranking table
    print("\n===== 留出集均分排名 =====")
    ranking = sorted(
        ((k, v["mean"]) for k, v in report["heldout_N20"].items()),
        key=lambda x: -x[1],
    )
    report["ranking_mean"] = [{"method": k, "mean": m} for k, m in ranking]
    for i, (k, m) in enumerate(ranking, 1):
        print(f"  #{i:02d} {m:6.2f}%  {k}")

    out = Path(__file__).parent / "results" / "all_methods_via_toolkit.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✅ 已保存 {out}")


if __name__ == "__main__":
    main()
