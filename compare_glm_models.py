import collections
import concurrent.futures
import json
import random
import time
from pathlib import Path
from typing import Any, Dict, List

from evolve_population import (
    PARADIGMS,
    build_offspring_prompt,
    build_system_prompt,
    evaluate_suite_timed,
)
from glm_client import call_glm, extract_json_block, extract_python_block
from loop1_static_reflexion import build_static_instances, format_problem_prompt
from loop2_dynamic_evolve import audit_and_load_policy
from problem_core import (
    build_arrival_schedule,
    myopic_policy,
    paper_prices,
    precompute_remaining_expected_demand,
    sample_path,
    solve_hindsight_optimum_empty_train,
    solve_static_exact_bb,
    validate_static_solution,
)


def run_static_benchmark_for_model(req_model: str, max_rounds: int = 4) -> List[Dict[str, Any]]:
    out = []
    for inst in build_static_instances():
        C, demands, prices = inst["C"], inst["demands"], inst["prices"]
        exact = solve_static_exact_bb(C, demands, prices)
        messages = [
            {
                "role": "system",
                "content": "你是精通组合优化的专家。不用外部求解器，每次只输出严格合法 JSON。",
            },
            {"role": "user", "content": format_problem_prompt(inst)},
        ]
        best_rev = 0
        backend = req_model
        rounds = []
        t_start = time.perf_counter()
        for r in range(1, max_rounds + 1):
            resp = call_glm(
                messages, model=req_model, temperature=0.0, max_tokens=4096, thinking=False, timeout=120
            )
            backend = resp["model_returned"]
            raw = resp["content"]
            messages.append({"role": "assistant", "content": raw})
            try:
                assigns = extract_json_block(raw).get("assignments", [])
                val = validate_static_solution(C, demands, prices, assigns)
            except Exception as e:
                val = {
                    "feasible": False,
                    "errors": [str(e)],
                    "revenue": 0,
                    "accepted_count": 0,
                    "leftover_seat_intervals": {},
                    "unmet_demands": [],
                }
            if val["feasible"] and val["revenue"] > best_rev:
                best_rev = val["revenue"]
            rounds.append(
                {
                    "round": r,
                    "feasible": val["feasible"],
                    "revenue": val["revenue"],
                    "ratio_pct": round(val["revenue"] / exact["revenue"] * 100, 2),
                    "elapsed_s": resp["elapsed_s"],
                }
            )
            if r == max_rounds:
                break
            if not val["feasible"]:
                fb = (
                    "【校验失败】冲突如下：\n"
                    + "\n".join("- " + x for x in val["errors"][:8])
                    + "\n请彻底修复所有冲突并尽量提高总收益，输出严格 JSON。"
                )
            else:
                fb = (
                    f"【校验通过】合法收益={val['revenue']}（共接 {val['accepted_count']} 单）。\n"
                    f"剩余空座={json.dumps(val['leftover_seat_intervals'], ensure_ascii=False)}\n"
                    f"未满足高价单={json.dumps(val['unmet_demands'][:8], ensure_ascii=False)}\n"
                    "请尝试跨座重排进一步提分，输出严格 JSON。"
                )
            messages.append({"role": "user", "content": fb})

        ratio = round(best_rev / exact["revenue"] * 100, 2)
        print(
            f"  [静态 {req_model}->{backend}] {inst['name']}: best={best_rev}/{exact['revenue']} ({ratio}%) "
            f"| 轮次={[x['revenue'] if x['feasible'] else 'X' for x in rounds]} | {round(time.perf_counter()-t_start,1)}s"
        )
        out.append(
            {
                "instance": inst["name"],
                "req_model": req_model,
                "backend": backend,
                "exact": exact["revenue"],
                "best_revenue": best_rev,
                "best_ratio_pct": ratio,
                "gap_pct": round(100.0 - ratio, 2),
                "rounds": rounds,
            }
        )
    return out


