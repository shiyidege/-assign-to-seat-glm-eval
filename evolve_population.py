import argparse
import collections
import concurrent.futures
import json
import math
import random
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from glm_client import call_glm, extract_python_block
from loop2_dynamic_evolve import audit_and_load_policy
from problem_core import (
    apply_maximal_transition,
    build_arrival_schedule,
    feasible_intervals,
    myopic_policy,
    paper_prices,
    precompute_remaining_expected_demand,
    sample_path,
    solve_hindsight_optimum_empty_train,
)


PARADIGMS = [
    (
        "P1_纯Python最小费用流_BPCA_碎片感知",
        "用纯 Python 写一个轻量的 (M+1) 节点最小费用流 / SPFA 增广路算法来精确求解全车确定性流体收益 V(leg_caps, rem) 或对偶势能 pi[0..M]，"
        "计算接受请求 (req_i, req_j) 的腿级机会成本，同时在选座时结合 Maximal Sequence 碎片惩罚（优先贴合或保住长连续空座 [1, M]），"
        "并在供需紧张时适度提高短途门槛。注意用轻量缩放（例如需求缩放 x10 或直接浮点 SPFA，限制迭代步数）确保单次 decide < 2ms。",
    ),
    (
        "P2_纯Python次梯度对偶_BPCM",
        "仿照论文 Section 4.1 Eq.(12) 的 BPC-M 模型：直接为每个最大连续区间 [u, v] 维护非线性影子价格 beta[u, v]，"
        "在纯 Python 里用少量迭代（如 15~30 步 projected subgradient / 坐标下降 / 乘性权重）近似求解对偶问题 Eq.(12) 或动态规划松弛，"
        "再用论文准则 p_ij + beta[u, i-1] + beta[j+1, v] - beta[u, v] > 0 决定接单与选块。",
    ),
    (
        "P3_纯Python动态原问题近似_RDP",
        "仿照论文 Section 4.2 Eq.(14)-(15) 的 RDP 思路：基于当前 counts 与未来剩余期望需求 rem，在纯 Python 里通过迭代比例调整 / 贪心-重分配局部搜索"
        "（把高收益/高单价需求分配进 counts，并追踪分裂产生的新空闲块），得到当前请求 (req_i, req_j) 在未来最优计划中的建议分配量 gamma[u,i,j,v] 与拒绝量 gamma_0，"
        "若建议分配量占优则接单并分配到对应最优 [u, v]。",
    ),
    (
        "P4_严格分裂流体前向推演_Rollout",
        "写一个严格遵守 Maximal Sequence 分裂规则的全车流体前向推演估值函数 V(counts, rem)："
        "每次模拟把未来高价值/高边际需求放入最匹配的空闲块 [u, v] 时，【必须正确生成分裂后的残余空闲块 [u, a-1] 和 [b+1, v] 放回池子继续参与后续分配】！"
        "然后比较接单前 V(counts, rem_after) 与接单后 p_ij + V(counts_after, rem_after)（可结合小规模风险/方差折扣系数防止过度保守）。",
    ),
    (
        "P5_多阶段动态护留与连续性价值",
        "利用 remaining_expected 中不同行程长度（短途 L=1..2 vs 中长途 L=3..6）的未来需求结构，显式计算每条腿的供需比以及长连续块的稀缺溢价，"
        "结合论文的非线性价值特征（整块 [1, M] 的价值大于其拆碎后的子块价值之和）构造闭式/轻量递归价值函数 V(u, v)，并按净边际收益决定接拒与选座。",
    ),
    (
        "P6_方差修正流体与在线双界混合",
        "把【快速纯 Python 腿级最大权流（捕获全局跨段竞争）】与【Maximal Sequence 连续块真实分裂模拟（捕获 assign-to-seat 碎片损失）】结合起来，"
        "并对未来期望需求 remaining_expected 加入随剩余时间 (T-t)/T 自适应的保守/方差修正（小样本下确定性流体略偏乐观，适度缩放期望需求可大幅提升真实随机路径收益）。",
    ),
]


