import json
import os
import time
from pathlib import Path
from typing import Dict, List, Tuple

from glm_client import call_glm, extract_json_block
from problem_core import (
    paper_prices,
    seat_maximal_sequences,
    solve_static_exact_bb,
    solve_static_greedy,
    validate_static_solution,
)


def build_static_instances():
    """构造 3 个递增规模的非 NSE 静态 Assign-to-Seat 算例（保证贪心明显次优）。"""
    p_sub = paper_prices(6)

    # S1: 论文 Example 1 风格的 3 座位 x 6 区间线性票价陷阱 (非 NSE)
    # 区间单价 v = [1, 1, 1, 2, 1, 2]，即 p_ij = sum_{l=i..j} v_l
    v1 = [1, 1, 1, 2, 1, 2]
    p1 = {
        (i, j): sum(v1[i - 1 : j])
        for i in range(1, 7)
        for j in range(i, 7)
    }
    c1 = [
        [1, 1, 1, 1, 1, 0],  # 座位1: [1,5]
        [0, 1, 1, 1, 1, 1],  # 座位2: [2,6]
        [1, 1, 0, 1, 1, 1],  # 座位3: [1,2] 和 [4,6]
    ]
    d1 = {
        (1, 5): 1,
        (2, 4): 1,
        (3, 6): 1,
        (1, 2): 1,
        (5, 6): 1,
        (4, 6): 1,
    }

    # S2: 5 座位 x 6 区间，非 NSE 碎片座位 + 论文次加性高铁票价 (14 条需求)
    c2 = [
        [1, 1, 1, 1, 1, 0],  # [1,5]
        [0, 1, 1, 1, 1, 1],  # [2,6]
        [1, 1, 1, 0, 1, 1],  # [1,3], [5,6]
        [1, 0, 1, 1, 1, 1],  # [1,1], [3,6]
        [1, 1, 1, 1, 1, 1],  # [1,6]
    ]
    d2 = {
        (1, 6): 1,
        (1, 4): 1,
        (2, 5): 2,
        (3, 6): 2,
        (1, 2): 2,
        (3, 4): 2,
        (5, 6): 2,
        (2, 3): 1,
        (4, 5): 1,
    }

    # S3: 8 座位 x 6 区间，更碎片化的非 NSE 矩阵 + 24 条需求
    c3 = [
        [1, 1, 1, 1, 1, 1],  # [1,6]
        [1, 1, 1, 1, 1, 0],  # [1,5]
        [0, 1, 1, 1, 1, 1],  # [2,6]
        [1, 1, 1, 0, 1, 1],  # [1,3], [5,6]
        [1, 1, 0, 1, 1, 1],  # [1,2], [4,6]
        [0, 1, 1, 1, 0, 1],  # [2,4], [6,6]
        [1, 0, 1, 1, 1, 0],  # [1,1], [3,5]
        [1, 1, 1, 1, 0, 1],  # [1,4], [6,6]
    ]
    d3 = {
        (1, 6): 1,
        (1, 5): 1,
        (2, 6): 2,
        (1, 4): 2,
        (3, 6): 2,
        (2, 5): 2,
        (1, 3): 2,
        (4, 6): 2,
        (1, 2): 3,
        (3, 4): 2,
        (5, 6): 3,
        (2, 3): 1,
        (4, 5): 1,
    }

    return [
        {"name": "S1_小规模(3座x6区间)", "C": c1, "demands": d1, "prices": p1},
        {"name": "S2_中规模(5座x6区间)", "C": c2, "demands": d2, "prices": p_sub},
        {"name": "S3_较大规模(8座x6区间)", "C": c3, "demands": d3, "prices": p_sub},
    ]


def format_problem_prompt(inst: Dict) -> str:
    C = inst["C"]
    demands = inst["demands"]
    prices = inst["prices"]
    N, M = len(C), len(C[0])

    seat_lines = []
    for k, row in enumerate(C, start=1):
        seqs = seat_maximal_sequences(row)
        seat_lines.append(f"  - 座位 {k}: 向量={row}, 可用连续区间={seqs}")

    demand_lines = []
    for (i, j), cnt in sorted(demands.items(), key=lambda x: (-prices[x[0]], x[0])):
        demand_lines.append(
            f"  - 区间 [{i}, {j}] (跨越 {j-i+1} 个leg): 票价={prices[(i, j)]}, 最大可接单数={cnt}"
        )

    return (
        f"你正在求解高铁 Assign-to-Seat 静态座位分配优化问题（不调用任何求解器，靠你自身组合推理最大化总收益）。\n"
        f"参数：共 N={N} 个座位（编号 1..{N}），M={M} 个相邻区间 leg（编号 1..{M}）。\n\n"
        f"1) 各座位初始可用区间（1=可用，0=已被占用不可分配）：\n"
        + "\n".join(seat_lines)
        + "\n\n2) 可选订单及票价（每个订单必须完整分配到同一个座位的连续可用区间上，同座位不同订单区间不能有任何重叠，每种订单接受数量不能超过最大可接单数）：\n"
        + "\n".join(demand_lines)
        + "\n\n请仔细做全局组合权衡（注意：短途组合有时总价高于长途，也要避免把好座位切碎），输出最优分配方案。\n"
        "必须只输出一个合法 JSON 对象，格式如下：\n"
        '{"assignments": [{"seat": 1, "start": 1, "end": 2}, ...], "expected_revenue": 16, "strategy_note": "简短说明"}'
    )