def run_evolution_for_model(
    req_model: str,
    rounds_total: int,
    workers: int,
    M: int,
    N: int,
    T: int,
    prices: Dict,
    suffix_by_case: Dict,
    train_paths: Dict,
    train_ho: Dict,
    test_paths: Dict,
    test_ho: Dict,
    mp_train: Dict,
) -> Dict[str, Any]:
    sys_prompt = build_system_prompt()
    pool: List[Dict[str, Any]] = []
    history: List[Dict[str, Any]] = []
    total_tokens = 0
    backend_seen = req_model
    t0 = time.perf_counter()

    def gen_one(eval_idx: int, op: str, pidx: int) -> Dict[str, Any]:
        if not pool:
            pname, pdesc = PARADIGMS[pidx % len(PARADIGMS)]
            tag = pname
            user_prompt = (
                f"当前任务：M={M}, N={N}, T={T}，票价 L=1..6 为 [10, 17, 24, 30, 36, 41]。\n"
                f"Myopic 基线：Case1={mp_train['Case1']['ratio_pct']}%, Case2={mp_train['Case2']['ratio_pct']}%。\n"
                f"请按以下无求解器范式设计纯 Python 策略：\n{pdesc}\n只输出 ```python ... ``` 代码。"
            )
        else:
            tag, user_prompt = build_offspring_prompt(
                op, pool, mp_train, pidx, random.Random(eval_idx * 97 + 13), eval_idx
            )
        temp = 0.35 if op == "explore_paradigm" else (0.25 if op == "crossover" else 0.15)
        try:
            resp = call_glm(
                messages=[
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                model=req_model,
                temperature=temp,
                max_tokens=4096,
                thinking=False,
                timeout=120,
                retries=2,
            )
            return {
                "ok": True,
                "backend": resp["model_returned"],
                "op": op,
                "tag": tag,
                "code": extract_python_block(resp["content"]),
                "elapsed_s": resp["elapsed_s"],
                "tokens": resp["usage"].get("total_tokens", 0),
            }
        except Exception as e:
            return {"ok": False, "backend": req_model, "op": op, "tag": tag, "error": str(e), "tokens": 0, "elapsed_s": 0.0}

    while len(history) < rounds_total:
        batch_size = min(workers, rounds_total - len(history))
        tasks = []
        for b in range(batch_size):
            eval_idx = len(history) + b + 1
            if len(pool) < 2 or eval_idx <= len(PARADIGMS):
                op = "explore_paradigm"
            else:
                r_mod = eval_idx % 5
                op = (
                    "explore_paradigm"
                    if r_mod == 1
                    else ("crossover" if r_mod == 2 else ("refine_diagnostics" if r_mod in (3, 4) else "hyper_tune"))
                )
            tasks.append((eval_idx, op, eval_idx - 1))

        outs = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=batch_size) as ex:
            futs = [ex.submit(gen_one, i, op, p) for (i, op, p) in tasks]
            for fut in concurrent.futures.as_completed(futs):
                outs.append(fut.result())

        for out in outs:
            backend_seen = out.get("backend", backend_seen)
            total_tokens += out.get("tokens", 0)
            eid = f"{req_model}_E{len(history)+1:02d}"
            if not out["ok"]:
                history.append({"id": eid, "status": "api_error", "error": out["error"], "api_s": out["elapsed_s"]})
                continue
            try:
                fn = audit_and_load_policy(out["code"])
                tr = evaluate_suite_timed(fn, M, N, T, train_paths, train_ho, suffix_by_case, prices, max_seconds=3.5)
                te = evaluate_suite_timed(fn, M, N, T, test_paths, test_ho, suffix_by_case, prices, max_seconds=5.0)
            except Exception as e:
                history.append({"id": eid, "status": "eval_error", "error": str(e), "api_s": out["elapsed_s"]})
                continue

            entry = {"id": eid, "tag": out["tag"], "code": out["code"], "train_eval": tr, "test_eval": te}
            pool.append(entry)
            pool.sort(key=lambda x: (-x["train_eval"]["score"], x["train_eval"]["elapsed_ms"]))
            pool = pool[:6]
            history.append(
                {
                    "id": eid,
                    "status": "ok",
                    "tag": out["tag"],
                    "train_score": tr["score"],
                    "train_c1": tr["Case1"]["ratio_pct"],
                    "train_c2": tr["Case2"]["ratio_pct"],
                    "test_score": te["score"],
                    "test_c1": te["Case1"]["ratio_pct"],
                    "test_c2": te["Case2"]["ratio_pct"],
                    "api_s": out["elapsed_s"],
                }
            )

        best = pool[0] if pool else None
        if best:
            print(
                f"  [进化 {req_model}->{backend_seen}] {len(history):2d}/{rounds_total} | "
                f"当前冠军 训练={best['train_eval']['score']}% (C1={best['train_eval']['Case1']['ratio_pct']}%, C2={best['train_eval']['Case2']['ratio_pct']}%) | "
                f"留出={best['test_eval']['score']}% (C1={best['test_eval']['Case1']['ratio_pct']}%, C2={best['test_eval']['Case2']['ratio_pct']}%)"
            )

    ok_runs = [h for h in history if h["status"] == "ok"]
    best = pool[0] if pool else None
    return {
        "req_model": req_model,
        "backend": backend_seen,
        "rounds": rounds_total,
        "valid_rate": f"{len(ok_runs)}/{len(history)}",
        "valid_count": len(ok_runs),
        "total_tokens": total_tokens,
        "wall_s": round(time.perf_counter() - t0, 1),
        "avg_api_s": round(sum(h.get("api_s", 0.0) for h in history) / max(1, len(history)), 2),
        "best_train": best["train_eval"] if best else None,
        "best_test": best["test_eval"] if best else None,
        "best_tag": best["tag"] if best else None,
        "history": history,
    }