def simulate_with_timeout(
    N: int,
    M: int,
    path: List[Optional[Tuple[int, int]]],
    prices: Dict[Tuple[int, int], int],
    suffix_expected: List[Dict[Tuple[int, int], float]],
    policy_fn: Callable,
    deadline: float,
) -> Dict[str, Any]:
    T = len(path)
    counts: Dict[Tuple[int, int], int] = {(1, M): N}
    revenue = 0
    accepted_by_len: Dict[int, int] = collections.defaultdict(int)
    rejected_by_len: Dict[int, int] = collections.defaultdict(int)
    stockout_by_len: Dict[int, int] = collections.defaultdict(int)
    invalid_decisions = 0

    for idx, req in enumerate(path):
        if time.perf_counter() > deadline:
            raise TimeoutError("策略执行超时（单批超过时间上限，请降低复杂度）")
        if req is None:
            continue
        i, j = req
        trip_len = j - i + 1
        cands = feasible_intervals(counts, i, j)
        if not cands:
            stockout_by_len[trip_len] += 1
            continue

        decision = policy_fn(
            idx + 1,
            T,
            M,
            dict(counts),
            i,
            j,
            prices,
            suffix_expected[idx],
        )

        if decision is None:
            rejected_by_len[trip_len] += 1
            continue

        if (
            not isinstance(decision, (tuple, list))
            or len(decision) != 2
            or (int(decision[0]), int(decision[1])) not in cands
        ):
            invalid_decisions += 1
            rejected_by_len[trip_len] += 1
            continue

        u, v = int(decision[0]), int(decision[1])
        counts = apply_maximal_transition(counts, u, v, i, j)
        revenue += prices[(i, j)]
        accepted_by_len[trip_len] += 1

    leftover_leg_seats = [0] * M
    for (u, v), cnt in counts.items():
        for l in range(u - 1, v):
            leftover_leg_seats[l] += cnt

    return {
        "revenue": revenue,
        "invalid_decisions": invalid_decisions,
        "accepted_by_len": dict(sorted(accepted_by_len.items())),
        "rejected_by_len": dict(sorted(rejected_by_len.items())),
        "stockout_by_len": dict(sorted(stockout_by_len.items())),
        "leftover_leg_seats": leftover_leg_seats,
        "final_fragments": sum(counts.values()),
    }


