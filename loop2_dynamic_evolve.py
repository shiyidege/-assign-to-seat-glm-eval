import ast
import collections
import json
import math
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from glm_client import call_glm, extract_python_block
from problem_core import (
    build_arrival_schedule,
    myopic_policy,
    paper_prices,
    precompute_remaining_expected_demand,
    sample_path,
    simulate_dynamic_policy,
    solve_hindsight_optimum_empty_train,
)

FORBIDDEN_IMPORTS = {
    "scipy",
    "pulp",
    "ortools",
    "cvxpy",
    "coptpy",
    "gurobipy",
    "cplex",
    "highspy",
    "mip",
    "pyomo",
    "os",
    "sys",
    "subprocess",
    "socket",
    "urllib",
    "requests",
    "pathlib",
    "shutil",
}


def audit_and_load_policy(code: str) -> Callable:
    """AST 审计确保严禁调用任何外部求解器/系统模块，并加载 decide 函数。"""
    tree = ast.parse(code)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in FORBIDDEN_IMPORTS:
                    raise ValueError(f"禁止导入模块: {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                root = node.module.split(".")[0]
                if root in FORBIDDEN_IMPORTS:
                    raise ValueError(f"禁止导入模块: {node.module}")

    ns: Dict[str, Any] = {"math": math, "collections": collections}
    exec(compile(tree, "<glm_policy>", "exec"), ns)
    if "decide" not in ns or not callable(ns["decide"]):
        raise ValueError("生成的代码中未找到可调用函数 decide(...)")
    return ns["decide"]


def evaluate_policy_suite(
    policy_fn: Callable,
    M: int,
    N: int,
    T: int,
    paths_by_case: Dict[str, List[List[Optional[Tuple[int, int]]]]],
    ho_by_case: Dict[str, List[int]],
    suffix_by_case: Dict[str, List[Dict[Tuple[int, int], float]]],
    prices: Dict[Tuple[int, int], int],
) -> Dict[str, Any]:
    summary: Dict[str, Any] = {}
    t0 = time.perf_counter()

    for case_name, paths in paths_by_case.items():
        revs = []
        ratios = []
        ho_list = ho_by_case[case_name]
        acc_len = collections.defaultdict(int)
        rej_len = collections.defaultdict(int)
        stk_len = collections.defaultdict(int)
        leftover_legs = [0] * M
        total_invalid = 0
        total_frags = 0

        for idx, path in enumerate(paths):
            sim = simulate_dynamic_policy(
                N=N,
                M=M,
                path=path,
                prices=prices,
                suffix_expected=suffix_by_case[case_name],
                policy_fn=policy_fn,
            )
            rev = int(sim["revenue"])
            ho = ho_list[idx]
            revs.append(rev)
            ratios.append(rev / ho if ho > 0 else 1.0)
            total_invalid += int(sim["invalid_decisions"])
            total_frags += int(sim["final_fragments"])
            for k, v in sim["accepted_by_len"].items():
                acc_len[k] += v
            for k, v in sim["rejected_by_len"].items():
                rej_len[k] += v
            for k, v in sim["stockout_by_len"].items():
                stk_len[k] += v
            for l in range(M):
                leftover_legs[l] += sim["leftover_leg_seats"][l]

        n_paths = len(paths)
        per_len_diag = {}
        for l in range(1, M + 1):
            tot = acc_len[l] + rej_len[l] + stk_len[l]
            per_len_diag[f"len_{l}"] = {
                "accepted": round(acc_len[l] / n_paths, 2),
                "active_rejected": round(rej_len[l] / n_paths, 2),
                "stockout": round(stk_len[l] / n_paths, 2),
                "accept_rate_pct": round(acc_len[l] / tot * 100, 1) if tot > 0 else 0.0,
            }

        summary[case_name] = {
            "avg_revenue": round(sum(revs) / n_paths, 2),
            "avg_ho": round(sum(ho_list) / n_paths, 2),
            "avg_ho_ratio_pct": round(sum(ratios) / n_paths * 100, 2),
            "avg_loss_vs_ho": round((sum(ho_list) - sum(revs)) / n_paths, 2),
            "invalid_decisions": total_invalid,
            "avg_final_fragments": round(total_frags / n_paths, 2),
            "avg_leftover_per_leg": [round(x / n_paths, 2) for x in leftover_legs],
            "by_trip_length": per_len_diag,
        }

    summary["eval_elapsed_ms"] = round((time.perf_counter() - t0) * 1000, 2)
    return summary


def main():
    M = 6
    N = 20
    T = 100
    NUM_PATHS = 30
    prices = paper_prices(M)

    sched_c1 = build_arrival_schedule(M, T, case=1)
    sched_c2 = build_arrival_schedule(M, T, case=2)
    suffix_by_case = {
        "Case1_平稳到达": precompute_remaining_expected_demand(sched_c1),
        "Case2_短途先来长途后来": precompute_remaining_expected_demand(sched_c2),
    }

    paths_by_case = {
        "Case1_平稳到达": [sample_path(sched_c1, seed=1000 + s) for s in range(NUM_PATHS)],
        "Case2_短途先来长途后来": [sample_path(sched_c2, seed=2000 + s) for s in range(NUM_PATHS)],
    }

    # 用纯 Python 最小费用流计算每条路径的精确离线最优上界 HO（由论文 Theorem 2 保证精确）
    ho_by_case: Dict[str, List[int]] = {}
    for cname, paths in paths_by_case.items():
        ho_list = []
        for path in paths:
            dem = collections.Counter(req for req in path if req is not None)
            ho_list.append(solve_hindsight_optimum_empty_train(N, M, dict(dem), prices))
        ho_by_case[cname] = ho_list

    mp_eval = evaluate_policy_suite(
        myopic_policy, M, N, T, paths_by_case, ho_by_case, suffix_by_case, prices
    )
    print("==================== 基线结果 (M=6, N=20, T=100, 30条路径) ====================")
    for cname in ("Case1_平稳到达", "Case2_短途先来长途后来"):
        c = mp_eval[cname]
        print(
            f"  [Myopic 基线] {cname}: rev={c['avg_revenue']} / HO={c['avg_ho']} "
            f"({c['avg_ho_ratio_pct']}%, 损失={c['avg_loss_vs_ho']})"
        )

    out_dir = Path(__file__).parent / "results"
    out_dir.mkdir(parents=True, exist_ok=True)

    system_prompt = (
        "你是顶级的运筹学与算法设计专家，正在为高铁 Assign-to-Seat 动态容量控制问题（Zhu et al., Management Science/OR 风格）"
        "设计【完全不依赖任何外部求解器】的纯 Python 实时控票策略。\n"
        "注意：严禁导入 scipy / pulp / ortools / cvxpy / coptpy / gurobipy 等任何外部库，只能使用 Python 标准库（math, collections 等）。\n"
        "你必须输出一个可以直接执行的 Python 代码块，且内部必须定义函数：\n"
        "def decide(t, T, M, counts, req_i, req_j, prices, remaining_expected):\n"
        "参数说明：\n"
        "- t: 当前时间步 (1..T)\n"
        "- T: 总时间步\n"
        "- M: 区间总数 (legs 1..M)\n"
        "- counts: dict[(u, v), int]，当前所有座位的最大连续空闲区间 (Maximal Sequence) 数量，u<=v\n"
        "- req_i, req_j: 当前到来乘客请求的起止区间 (1 <= req_i <= req_j <= M)\n"
        "- prices: dict[(i, j), int]，票价表，次加性 p_ij = floor(10 * (j-i+1)^0.8)\n"
        "- remaining_expected: dict[(i, j), float]，从当前时刻 t 到结束 T 各行程的未来期望到达总数 lambda_{[t,T]}\n"
        "返回值：\n"
        "- 返回 None 表示拒单；\n"
        "- 返回 (u, v) 元组（必须满足 (u, v) in counts 且 counts[(u, v)] > 0 且 u <= req_i <= req_j <= v）表示接单并分配给一个包含该最大连续空闲区间的座位。\n"
        "  分配后，该 [u, v] 会消耗 1 个，并分裂出 [u, req_i-1] (若 u < req_i) 和 [req_j+1, v] (若 req_j < v)。"
    )

    init_user_prompt = (
        f"当前测试环境：M={M} 个区间，初始 N={N} 个全空座位，总时长 T={T}。\n"
        f"票价表：长度 1~6 对应票价分别为 {[prices[(1, l)] for l in range(1, M+1)]}。\n"
        f"重点难点：\n"
        "1. 存在两类需求场景：Case 1（各行程均匀到达）和 Case 2（前期大量短途先来、后期长途集中到达）。\n"
        "2. 论文基线 Myopic（见单就接）的表现：\n"
        f"   - Case 1 (平稳到达): 收益占事后最优上界 HO 的 {mp_eval['Case1_平稳到达']['avg_ho_ratio_pct']}% (均损失 {mp_eval['Case1_平稳到达']['avg_loss_vs_ho']})\n"
        f"   - Case 2 (短途先来长途后来): 收益占 HO 的 {mp_eval['Case2_短途先来长途后来']['avg_ho_ratio_pct']}% (均损失 {mp_eval['Case2_短途先来长途后来']['avg_loss_vs_ho']})\n"
        "3. 核心挑战是 Assign-to-Seat 约束：前期若把整段 [1, M] 随意拆碎给短途，后期长途来了即使每个区间总余座都够，也可能因为没有【同一座位连续空闲】而全部流失！\n"
        "4. 你可以充分利用 remaining_expected（未来剩余期望需求）和 counts（当前最大连续空闲区间分布），例如：\n"
        "   - 自己用纯 Python 写一个轻量级的非线性机会成本 / 最大连续区间影子价格近似，或者纯 Python 次梯度/对偶更新 / 护留策略 / 碎片惩罚函数！\n"
        "   - 注意单次 decide 调用要快（< 1ms），这样 30 条路径 x 100 步能秒级跑完。\n\n"
        "请给出第 1 版策略代码（只输出一个 ```python ... ``` 代码块，代码注释简要写清核心思路）。"
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": init_user_prompt},
    ]

    evolution_log = {
        "config": {"M": M, "N": N, "T": T, "num_paths": NUM_PATHS},
        "myopic_baseline": mp_eval,
        "rounds": [],
    }

    best_score = -1.0
    best_code = ""
    best_round = 0

    for r in range(1, 5):
        print(f"\n-------------------- 策略进化 Round {r} --------------------")
        resp = call_glm(messages, model="glm-5", temperature=0.15, max_tokens=4096, thinking=False, timeout=180)
        raw_content = resp["content"]
        messages.append({"role": "assistant", "content": raw_content})

        code = extract_python_block(raw_content)
        code_file = Path(__file__).parent / f"evolved_policy_r{r}.py"
        code_file.write_text(code + "\n", encoding="utf-8")

        eval_err = None
        eval_res = None
        try:
            policy_fn = audit_and_load_policy(code)
            eval_res = evaluate_policy_suite(
                policy_fn, M, N, T, paths_by_case, ho_by_case, suffix_by_case, prices
            )
        except Exception as e:
            eval_err = str(e)

        if eval_err is not None:
            print(f"  [Round {r}] ❌ 运行/审计失败: {eval_err}")
            evolution_log["rounds"].append(
                {
                    "round": r,
                    "status": "error",
                    "error": eval_err,
                    "elapsed_s": resp["elapsed_s"],
                    "usage": resp["usage"],
                    "code_file": code_file.name,
                }
            )
            messages.append(
                {
                    "role": "user",
                    "content": (
                        f"【第 {r} 轮代码运行报错】错误信息：{eval_err}\n"
                        "请修复该错误，确保只使用标准库且返回 None 或合法的 (u, v) 元组，输出完整的新 ```python ... ``` 代码。"
                    ),
                }
            )
            continue

        c1 = eval_res["Case1_平稳到达"]
        c2 = eval_res["Case2_短途先来长途后来"]
        avg_ratio = round((c1["avg_ho_ratio_pct"] + c2["avg_ho_ratio_pct"]) / 2, 2)
        if avg_ratio > best_score:
            best_score = avg_ratio
            best_code = code
            best_round = r

        print(
            f"  [Round {r}] ✅ 评测完成 ({eval_res['eval_elapsed_ms']} ms) | "
            f"Case1={c1['avg_ho_ratio_pct']}% (MP={mp_eval['Case1_平稳到达']['avg_ho_ratio_pct']}%) | "
            f"Case2={c2['avg_ho_ratio_pct']}% (MP={mp_eval['Case2_短途先来长途后来']['avg_ho_ratio_pct']}%) | "
            f"均分={avg_ratio}% | GLM耗时={resp['elapsed_s']}s"
        )

        evolution_log["rounds"].append(
            {
                "round": r,
                "status": "ok",
                "avg_ratio_pct": avg_ratio,
                "eval": eval_res,
                "elapsed_s": resp["elapsed_s"],
                "usage": resp["usage"],
                "code_file": code_file.name,
            }
        )

        if r == 4:
            break

        # 生成详细失分诊断报告反馈给 GLM-5 进行下一轮进化
        feedback = (
            f"【第 {r} 轮仿真评测反馈】（30 条随机路径均值，纯 Python 耗时 {eval_res['eval_elapsed_ms']} ms）：\n"
            f"1) Case 1（平稳到达）：\n"
            f"   - 你的策略：{c1['avg_revenue']} / HO={c1['avg_ho']} = {c1['avg_ho_ratio_pct']}%（Myopic 基线为 {mp_eval['Case1_平稳到达']['avg_ho_ratio_pct']}%）\n"
            f"   - 结束时各区间平均剩余空座：{c1['avg_leftover_per_leg']}，碎片数={c1['avg_final_fragments']}\n"
            f"   - 按行程长度统计（平均接单/主动拒单/无座流失）：{json.dumps(c1['by_trip_length'], ensure_ascii=False)}\n"
            f"2) Case 2（短途先来长途后来）：\n"
            f"   - 你的策略：{c2['avg_revenue']} / HO={c2['avg_ho']} = {c2['avg_ho_ratio_pct']}%（Myopic 基线为 {mp_eval['Case2_短途先来长途后来']['avg_ho_ratio_pct']}%）\n"
            f"   - 结束时各区间平均剩余空座：{c2['avg_leftover_per_leg']}，碎片数={c2['avg_final_fragments']}\n"
            f"   - 按行程长度统计（平均接单/主动拒单/无座流失）：{json.dumps(c2['by_trip_length'], ensure_ascii=False)}\n\n"
            "【请据此诊断并进化第 "
            f"{r+1} 版策略】：\n"
            "- 仔细看各区间结束时剩余空座是否过多（说明拒单太保守）或长途无座流失过多（说明前期拆碎了太多长连续区间、或拒短单不够）；\n"
            "- 思考如何更精确地估计每个 Maximal Sequence [u, v] 的非线性边际价值 V(u, v)（比如利用纯 Python 迭代近似对偶价格 / 贪心重排模拟未来收益差 / 保护完整连续区间）；\n"
            "- 目标是在 Case 1 和 Case 2 上【同时】显著超越 Myopic 基线并向 HO 逼近！\n"
            "请输出完整的改进版 ```python ... ``` 代码。"
        )
        messages.append({"role": "user", "content": feedback})

    if best_code:
        (Path(__file__).parent / "best_evolved_policy.py").write_text(
            best_code + "\n", encoding="utf-8"
        )
        evolution_log["best_round"] = best_round
        evolution_log["best_avg_ratio_pct"] = best_score

    out_path = out_dir / "exp2_dynamic_evolve.json"
    out_path.write_text(json.dumps(evolution_log, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✅ 实验 2 完成（最佳第 {best_round} 轮，均分 {best_score}%），结果已保存至: {out_path}")


if __name__ == "__main__":
    main()