def main():
    M, N, T = 6, 20, 100
    prices = paper_prices(M)
    sched_c1 = build_arrival_schedule(M, T, case=1)
    sched_c2 = build_arrival_schedule(M, T, case=2)
    suffix_by_case = {
        "Case1": precompute_remaining_expected_demand(sched_c1),
        "Case2": precompute_remaining_expected_demand(sched_c2),
    }
    train_paths = {
        "Case1": [sample_path(sched_c1, 1000 + s) for s in range(20)],
        "Case2": [sample_path(sched_c2, 2000 + s) for s in range(20)],
    }
    train_ho = {
        c: [solve_hindsight_optimum_empty_train(N, M, dict(collections.Counter(x for x in p if x)), prices) for p in ps]
        for c, ps in train_paths.items()
    }
    test_paths = {
        "Case1": [sample_path(sched_c1, 5000 + s) for s in range(30)],
        "Case2": [sample_path(sched_c2, 6000 + s) for s in range(30)],
    }
    test_ho = {
        c: [solve_hindsight_optimum_empty_train(N, M, dict(collections.Counter(x for x in p if x)), prices) for p in ps]
        for c, ps in test_paths.items()
    }
    mp_train = evaluate_suite_timed(myopic_policy, M, N, T, train_paths, train_ho, suffix_by_case, prices)
    mp_test = evaluate_suite_timed(myopic_policy, M, N, T, test_paths, test_ho, suffix_by_case, prices)

    print("==================== 1. 静态排座 S1/S2/S3 模型对比（4轮闭环，非思考模式统一口径） ====================")
    static_flash = run_static_benchmark_for_model("glm-4.7", max_rounds=4)
    static_pro = run_static_benchmark_for_model("glm-5", max_rounds=4)

    print("\n==================== 2. 动态控票从零 20 轮种群进化对比（完全同起跑线，无初始种子） ====================")
    evo_flash = run_evolution_for_model(
        "glm-4.7", 20, 4, M, N, T, prices, suffix_by_case, train_paths, train_ho, test_paths, test_ho, mp_train
    )
    evo_pro = run_evolution_for_model(
        "glm-5", 20, 4, M, N, T, prices, suffix_by_case, train_paths, train_ho, test_paths, test_ho, mp_train
    )

    report = {
        "myopic_test": mp_test,
        "static": {"glm-5.3-flash (req=glm-4.7)": static_flash, "glm-5.3 (req=glm-5)": static_pro},
        "evolution_20rounds_from_scratch": {
            "glm-5.3-flash (req=glm-4.7)": evo_flash,
            "glm-5.3 (req=glm-5)": evo_pro,
        },
    }
    out_path = Path(__file__).parent / "results" / "model_comparison_glm53_vs_flash.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✅ 同系列模型对比完成，结果已保存至: {out_path}")


if __name__ == "__main__":
    main()