def evaluate_suite_timed(
    policy_fn: Callable,
    M: int,
    N: int,
    T: int,
    paths_by_case: Dict[str, List[List[Optional[Tuple[int, int]]]]],
    ho_by_case: Dict[str, List[int]],
    suffix_by_case: Dict[str, List[Dict[Tuple[int, int], float]]],
    prices: Dict[Tuple[int, int], int],
    max_seconds: float = 4.0,
) -> Dict[str, Any]:
    t0 = time.perf_counter()
    deadline = t0 + max_seconds
    summary: Dict[str, Any] = {}

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
            sim = simulate_with_timeout(
                N, M, path, prices, suffix_by_case[case_name], policy_fn, deadline
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
            per_len_diag[f"L{l}"] = {
                "acc": round(acc_len[l] / n_paths, 2),
                "rej": round(rej_len[l] / n_paths, 2),
                "stk": round(stk_len[l] / n_paths, 2),
                "acc%": round(acc_len[l] / tot * 100, 1) if tot > 0 else 0.0,
            }

        summary[case_name] = {
            "avg_revenue": round(sum(revs) / n_paths, 2),
            "avg_ho": round(sum(ho_list) / n_paths, 2),
            "ratio_pct": round(sum(ratios) / n_paths * 100, 2),
            "gap_pct": round(100.0 - sum(ratios) / n_paths * 100, 2),
            "invalid": total_invalid,
            "frags": round(total_frags / n_paths, 2),
            "leftover": [round(x / n_paths, 2) for x in leftover_legs],
            "by_len": per_len_diag,
        }

    c1 = summary["Case1"]["ratio_pct"]
    c2 = summary["Case2"]["ratio_pct"]
    # 加权分：Case1 和 Case2 各占一半，鼓励双场景全面领先
    summary["score"] = round(0.5 * c1 + 0.5 * c2, 3)
    summary["elapsed_ms"] = round((time.perf_counter() - t0) * 1000, 2)
    return summary


def build_system_prompt() -> str:
    return (
        "你是顶级的运筹学、组合优化与算法设计专家，正在通过进化搜索为论文"
        "《Assign-to-Seat: Dynamic Capacity Control for Selling High-Speed Train Tickets》"
        "设计【完全不依赖任何外部求解器（无 COPT/Gurobi/SciPy/PuLP/OR-Tools）】的纯 Python 在线控票策略。\n"
        "硬规则：\n"
        "1. 只能使用 Python 标准库（math, collections, heapq, itertools 等），严禁导入任何第三方库或系统模块。\n"
        "2. 必须定义函数：def decide(t, T, M, counts, req_i, req_j, prices, remaining_expected):\n"
        "   - t: 1..T 当前时间步；T: 总时间步；M: 区间总数\n"
        "   - counts: dict[(u, v), int]，当前最大连续空闲区间数量\n"
        "   - req_i, req_j: 请求起止区间 (1 <= req_i <= req_j <= M)\n"
        "   - prices: dict[(i, j), int]，票价 p_ij = floor(10 * (j-i+1)^0.8)\n"
        "   - remaining_expected: dict[(i, j), float]，时刻 t..T 各行程未来期望到达总数\n"
        "3. 返回 None 表示拒单，或返回合法的 (u, v) 元组（counts[(u,v)] > 0 且 u <= req_i <= req_j <= v）。\n"
        "4. 性能要求：60 条路径 x 100 步必须在 3 秒内跑完（单次 decide < 0.5ms ~ 1.5ms）。\n"
        "5. 只输出一个 ```python ... ``` 代码块，首行用简短注释标明本版核心思路。"
    )


def format_candidate_brief(cand: Dict[str, Any]) -> str:
    ev = cand["train_eval"]
    c1, c2 = ev["Case1"], ev["Case2"]
    return (
        f"ID={cand['id']} | 范式={cand['tag']} | 综合均分={ev['score']}% "
        f"(Case1={c1['ratio_pct']}%, Case2={c2['ratio_pct']}%, 耗时={ev['elapsed_ms']}ms)\n"
        f"  Case1 剩座={c1['leftover']} | 按长度={json.dumps(c1['by_len'], ensure_ascii=False)}\n"
        f"  Case2 剩座={c2['leftover']} | 按长度={json.dumps(c2['by_len'], ensure_ascii=False)}"
    )


def build_offspring_prompt(
    op: str,
    pool: List[Dict[str, Any]],
    mp_train: Dict[str, Any],
    paradigm_idx: int,
    rng: random.Random,
    eval_idx: int,
) -> Tuple[str, str]:
    c1_mp = mp_train["Case1"]["ratio_pct"]
    c2_mp = mp_train["Case2"]["ratio_pct"]
    best = pool[0]

    header = (
        f"当前第 {eval_idx} 次进化评估（测试规格 M=6, N=20, T=100，票价 L=1..6 为 [10, 17, 24, 30, 36, 41]）。\n"
        f"Myopic 基线：Case1={c1_mp}%, Case2={c2_mp}%（均分={mp_train['score']}%）。\n"
        f"当前 Top-{len(pool)} 精英榜：\n"
        + "\n".join(
            f"  #{i+1}: ID={c['id']} [{c['tag']}] 均分={c['train_eval']['score']}% "
            f"(C1={c['train_eval']['Case1']['ratio_pct']}%, C2={c['train_eval']['Case2']['ratio_pct']}%, {c['train_eval']['elapsed_ms']}ms)"
            for i, c in enumerate(pool)
        )
        + "\n\n"
    )

    if op == "explore_paradigm":
        pname, pdesc = PARADIGMS[paradigm_idx % len(PARADIGMS)]
        prompt = (
            header
            + f"【本次进化算子：新范式探索 -> {pname}】\n"
            f"请跳出已有代码框架，围绕以下算法范式从头设计一个全新的纯 Python 无求解器策略：\n"
            f"{pdesc}\n\n"
            f"参考当前最强版本（供知悉标杆，不必沿用其结构）：\n{format_candidate_brief(best)}\n"
            "请直接输出完整可运行的 ```python ... ``` 代码。"
        )
        return pname, prompt

    if op == "crossover" and len(pool) >= 2:
        p1 = pool[0]
        others = pool[1:]
        p2 = rng.choice(others)
        prompt = (
            header
            + "【本次进化算子：双精英交叉融合（Crossover）】\n"
            "下面是种群中两个不同表现的精英策略，请取长补短，融合两者的核心优势（例如把更准的全局价值评估与更优的碎片选座/方差校准结合），"
            "构造一个在 Case1 和 Case2 上都更强的全新版本：\n\n"
            f"--- 亲本 A ---\n{format_candidate_brief(p1)}\n```python\n{p1['code']}\n```\n\n"
            f"--- 亲本 B ---\n{format_candidate_brief(p2)}\n```python\n{p2['code']}\n```\n\n"
            "请分析两者各自的失分点（看剩座和按长度流失），融合改进后输出完整 ```python ... ``` 代码。"
        )
        return f"Cross({p1['id']}+{p2['id']})", prompt

    if op == "refine_diagnostics":
        parent = pool[0] if rng.random() < 0.65 else rng.choice(pool[: min(3, len(pool))])
        prompt = (
            header
            + "【本次进化算子：基于诊断定向精修（Diagnostic Refinement）】\n"
            f"请针对以下精英策略的真实仿真诊断，定位核心数学缺陷或近似偏差并做实质性算法升级：\n"
            f"{format_candidate_brief(parent)}\n```python\n{parent['code']}\n```\n\n"
            "重点检查方向：\n"
            "1) 若流体模拟/网络流把未来期望需求当确定值（忽略随机波动），往往会导致估值偏高或偏低；\n"
            "2) 模拟分配空闲块 [u, v] 时是否忘记把分裂后的子块 [u, a-1] 和 [b+1, v] 放回池子？\n"
            "3) 是否正确处理了当前时刻 req 本身已包含在 remaining_expected 中（rem_after = rem - 1_req 或按剩余步数折算）？\n"
            "4) 能否用纯 Python 7 节点最小费用流或迭代对偶价让机会成本更精确，同时保证总耗时 < 2s？\n"
            "请输出实质改进后的完整 ```python ... ``` 代码。"
        )
        return f"Refine({parent['id']})", prompt

    # hyper_tune / local mutation
    parent = pool[0]
    prompt = (
        header
        + "【本次进化算子：冠军局部精细变异（Champion Fine-Tune）】\n"
        f"当前全场冠军如下：\n{format_candidate_brief(parent)}\n```python\n{parent['code']}\n```\n\n"
        "请在保留其核心有效机制的基础上，做一个精准、有数学依据的改进（例如：引入更精确的未来需求缩放/方差修正、改进平手 Tie-Breaking 碎片保护权重、"
        "优化剩余容量与期望需求扣减方式、或增加一步轻量迭代修正），冲击更高的 Case1 与 Case2 综合均分！\n"
        "请输出完整 ```python ... ``` 代码。"
    )
    return f"Tune({parent['id']})", prompt


def main():
    parser = argparse.ArgumentParser(description="Top-K 种群进化（无求解器纯 Python + GLM-5）")
    parser.add_argument("--rounds", type=int, default=100, help="总候选策略评估数")
    parser.add_argument("--workers", type=int, default=4, help="每代并行调用 GLM 并发数")
    parser.add_argument("--topk", type=int, default=6, help="精英池大小 K")
    parser.add_argument("--model", type=str, default="glm-5", help="GLM 模型名")
    parser.add_argument("--seed-existing", action="store_true", help="是否注入已有 best_evolved_policy.py 作为初始种子")
    parser.add_argument("--resume", action="store_true", help="是否从断点继续")
    args = parser.parse_args()

    base_dir = Path(__file__).parent
    out_dir = base_dir / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "pop_100_log.jsonl"
    state_path = out_dir / "pop_100_state.json"
    summary_path = out_dir / "pop_100_summary.json"
    best_code_path = base_dir / "best_pop100_policy.py"

    M, N, T = 6, 20, 100
    prices = paper_prices(M)
    sched_c1 = build_arrival_schedule(M, T, case=1)
    sched_c2 = build_arrival_schedule(M, T, case=2)
    suffix_by_case = {
        "Case1": precompute_remaining_expected_demand(sched_c1),
        "Case2": precompute_remaining_expected_demand(sched_c2),
    }

    # 训练集（进化打分用）：20 + 20 = 40 条路径
    train_paths = {
        "Case1": [sample_path(sched_c1, 1000 + s) for s in range(20)],
        "Case2": [sample_path(sched_c2, 2000 + s) for s in range(20)],
    }
    train_ho = {
        cname: [
            solve_hindsight_optimum_empty_train(
                N, M, dict(collections.Counter(x for x in p if x is not None)), prices
            )
            for p in plist
        ]
        for cname, plist in train_paths.items()
    }

    # 留出测试集（绝不给 GLM 看到，防过拟合）：30 + 30 = 60 条全新路径
    test_paths = {
        "Case1": [sample_path(sched_c1, 5000 + s) for s in range(30)],
        "Case2": [sample_path(sched_c2, 6000 + s) for s in range(30)],
    }
    test_ho = {
        cname: [
            solve_hindsight_optimum_empty_train(
                N, M, dict(collections.Counter(x for x in p if x is not None)), prices
            )
            for p in plist
        ]
        for cname, plist in test_paths.items()
    }

    # 原实验 2 的 30+30 基准集（用于严格横向对齐）
    bench_paths = {
        "Case1": [sample_path(sched_c1, 1000 + s) for s in range(30)],
        "Case2": [sample_path(sched_c2, 2000 + s) for s in range(30)],
    }
    bench_ho = {
        cname: [
            solve_hindsight_optimum_empty_train(
                N, M, dict(collections.Counter(x for x in p if x is not None)), prices
            )
            for p in plist
        ]
        for cname, plist in bench_paths.items()
    }

    mp_train = evaluate_suite_timed(myopic_policy, M, N, T, train_paths, train_ho, suffix_by_case, prices)
    mp_test = evaluate_suite_timed(myopic_policy, M, N, T, test_paths, test_ho, suffix_by_case, prices)
    mp_bench = evaluate_suite_timed(myopic_policy, M, N, T, bench_paths, bench_ho, suffix_by_case, prices)

    print("=========================================================================")
    print(f"🚀 Top-{args.topk} 种群进化启动 | 目标评估轮数={args.rounds} | 并发={args.workers} | 模型={args.model}")
    print(
        f"   Myopic 训练集: C1={mp_train['Case1']['ratio_pct']}% C2={mp_train['Case2']['ratio_pct']}% (均分={mp_train['score']}%)"
    )
    print(
        f"   Myopic 留出集: C1={mp_test['Case1']['ratio_pct']}% C2={mp_test['Case2']['ratio_pct']}% (均分={mp_test['score']}%)"
    )
    print("=========================================================================")

    pool: List[Dict[str, Any]] = []
    history: List[Dict[str, Any]] = []
    next_id = 1
    total_tokens = 0
    started_at = time.perf_counter()

    if args.resume and state_path.exists():
        st = json.loads(state_path.read_text(encoding="utf-8"))
        pool = st["pool"]
        history = st["history"]
        next_id = st["next_id"]
        total_tokens = st.get("total_tokens", 0)
        print(f"♻️  从断点恢复：已完成 {len(history)} 轮，当前最优训练均分 {pool[0]['train_eval']['score']}%")
    else:
        if log_path.exists():
            log_path.unlink()
        if args.seed_existing:
            for fname, tag in [
                ("best_evolved_policy.py", "Seed_R5"),
                ("evolved_policy_r7.py", "Seed_R7"),
            ]:
                pfile = base_dir / fname
                if pfile.exists():
                    code = pfile.read_text(encoding="utf-8")
                    fn = audit_and_load_policy(code)
                    tr = evaluate_suite_timed(fn, M, N, T, train_paths, train_ho, suffix_by_case, prices)
                    te = evaluate_suite_timed(fn, M, N, T, test_paths, test_ho, suffix_by_case, prices)
                    pool.append(
                        {
                            "id": f"S{len(pool)+1}",
                            "tag": tag,
                            "code": code,
                            "train_eval": tr,
                            "test_eval": te,
                        }
                    )
            pool.sort(key=lambda x: -x["train_eval"]["score"])
            print(
                f"🌱 已注入 {len(pool)} 个初始种子，当前起点：训练={pool[0]['train_eval']['score']}% | 留出={pool[0]['test_eval']['score']}%"
            )

    sys_prompt = build_system_prompt()
    rng = random.Random(20261123)

    def generate_one(task_idx: int, op: str, paradigm_idx: int) -> Dict[str, Any]:
        if not pool:
            pname, pdesc = PARADIGMS[paradigm_idx % len(PARADIGMS)]
            tag = pname
            user_prompt = (
                f"当前任务：M={M}, N={N}, T={T}，票价 L=1..6 为 [10, 17, 24, 30, 36, 41]。\n"
                f"Myopic 基线：Case1={mp_train['Case1']['ratio_pct']}%, Case2={mp_train['Case2']['ratio_pct']}%。\n"
                f"请按以下无求解器范式设计纯 Python 策略：\n{pdesc}\n只输出 ```python ... ``` 代码。"
            )
        else:
            tag, user_prompt = build_offspring_prompt(op, pool, mp_train, paradigm_idx, random.Random(task_idx * 97 + 13), task_idx)

        temp = 0.35 if op == "explore_paradigm" else (0.25 if op == "crossover" else 0.15)
        try:
            resp = call_glm(
                messages=[
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                model=args.model,
                temperature=temp,
                max_tokens=4096,
                thinking=False,
                timeout=150,
                retries=2,
            )
            raw = resp["content"]
            code = extract_python_block(raw)
            return {
                "ok": True,
                "op": op,
                "tag": tag,
                "code": code,
                "elapsed_s": resp["elapsed_s"],
                "tokens": resp["usage"].get("total_tokens", 0),
            }
        except Exception as e:
            return {
                "ok": False,
                "op": op,
                "tag": tag,
                "error": str(e),
                "elapsed_s": 0.0,
                "tokens": 0,
            }

    best_ever_train = pool[0]["train_eval"]["score"] if pool else -1.0
    best_ever_test = pool[0]["test_eval"]["score"] if pool else -1.0

    # 按代并行执行，直到达到 args.rounds 次评估
    gen_num = 0
    while len(history) < args.rounds:
        gen_num += 1
        remain = args.rounds - len(history)
        batch_size = min(args.workers, remain)

        # 规划本代多样性算子配比
        tasks = []
        for b in range(batch_size):
            eval_idx = len(history) + b + 1
            if len(pool) < 2 or eval_idx <= len(PARADIGMS):
                op = "explore_paradigm"
            else:
                r_mod = eval_idx % 5
                if r_mod == 1:
                    op = "explore_paradigm"
                elif r_mod == 2:
                    op = "crossover"
                elif r_mod in (3, 4):
                    op = "refine_diagnostics"
                else:
                    op = "hyper_tune"
            tasks.append((eval_idx, op, eval_idx - 1))

        gen_t0 = time.perf_counter()
        raw_outputs = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=batch_size) as ex:
            futs = [ex.submit(generate_one, idx, op, pidx) for (idx, op, pidx) in tasks]
            for fut in concurrent.futures.as_completed(futs):
                raw_outputs.append(fut.result())

        # 本地串行高速评测（每个 < 0.5s，且严格计时防死循环）
        gen_improved = False
        for out in raw_outputs:
            cid = f"E{next_id:03d}"
            next_id += 1
            total_tokens += out.get("tokens", 0)

            record: Dict[str, Any] = {
                "eval_num": len(history) + 1,
                "id": cid,
                "gen": gen_num,
                "op": out["op"],
                "tag": out["tag"],
                "api_s": out.get("elapsed_s", 0.0),
                "tokens": out.get("tokens", 0),
            }

            if not out["ok"]:
                record["status"] = "api_error"
                record["error"] = out["error"]
                history.append(record)
                with log_path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
                print(f"  [{record['eval_num']:3d}/{args.rounds}] ❌ {cid} API错误: {out['error'][:80]}")
                continue

            code = out["code"]
            try:
                fn = audit_and_load_policy(code)
                tr_eval = evaluate_suite_timed(
                    fn, M, N, T, train_paths, train_ho, suffix_by_case, prices, max_seconds=3.5
                )
            except Exception as e:
                record["status"] = "eval_error"
                record["error"] = str(e)
                history.append(record)
                with log_path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
                print(f"  [{record['eval_num']:3d}/{args.rounds}] ⚠️ {cid} ({out['tag']}) 运行/审计失败: {str(e)[:80]}")
                continue

            score = tr_eval["score"]
            record["status"] = "ok"
            record["train_score"] = score
            record["train_c1"] = tr_eval["Case1"]["ratio_pct"]
            record["train_c2"] = tr_eval["Case2"]["ratio_pct"]
            record["eval_ms"] = tr_eval["elapsed_ms"]

            # 若进入 Top-K 或刷新历史最佳，立刻在 60 条留出测试集验证防过拟合！
            qualifies = len(pool) < args.topk or score > pool[-1]["train_eval"]["score"]
            te_eval = None
            if qualifies:
                try:
                    te_eval = evaluate_suite_timed(
                        fn, M, N, T, test_paths, test_ho, suffix_by_case, prices, max_seconds=5.0
                    )
                    record["test_score"] = te_eval["score"]
                    record["test_c1"] = te_eval["Case1"]["ratio_pct"]
                    record["test_c2"] = te_eval["Case2"]["ratio_pct"]
                except Exception:
                    qualifies = False

            star = ""
            if qualifies and te_eval is not None:
                sig = (tr_eval["Case1"]["ratio_pct"], tr_eval["Case2"]["ratio_pct"])
                dup_idx = next(
                    (
                        i
                        for i, p in enumerate(pool)
                        if (p["train_eval"]["Case1"]["ratio_pct"], p["train_eval"]["Case2"]["ratio_pct"]) == sig
                    ),
                    None,
                )
                entry = {
                    "id": cid,
                    "tag": out["tag"],
                    "code": code,
                    "train_eval": tr_eval,
                    "test_eval": te_eval,
                }
                if dup_idx is not None:
                    if tr_eval["elapsed_ms"] < pool[dup_idx]["train_eval"]["elapsed_ms"]:
                        pool[dup_idx] = entry
                else:
                    pool.append(entry)
                pool.sort(key=lambda x: (-x["train_eval"]["score"], x["train_eval"]["elapsed_ms"]))
                pool = pool[: args.topk]

                if score > best_ever_train:
                    best_ever_train = score
                    best_ever_test = te_eval["score"]
                    best_code_path.write_text(code + "\n", encoding="utf-8")
                    gen_improved = True
                    star = " 🌟 NEW BEST!"

            history.append(record)
            with log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps({**record, "code": code}, ensure_ascii=False) + "\n")

            test_str = f" | 留出={record['test_score']}%" if "test_score" in record else ""
            print(
                f"  [{record['eval_num']:3d}/{args.rounds}] ✅ {cid} [{out['tag'][:22]:22s}] "
                f"训练={score:6.2f}% (C1={record['train_c1']:5.2f}%, C2={record['train_c2']:5.2f}%){test_str} "
                f"| {tr_eval['elapsed_ms']:6.1f}ms{star}"
            )

        # 保存断点
        state_path.write_text(
            json.dumps(
                {
                    "pool": pool,
                    "history": history,
                    "next_id": next_id,
                    "total_tokens": total_tokens,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        gen_s = round(time.perf_counter() - gen_t0, 1)
        wall_s = round(time.perf_counter() - started_at, 1)
        print(
            f"--- Gen {gen_num:2d} 完成 ({gen_s}s, 累计 {wall_s}s) | "
            f"当前冠军: {pool[0]['id']} 训练={pool[0]['train_eval']['score']}% "
            f"(C1={pool[0]['train_eval']['Case1']['ratio_pct']}%, C2={pool[0]['train_eval']['Case2']['ratio_pct']}%) | "
            f"留出={pool[0]['test_eval']['score']}% "
            f"(C1={pool[0]['test_eval']['Case1']['ratio_pct']}%, C2={pool[0]['test_eval']['Case2']['ratio_pct']}%) ---"
        )

    # 最终在原 30+30 基准集和 60 条留出集上全量复核冠军与 Top-3
    final_top = []
    for cand in pool[:3]:
        fn = audit_and_load_policy(cand["code"])
        bench_eval = evaluate_suite_timed(fn, M, N, T, bench_paths, bench_ho, suffix_by_case, prices, max_seconds=8.0)
        final_top.append(
            {
                "id": cand["id"],
                "tag": cand["tag"],
                "train_eval": cand["train_eval"],
                "test_eval": cand["test_eval"],
                "bench30_eval": bench_eval,
            }
        )

    # 确保 best_pop100_policy.py 写入最终留出测试表现最好的 Top-3 之一或训练冠军
    best_code_path.write_text(pool[0]["code"] + "\n", encoding="utf-8")

    ok_runs = [h for h in history if h.get("status") == "ok"]
    summary = {
        "config": {
            "rounds": args.rounds,
            "workers": args.workers,
            "topk": args.topk,
            "model": args.model,
            "M": M,
            "N": N,
            "T": T,
        },
        "total_evals": len(history),
        "valid_evals": len(ok_runs),
        "total_tokens": total_tokens,
        "total_wall_s": round(time.perf_counter() - started_at, 2),
        "myopic_baseline": {
            "train": mp_train,
            "test_heldout": mp_test,
            "bench30": mp_bench,
        },
        "final_top3": final_top,
        "trajectory": [
            {
                "eval_num": h["eval_num"],
                "id": h["id"],
                "op": h["op"],
                "tag": h["tag"],
                "status": h["status"],
                "train_score": h.get("train_score"),
                "train_c1": h.get("train_c1"),
                "train_c2": h.get("train_c2"),
                "test_score": h.get("test_score"),
            }
            for h in history
        ],
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    champ = final_top[0]
    print("\n=========================================================================")
    print(f"🏁 100 轮 Top-{args.topk} 种群进化全部完成！总耗时 {summary['total_wall_s']}s，有效策略 {len(ok_runs)}/{len(history)}，总 tokens={total_tokens}")
    print(f"🏆 冠军 {champ['id']} [{champ['tag']}] -> 已保存至 {best_code_path.name}")
    print(
        f"   训练集 (20+20): C1={champ['train_eval']['Case1']['ratio_pct']}% | C2={champ['train_eval']['Case2']['ratio_pct']}% | 均分={champ['train_eval']['score']}%"
    )
    print(
        f"   留出集 (30+30): C1={champ['test_eval']['Case1']['ratio_pct']}% (MP={mp_test['Case1']['ratio_pct']}%) | "
        f"C2={champ['test_eval']['Case2']['ratio_pct']}% (MP={mp_test['Case2']['ratio_pct']}%) | 均分={champ['test_eval']['score']}%"
    )
    print(
        f"   原基准 (30+30): C1={champ['bench30_eval']['Case1']['ratio_pct']}% (MP={mp_bench['Case1']['ratio_pct']}%) | "
        f"C2={champ['bench30_eval']['Case2']['ratio_pct']}% (MP={mp_bench['Case2']['ratio_pct']}%) | 均分={champ['bench30_eval']['score']}%"
    )
    print("=========================================================================")


if __name__ == "__main__":
    main()