def run_reflexion_on_instance(inst: Dict, max_rounds: int = 4) -> Dict:
    C, demands, prices = inst["C"], inst["demands"], inst["prices"]
    exact = solve_static_exact_bb(C, demands, prices)
    greedy_total = solve_static_greedy(C, demands, prices, by_unit_price=False)
    greedy_unit = solve_static_greedy(C, demands, prices, by_unit_price=True)

    print(f"\n==================== {inst['name']} ====================")
    print(
        f"裁判最优解: {exact['revenue']} (proven={exact['proven_optimal']}, nodes={exact['nodes_searched']}) | "
        f"贪心(总价): {greedy_total['revenue']} | 贪心(单价): {greedy_unit['revenue']}"
    )

    messages = [
        {
            "role": "system",
            "content": (
                "你是精通组合优化与运筹学的专家。你要在没有外部求解器的情况下，"
                "通过严密推演和接收校验器反馈，逐轮优化高铁 Assign-to-Seat 座位分配方案。"
                "每次回复只输出严格合法的 JSON。"
            ),
        },
        {"role": "user", "content": format_problem_prompt(inst)},
    ]

    rounds = []
    best_feasible_rev = 0
    best_feasible_assign = None

    for r in range(1, max_rounds + 1):
        resp = call_glm(messages, model="glm-5", temperature=0.0, max_tokens=4096, thinking=True)
        raw_content = resp["content"]
        if not raw_content.strip():
            resp = call_glm(messages, model="glm-5", temperature=0.0, max_tokens=4096, thinking=False)
            raw_content = resp["content"]
        messages.append({"role": "assistant", "content": raw_content})

        parse_err = None
        assignments = []
        try:
            parsed = extract_json_block(raw_content)
            assignments = parsed.get("assignments", [])
        except Exception as e:
            parse_err = str(e)

        if parse_err is not None:
            val = {
                "feasible": False,
                "errors": [f"JSON 解析失败: {parse_err}"],
                "revenue": 0,
                "accepted_count": 0,
                "leftover_seat_intervals": {},
                "unmet_demands": [],
            }
        else:
            val = validate_static_solution(C, demands, prices, assignments)

        if val["feasible"] and val["revenue"] > best_feasible_rev:
            best_feasible_rev = val["revenue"]
            best_feasible_assign = assignments

        opt_ratio = round(val["revenue"] / exact["revenue"] * 100, 2) if exact["revenue"] > 0 else 0.0
        print(
            f"  [Round {r}] feasible={val['feasible']} | rev={val['revenue']}/{exact['revenue']} ({opt_ratio}%) "
            f"| errors={len(val['errors'])} | elapsed={resp['elapsed_s']}s | tokens={resp['usage'].get('total_tokens')}"
        )

        rounds.append(
            {
                "round": r,
                "feasible": val["feasible"],
                "revenue": val["revenue"],
                "opt_ratio_pct": opt_ratio,
                "errors": val["errors"],
                "elapsed_s": resp["elapsed_s"],
                "usage": resp["usage"],
                "assignments": assignments,
            }
        )

        if r == max_rounds:
            break

        # 构造真实无求解器环境下的“校验器反馈”（绝不泄露裁判最优解！）
        if not val["feasible"]:
            feedback = (
                f"【第 {r} 轮校验失败】你的方案存在以下硬约束违背：\n"
                + "\n".join(f"- {e}" for e in val["errors"][:10])
                + "\n\n请逐座核对每个座位的可用连续区间与订单起止 leg，彻底修复所有冲突，并尽量提高总收益。仅输出修正后的 JSON。"
            )
        else:
            leftover_str = json.dumps(val["leftover_seat_intervals"], ensure_ascii=False)
            unmet_str = json.dumps(val["unmet_demands"][:8], ensure_ascii=False)
            feedback = (
                f"【第 {r} 轮校验通过】当前方案完全合法，实际总收益 = {val['revenue']}（共接受 {val['accepted_count']} 单）。\n"
                f"【资源利用率诊断】\n"
                f"- 分配后仍有空余区间的座位：{leftover_str}\n"
                f"- 尚未满足的高价订单：{unmet_str}\n\n"
                "请你尝试局部重排或跨座位交换（swap / repack），看能否塞进更多未满足的高价订单、或用更高总价的组合替换当前分配，进一步提升总收益。"
                "如果你确认已无法提升，也可保留当前最优方案并输出严格合法 JSON。"
            )

        messages.append({"role": "user", "content": feedback})

    return {
        "instance": inst["name"],
        "N": len(C),
        "M": len(C[0]),
        "total_requests": sum(demands.values()),
        "exact_optimum": exact["revenue"],
        "exact_proven": exact["proven_optimal"],
        "greedy_by_total_price": greedy_total["revenue"],
        "greedy_by_unit_price": greedy_unit["revenue"],
        "glm_round1_feasible": rounds[0]["feasible"],
        "glm_round1_revenue": rounds[0]["revenue"],
        "glm_best_revenue": best_feasible_rev,
        "glm_best_opt_ratio_pct": round(best_feasible_rev / exact["revenue"] * 100, 2),
        "rounds": rounds,
    }


def main():
    out_dir = Path(__file__).parent / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for inst in build_static_instances():
        results.append(run_reflexion_on_instance(inst, max_rounds=4))

    out_path = out_dir / "exp1_static_reflexion.json"
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✅ 实验 1 完成，结果已保存至: {out_path}")


if __name__ == "__main__":
    main()
