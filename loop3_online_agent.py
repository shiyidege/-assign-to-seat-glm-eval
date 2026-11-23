import collections
import json
import time
from pathlib import Path
from typing import Dict, Optional, Tuple

from glm_client import call_glm, extract_json_block
from loop2_dynamic_evolve import audit_and_load_policy
from problem_core import (
    build_arrival_schedule,
    feasible_intervals,
    myopic_policy,
    paper_prices,
    precompute_remaining_expected_demand,
    sample_path,
    simulate_dynamic_policy,
    solve_hindsight_optimum_empty_train,
)


def main():
    M = 6
    N = 5
    T = 25
    prices = paper_prices(M)
    sched = build_arrival_schedule(M, T, case=2)
    suffix = precompute_remaining_expected_demand(sched)
    path = sample_path(sched, seed=2026)

    dem = collections.Counter(req for req in path if req is not None)
    ho = solve_hindsight_optimum_empty_train(N, M, dict(dem), prices)
    mp_res = simulate_dynamic_policy(N, M, path, prices, suffix, myopic_policy)

    # 加载实验 2 进化出的最佳纯 Python 策略（若存在）
    best_policy_path = Path(__file__).parent / "best_evolved_policy.py"
    evolved_res = None
    evolved_ms = None
    if best_policy_path.exists():
        evolved_fn = audit_and_load_policy(best_policy_path.read_text(encoding="utf-8"))
        t0 = time.perf_counter()
        evolved_res = simulate_dynamic_policy(N, M, path, prices, suffix, evolved_fn)
        evolved_ms = round((time.perf_counter() - t0) * 1000, 3)

    # 逐单调用 GLM-5 充当在线决策大脑
    call_logs = []
    total_tokens = 0
    total_api_s = 0.0

    def glm_online_policy(
        t: int,
        T_: int,
        M_: int,
        counts: Dict[Tuple[int, int], int],
        req_i: int,
        req_j: int,
        prices_: Dict[Tuple[int, int], int],
        rem_exp: Dict[Tuple[int, int], float],
    ) -> Optional[Tuple[int, int]]:
        nonlocal total_tokens, total_api_s
        cands = feasible_intervals(counts, req_i, req_j)
        if not cands:
            return None

        # 汇总各腿剩余期望需求与按长度期望需求，帮助 LLM 做在线权衡
        leg_rem = [0.0] * M_
        len_rem = collections.defaultdict(float)
        for (a, b), val in rem_exp.items():
            len_rem[b - a + 1] += val
            for l in range(a - 1, b):
                leg_rem[l] += val

        prompt = (
            f"时刻 t={t}/{T_}（非平稳 Case 2：前期短途多，后期长途多）。\n"
            f"当前请求：区间 [{req_i}, {req_j}]（长度 {req_j-req_i+1}），票价={prices_[(req_i, req_j)]}。\n"
            f"各长度票价：{[prices_[(1, l)] for l in range(1, M_+1)]}。\n"
            f"当前所有最大连续空闲区间 counts：{ {f'{u}-{v}': c for (u, v), c in sorted(counts.items())} }\n"
            f"可分配的合法候选区间：{[[u, v] for (u, v) in cands]}\n"
            f"未来剩余期望总需求（按区间 leg 1..{M_}）：{[round(x, 2) for x in leg_rem]}\n"
            f"未来剩余期望订单数（按行程长度 1..{M_}）：{ {l: round(len_rem[l], 2) for l in range(1, M_+1)} }\n\n"
            "请决策：拒绝该请求，还是接受并分配到哪个合法候选区间 [u, v]（尽量减少把长连续空座切碎，并在长途需求大时适当留座）？\n"
            '只输出 JSON：{"action": "accept" 或 "reject", "interval": [u, v] 或 null, "reason": "一句话理由"}'
        )

        resp = call_glm(
            messages=[
                {
                    "role": "system",
                    "content": "你是高铁动态收益管理实时控票助手，只输出严格 JSON。",
                },
                {"role": "user", "content": prompt},
            ],
            model="glm-5",
            temperature=0.0,
            max_tokens=512,
            thinking=False,
        )
        total_api_s += resp["elapsed_s"]
        total_tokens += resp["usage"].get("total_tokens", 0)

        chosen = None
        action = "reject"
        reason = ""
        try:
            obj = extract_json_block(resp["content"])
            action = obj.get("action", "reject")
            reason = obj.get("reason", "")
            iv = obj.get("interval")
            if action == "accept" and isinstance(iv, list) and len(iv) == 2:
                cand_tuple = (int(iv[0]), int(iv[1]))
                if cand_tuple in cands:
                    chosen = cand_tuple
        except Exception as e:
            reason = f"parse_err: {e}"

        call_logs.append(
            {
                "t": t,
                "req": [req_i, req_j],
                "price": prices_[(req_i, req_j)],
                "cands": [[u, v] for (u, v) in cands],
                "decision": list(chosen) if chosen else None,
                "reason": reason,
                "elapsed_s": resp["elapsed_s"],
            }
        )
        print(
            f"  t={t:2d}/{T_} req=[{req_i},{req_j}](p={prices_[(req_i,req_j)]}) -> "
            f"{'接 ' + str(list(chosen)) if chosen else '拒单'} ({resp['elapsed_s']}s) | {reason[:50]}"
        )
        return chosen

    print(f"==================== 实验 3：逐单 GLM-5 在线控票 (M={M}, N={N}, T={T}) ====================")
    print(f"样本路径有效到达单数: {sum(1 for x in path if x is not None)} | 事后最优上界 HO={ho}")
    glm_res = simulate_dynamic_policy(N, M, path, prices, suffix, glm_online_policy)

    report = {
        "config": {"M": M, "N": N, "T": T, "arrivals": sum(1 for x in path if x is not None)},
        "HO": ho,
        "myopic": {
            "revenue": mp_res["revenue"],
            "ho_ratio_pct": round(mp_res["revenue"] / ho * 100, 2),
        },
        "glm_per_request_agent": {
            "revenue": glm_res["revenue"],
            "ho_ratio_pct": round(glm_res["revenue"] / ho * 100, 2),
            "api_calls": len(call_logs),
            "total_api_s": round(total_api_s, 2),
            "avg_latency_s": round(total_api_s / max(1, len(call_logs)), 3),
            "total_tokens": total_tokens,
            "invalid_decisions": glm_res["invalid_decisions"],
            "trace": call_logs,
        },
        "glm_evolved_python_policy": (
            {
                "revenue": evolved_res["revenue"],
                "ho_ratio_pct": round(evolved_res["revenue"] / ho * 100, 2),
                "total_elapsed_ms": evolved_ms,
            }
            if evolved_res
            else None
        ),
    }

    print("\n--- 实验 3 对比汇总 ---")
    print(f"  HO 事后最优上界: {ho} (100.0%)")
    print(f"  Myopic 基线:     {mp_res['revenue']} ({report['myopic']['ho_ratio_pct']}%)")
    print(
        f"  GLM-5 逐单在线:  {glm_res['revenue']} ({report['glm_per_request_agent']['ho_ratio_pct']}%) "
        f"| {len(call_logs)} 次调用, 总耗时 {report['glm_per_request_agent']['total_api_s']}s, "
        f"均延迟 {report['glm_per_request_agent']['avg_latency_s']}s/单, tokens={total_tokens}"
    )
    if evolved_res:
        print(
            f"  GLM-5 进化策略:  {evolved_res['revenue']} ({report['glm_evolved_python_policy']['ho_ratio_pct']}%) "
            f"| 整条路径耗时 {evolved_ms} ms"
        )

    out_path = Path(__file__).parent / "results" / "exp3_online_agent.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ 实验 3 完成，结果已保存至: {out_path}")


if __name__ == "__main__":
    main()
