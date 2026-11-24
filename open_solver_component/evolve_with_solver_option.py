#!/usr/bin/env python3
"""本目录脚本：自动把上级实验仓库加入 sys.path，以便复用 problem_core / glm_client / E097。"""
import sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

"""
实验：给 AI 一个【可选】开源求解器组件（SCIP / CBC / OR-Tools GLOP/CLP / HiGHS），
看它是否会调用，以及最终效果是否强于纯 AI 无求解器冠军 E097。

要点：
- 不是强制用求解器硬算；Prompt 明确写「可以调用，也可以不调用」。
- AST 审计只允许标准库 + `solver_toolkit`（禁止直接 import gurobipy/coptpy/ortools/...）。
- 先跑组件可用性 + 种子 BPC-M(via toolkit) vs E097；再短跑若干轮可选组件进化。
"""

from __future__ import annotations

import argparse
import ast
import collections
import json
import math
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from glm_client import call_glm, extract_python_block
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
from solver_toolkit import available_solvers, preferred_lp_solver, smoke_test

from best_pop100_policy import decide as e097_decide
from seed_bpcm_via_toolkit import decide as seed_bpcm_decide


ALLOWED_IMPORT_ROOTS = {
    "math",
    "collections",
    "heapq",
    "itertools",
    "functools",
    "typing",
    "solver_toolkit",
}

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
    "numpy",
    "os",
    "sys",
    "subprocess",
    "socket",
    "urllib",
    "requests",
    "pathlib",
    "shutil",
}


