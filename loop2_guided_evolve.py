import collections
import json
from pathlib import Path
from typing import Dict, List

from glm_client import call_glm, extract_python_block
from loop2_dynamic_evolve import audit_and_load_policy, evaluate_policy_suite
from problem_core import (
    build_arrival_schedule,
    myopic_policy,
    paper_prices,
    precompute_remaining_expected_demand,
    sample_path,
    solve_hindsight_optimum_empty_train,
)


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

    prev_code = (Path(__file__).parent / "evolved_policy_r4.py").read_text(encoding="utf-8")
    prev_json = json.loads(
        (Path(__file__).parent / "results" / "exp2_dynamic_evolve.json").read_text(encoding="utf-8")
    )
    r4_c1 = prev_json["rounds"][-1]["eval"]["Case1_平稳到达"]
    r4_c2 = prev_json["rounds"][-1]["eval"]["Case2_短途先来长途后来"]

    system_prompt = (
        "你是顶级的运筹学与算法专家，正在为论文《Assign-to-Seat: Dynamic Capacity Control for Selling High-Speed Train Tickets》"
        "设计【完全不依赖任何外部求解器（无 COPT/Gurobi/SciPy/PuLP）】的纯 Python 实时控票策略。\n"
        "只允许使用 Python 标准库（math, collections 等）。必须定义函数：\n"
        "def decide(t, T, M, counts, req_i, req_j, prices, remaining_expected):"
    )

    guided_prompt = (
        f"此前盲试 4 轮的最佳代码（Round 4）结果不如 Myopic 基线：\n"
        f"- Myopic 基线：Case1 = {mp_eval['Case1_平稳到达']['avg_ho_ratio_pct']}%, Case2 = {mp_eval['Case2_短途先来长途后来']['avg_ho_ratio_pct']}%\n"
        f"- 你上一版 Round 4：Case1 = {r4_c1['avg_ho_ratio_pct']}% (剩座 {r4_c1['avg_leftover_per_leg']}), "
        f"Case2 = {r4_c2['avg_ho_ratio_pct']}% (剩座 {r4_c2['avg_leftover_per_leg']})\n\n"
        "【核心数学提示（基于论文 Section 4.1 BPC-M 与 Section 3 定理 2，仍严禁调外部求解器）】：\n"
        "1. 上一版失分根因：用【全车总需求】去和【单个座位 seats=1】比，导致每个空闲块的机会成本严重高估，拒掉了大量高收益订单、结束时剩了一堆空座！\n"
        "2. 论文的核心思想其实是计算【当前全车供给 counts 与全车未来期望需求 remaining_expected】之间的真实边际影子价格：\n"
        "   - 提示 A（无求解器纯 Python 算精确/近似全车确定性最优）：在全车层面，可以把当前各最大连续空闲区间 counts 与未来剩余期望需求 remaining_expected 做一个极轻量的【确定性流体模拟 / 迭代次梯度对偶（Projected Subgradient）或纯 Python 7节点最大权网络流（仅 7 个点，SPFA 跑一次不到 0.1ms！）】来估算当前状态 f(counts, rem) 的总未来期望收益，或者直接计算每个区间 [u, v] 的边际价值 β[u, v] = V(counts) - V(counts - e_{uv})！\n"
        "   - 提示 B（BPC-M 决策准则）：一旦能准确估算把请求 (req_i, req_j) 塞进某个候选区间 [u, v] 前后的全车未来期望总收益差 ΔV = V(after) - V(before)，只要 p_ij + ΔV > 0 就接单，且选使 p_ij + ΔV 最大的 [u, v]（若多个平手，按论文 Tie-Breaking 选 u 最大、v 最小的）！\n"
        "   - 提示 C（警惕碎片化惩罚）：除了聚合腿容量，如果只看聚合流可能会忽略长连续块被切碎的损失，所以可以直接模拟在 Maximal Sequence counts 上的贪心/按单价排序填充（Fluid Primal Rollout），直接比较【拒单后的全车未来收益 V(counts, rem_after)】vs【把 (i,j) 塞进 [u,v] 后新状态 counts' 的未来收益 V(counts', rem_after) + p_ij】！\n\n"
        "请基于以上洞察，彻底重构一个纯 Python、高精度的 `decide(...)` 策略（注意保持单次调用速度 < 2ms，不要死循环）。只输出 ```python ... ``` 代码块。"
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"上一版代码参考：\n```python\n{prev_code}\n```\n\n{guided_prompt}"},
    ]

    rounds = []
    best_score = -1.0
    best_code = ""
    best_round = 0

    for r in range(5, 8):
        print(f"\n-------------------- 论文引导进化 Round {r} --------------------")
        resp = call_glm(messages, model="glm-5", temperature=0.1, max_tokens=4096, thinking=False, timeout=180)
        raw_content = resp["content"]
        messages.append({"role": "assistant", "content": raw_content})

        code = extract_python_block(raw_content)
        code_file = Path(__file__).parent / f"evolved_policy_r{r}.py"
        code_file.write_text(code + "\n", encoding="utf-8")

        try:
            policy_fn = audit_and_load_policy(code)
            eval_res = evaluate_policy_suite(
                policy_fn, M, N, T, paths_by_case, ho_by_case, suffix_by_case, prices
            )
        except Exception as e:
            print(f"  [Round {r}] ❌ 运行/审计失败: {e}")
            rounds.append({"round": r, "status": "error", "error": str(e), "elapsed_s": resp["elapsed_s"]})
            messages.append(
                {
                    "role": "user",
                    "content": f"代码运行报错：{e}。请修复并输出完整纯 Python 代码。",
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
            f"均分={avg_ratio}% | 剩座C1={c1['avg_leftover_per_leg']} C2={c2['avg_leftover_per_leg']} | GLM耗时={resp['elapsed_s']}s"
        )

        rounds.append(
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

        if r == 7:
            break

        fb = (
            f"【第 {r} 轮引导进化反馈】（总耗时 {eval_res['eval_elapsed_ms']} ms）：\n"
            f"- Case 1（平稳到达）：你的策略 {c1['avg_ho_ratio_pct']}%（MP={mp_eval['Case1_平稳到达']['avg_ho_ratio_pct']}%），"
            f"剩座={c1['avg_leftover_per_leg']}，按长度统计={json.dumps(c1['by_trip_length'], ensure_ascii=False)}\n"
            f"- Case 2（短途先来长途后来）：你的策略 {c2['avg_ho_ratio_pct']}%（MP={mp_eval['Case2_短途先来长途后来']['avg_ho_ratio_pct']}%），"
            f"剩座={c2['avg_leftover_per_leg']}，按长度统计={json.dumps(c2['by_trip_length'], ensure_ascii=False)}\n\n"
            "请分析当前剩座分布与各长度接单/拒单/无座流失情况，继续调优你的纯 Python 估值或碎片惩罚细节，力争在 Case 1 和 Case 2 上双双继续提分！只输出完整 ```python ... ``` 代码。"
        )
        messages.append({"role": "user", "content": fb})

    if best_code:
        (Path(__file__).parent / "best_evolved_policy.py").write_text(
            best_code + "\n", encoding="utf-8"
        )

    out_path = Path(__file__).parent / "results" / "exp2_guided_evolve.json"
    out_path.write_text(
        json.dumps(
            {
                "myopic_baseline": mp_eval,
                "best_round": best_round,
                "best_avg_ratio_pct": best_score,
                "rounds": rounds,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\n✅ 引导进化完成（最佳 Round {best_round}，均分 {best_score}%），结果已保存至: {out_path}")


if __name__ == "__main__":
    main()