def audit_and_load_policy_optional_solver(code: str) -> Tuple[Callable, bool]:
    """允许标准库 + solver_toolkit；返回 (decide_fn, used_toolkit)."""
    tree = ast.parse(code)
    used_toolkit = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in FORBIDDEN_IMPORTS:
                    raise ValueError(f"禁止直接导入: {alias.name}（请改用 solver_toolkit）")
                if root == "solver_toolkit":
                    used_toolkit = True
                elif root not in ALLOWED_IMPORT_ROOTS and root not in {"__future__"}:
                    # 宽松：未知第三方仍禁止
                    raise ValueError(f"禁止导入未授权模块: {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                root = node.module.split(".")[0]
                if root in FORBIDDEN_IMPORTS:
                    raise ValueError(f"禁止直接导入: {node.module}（请改用 solver_toolkit）")
                if root == "solver_toolkit":
                    used_toolkit = True
                elif root not in ALLOWED_IMPORT_ROOTS and root not in {"__future__"}:
                    raise ValueError(f"禁止导入未授权模块: {node.module}")

    # 额外：正文里出现 solver_toolkit. / from solver_toolkit 也算
    if "solver_toolkit" in code:
        used_toolkit = True

    ns: Dict[str, Any] = {"math": math, "collections": collections}
    # 预注入，避免 exec 时找不到（与 import 并存也安全）
    import solver_toolkit as _st

    ns["solver_toolkit"] = _st
    exec(compile(tree, "<glm_optional_solver_policy>", "exec"), ns)
    if "decide" not in ns or not callable(ns["decide"]):
        raise ValueError("未找到 decide(...)")
    return ns["decide"], used_toolkit


def run_sim(N, M, path, prices, suffix, policy_fn, deadline=None):
    counts = {(1, M): N}
    rev = 0
    for idx, req in enumerate(path):
        if deadline is not None and time.perf_counter() > deadline:
            raise TimeoutError("timeout")
        if req is None:
            continue
        i, j = req
        cands = feasible_intervals(counts, i, j)
        if not cands:
            continue
        dec = policy_fn(idx + 1, len(path), M, dict(counts), i, j, prices, suffix[idx])
        if dec is not None and (int(dec[0]), int(dec[1])) in cands:
            counts = apply_maximal_transition(counts, int(dec[0]), int(dec[1]), i, j)
            rev += prices[(i, j)]
    return rev


def eval_on_paths(N, M, paths, hos, prices, suffix, policy_fn, label=""):
    t0 = time.perf_counter()
    revs = []
    for p in paths:
        revs.append(run_sim(N, M, p, prices, suffix, policy_fn))
    dt = (time.perf_counter() - t0) * 1000
    ratio = sum(r / h for r, h in zip(revs, hos)) / len(paths) * 100
    return {
        "label": label,
        "avg_rev": round(sum(revs) / len(paths), 2),
        "ratio_pct": round(ratio, 2),
        "gap_pct": round(100 - ratio, 2),
        "elapsed_ms": round(dt, 1),
    }


def build_system_prompt(avail: Dict[str, bool]) -> str:
    avail_str = ", ".join(f"{k}={'✓' if v else '✗'}" for k, v in avail.items() if k in ("scip", "cbc", "glop", "clp", "highs"))
    return (
        "你是运筹学与算法专家，正在为高铁 Assign-to-Seat 动态控票设计在线策略 decide(...)。\n"
        "【重要】本环境提供了一个【可选】开源求解器组件 `solver_toolkit`：\n"
        f"  当前可用后端：{avail_str}\n"
        "  你可以调用它，也可以完全不调用（纯 Python 启发式同样允许）。\n"
        "  推荐接口：\n"
        "    from solver_toolkit import available_solvers, solve_lp, preferred_lp_solver\n"
        "    res = solve_lp(c, A_ub=A, b_ub=b, solver='scip')  # 或 'cbc'/'glop'/'highs'/'auto'\n"
        "    # res['ok'], res['x'], res['obj']\n"
        "硬规则：\n"
        "1. 只能用 Python 标准库 + solver_toolkit；禁止直接 import ortools/pulp/scipy/gurobipy/coptpy。\n"
        "2. 必须定义：def decide(t, T, M, counts, req_i, req_j, prices, remaining_expected)\n"
        "3. 返回 None（拒单）或合法 (u,v)（counts[(u,v)]>0 且 u<=req_i<=req_j<=v）。\n"
        "4. 若调用求解器：请控制单次 decide 耗时（建议 time_limit_s<=0.5，且可缓存矩阵）。\n"
        "5. 只输出一个 ```python``` 代码块。\n"
        "设计建议：\n"
        "- 若你认为 BPC-M / RDP 类影子价格 LP 有价值，可用 solver_toolkit.solve_lp 解小 LP；\n"
        "- 若你认为毫秒级启发式更划算，可不调用求解器，写纯 Python 估值/流体/护留规则。\n"
    )


def build_user_prompt(round_i: int, best_brief: str, prefer_solver_hint: bool) -> str:
    hint = (
        "本次请【优先尝试】调用 solver_toolkit（例如用 SCIP/GLOP 解 BPC-M 风格对偶 LP，或轻量流体 LP），"
        "并处理好失败回退。"
        if prefer_solver_hint
        else
        "本次请【自行决定】是否调用 solver_toolkit：如果纯启发式更稳更快也可以完全不调用。"
    )
    return (
        f"第 {round_i} 轮进化。测试规格：M=6, N=20, T=100，票价 L=1..6=[10,17,24,30,36,41]。\n"
        f"当前最佳参考：\n{best_brief}\n\n"
        f"{hint}\n"
        "目标：在 Case1（平稳）与 Case2（短途先来）留出集上提高占 HO 比例。\n"
        "请输出完整可运行代码。"
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rounds", type=int, default=8, help="GLM 进化轮数（可选组件）")
    parser.add_argument("--model", type=str, default="glm-5")
    parser.add_argument("--skip-evolve", action="store_true", help="只跑组件探测+种子对比，不调 GLM")
    args = parser.parse_args()

    out_dir = Path(__file__).parent / "results"
    out_dir.mkdir(exist_ok=True)

    print("=== Step0: 开源求解器组件可用性 ===")
    smoke = smoke_test()
    print(json.dumps(smoke, ensure_ascii=False, indent=2))
    avail = available_solvers()
    auto = preferred_lp_solver()
    print(f"preferred_lp_solver = {auto}")

    M, N, T = 6, 20, 100
    prices = paper_prices(M)

    # 与第一阶段相同的留出集种子，保证可比
    paths = {}
    hos = {}
    suf = {}
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

    report: Dict[str, Any] = {
        "solver_smoke": smoke,
        "preferred_lp_solver": auto,
        "heldout": {},
        "evolution": [],
    }

    print("\n=== Step1: 固定策略对比（组件种子 BPC-M vs 纯AI E097 vs Myopic）===")
    baselines = [
        ("MP (Myopic)", myopic_policy),
        ("GLM-5 E097 (纯AI无求解器)", e097_decide),
        (f"BPC-M via toolkit({auto})", seed_bpcm_decide),
    ]
    # 再测几个后端（若可用）
    for backend in ("scip", "glop", "cbc"):
        if avail.get(backend):
            baselines.append(
                (
                    f"BPC-M via toolkit({backend})",
                    lambda t, T_, M_, counts, i, j, prices_, rem, b=backend: seed_bpcm_decide(
                        t, T_, M_, counts, i, j, prices_, rem, solver=b
                    ),
                )
            )

    for bname, fn in baselines:
        row = {}
        print(f"\n-- {bname} --")
        scores = []
        for cname in ("Case1", "Case2"):
            r = eval_on_paths(N, M, paths[cname], hos[cname], prices, suf[cname], fn, cname)
            row[cname] = r
            scores.append(r["ratio_pct"])
            print(f"  {cname}: {r['ratio_pct']:.2f}% | {r['elapsed_ms']:.1f} ms")
        row["mean"] = round(sum(scores) / 2, 2)
        report["heldout"][bname] = row
        print(f"  mean={row['mean']:.2f}%")

    if args.skip_evolve:
        out = out_dir / "optional_solver_component.json"
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n✅ 已保存 {out}")
        return

    print("\n=== Step2: 短跑进化（AI 可选调用求解器组件）===")
    sys_prompt = build_system_prompt(avail)
    best_code = Path(__file__).parent.joinpath("seed_bpcm_via_toolkit.py").read_text(encoding="utf-8")
    # 进化用的种子代码需要是 decide-only 风格；给一个精简模板说明
    best_brief = (
        f"种子=BPC-M via toolkit({auto}) | heldout mean="
        f"{report['heldout'][f'BPC-M via toolkit({auto})']['mean']}% ; "
        f"E097 mean={report['heldout']['GLM-5 E097 (纯AI无求解器)']['mean']}%"
    )
    best_score = report["heldout"][f"BPC-M via toolkit({auto})"]["mean"]
    best_used_solver = True

    for r_i in range(1, args.rounds + 1):
        prefer = r_i % 2 == 1  # 奇数轮鼓励用求解器，偶数轮自由选择
        user_prompt = build_user_prompt(r_i, best_brief, prefer_solver_hint=prefer)
        # 附上当前最佳代码摘要（截断）
        user_prompt += "\n\n当前最佳代码参考（可改写）：\n```python\n" + best_code[:3500] + "\n```\n"

        entry = {"round": r_i, "prefer_solver_hint": prefer}
        try:
            res = call_glm(
                [
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                model=args.model,
                temperature=0.5,
                max_tokens=4096,
                thinking=False,
                timeout=180,
                retries=3,
            )
            code = extract_python_block(res["content"])
            fn, used = audit_and_load_policy_optional_solver(code)
            entry.update(
                {
                    "status": "ok",
                    "used_toolkit": used,
                    "tokens": res.get("usage", {}),
                    "api_s": res.get("elapsed_s"),
                    "model_returned": res.get("model_returned"),
                }
            )
            # 评测：训练集小一点加速（每侧 10 条），再在完整 30+30 留出上确认若更优
            train_scores = []
            for cname, seed0 in (("Case1", 1000), ("Case2", 2000)):
                sched = build_arrival_schedule(M, T, case=1 if cname == "Case1" else 2)
                suf_tr = precompute_remaining_expected_demand(sched)
                ps = [sample_path(sched, seed0 + s) for s in range(10)]
                hs = [
                    solve_hindsight_optimum_empty_train(
                        N, M, dict(collections.Counter(x for x in p if x is not None)), prices
                    )
                    for p in ps
                ]
                er = eval_on_paths(N, M, ps, hs, prices, suf_tr, fn, cname)
                train_scores.append(er["ratio_pct"])
            train_mean = round(sum(train_scores) / 2, 2)
            entry["train_mean"] = train_mean

            # heldout
            held = {}
            for cname in ("Case1", "Case2"):
                held[cname] = eval_on_paths(N, M, paths[cname], hos[cname], prices, suf[cname], fn, cname)
            held_mean = round((held["Case1"]["ratio_pct"] + held["Case2"]["ratio_pct"]) / 2, 2)
            entry["heldout"] = held
            entry["heldout_mean"] = held_mean
            entry["code"] = code

            print(
                f"R{r_i:02d}: train={train_mean:.2f}% held={held_mean:.2f}% "
                f"used_toolkit={used} api={entry.get('api_s')}s"
            )

            if held_mean > best_score + 1e-9:
                best_score = held_mean
                best_code = code
                best_used_solver = used
                best_brief = f"Round{r_i} held={held_mean}% used_toolkit={used}"
                print(f"  ★ 新最佳 {best_score}%")
        except Exception as e:
            entry["status"] = "error"
            entry["error"] = str(e)[:400]
            print(f"R{r_i:02d}: ERROR {entry['error']}")

        report["evolution"].append({k: v for k, v in entry.items() if k != "code" or entry.get("status") == "ok"})
        # 仅保留最后一轮完整代码到单独字段
        if entry.get("status") == "ok":
            report["last_ok_code"] = entry.get("code")

    report["best_heldout_mean"] = best_score
    report["best_used_toolkit"] = best_used_solver
    report["best_code"] = best_code

    out = out_dir / "optional_solver_component.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    best_path = Path(__file__).parent / "best_optional_solver_policy.py"
    best_path.write_text(best_code if "def decide" in best_code else report.get("last_ok_code", best_code), encoding="utf-8")
    print(f"\n✅ 完成。最佳 heldout mean={best_score}% | used_toolkit={best_used_solver}")
    print(f"结果: {out}")
    print(f"最佳代码: {best_path}")


if __name__ == "__main__":
    main()
