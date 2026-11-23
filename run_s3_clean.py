import json
from pathlib import Path

from glm_client import call_glm, extract_json_block
from loop1_static_reflexion import build_static_instances, format_problem_prompt
from problem_core import solve_static_exact_bb, solve_static_greedy, validate_static_solution


def main():
    inst = build_static_instances()[2]
    C, demands, prices = inst["C"], inst["demands"], inst["prices"]
    exact = solve_static_exact_bb(C, demands, prices)
    g_tot = solve_static_greedy(C, demands, prices, False)
    g_unit = solve_static_greedy(C, demands, prices, True)

    print(
        f"S3 补测 | 精确最优={exact['revenue']} | 贪心(总价)={g_tot['revenue']} | 贪心(单价)={g_unit['revenue']}"
    )

    messages = [
        {
            "role": "system",
            "content": "你是精通组合优化的专家。不用外部求解器，每次只输出严格合法 JSON。",
        },
        {"role": "user", "content": format_problem_prompt(inst)},
    ]
    rounds = []
    best_rev = 0
    for r in range(1, 5):
        resp = call_glm(
            messages, model="glm-5", temperature=0.0, max_tokens=4096, thinking=False
        )
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
        ratio = round(val["revenue"] / exact["revenue"] * 100, 2)
        print(
            f"  S3 [Round {r}] feasible={val['feasible']} | rev={val['revenue']}/{exact['revenue']} ({ratio}%) "
            f"| errs={len(val['errors'])} | elapsed={resp['elapsed_s']}s"
        )
        rounds.append(
            {
                "round": r,
                "feasible": val["feasible"],
                "revenue": val["revenue"],
                "opt_ratio_pct": ratio,
                "errors": val["errors"][:5],
                "elapsed_s": resp["elapsed_s"],
                "usage": resp["usage"],
            }
        )
        if r == 4:
            break
        if not val["feasible"]:
            fb = (
                "【校验失败】冲突如下：\n"
                + "\n".join("- " + x for x in val["errors"][:8])
                + "\n请逐座核对每个座位的可用区间，彻底修复所有冲突并尽量提高总收益，输出严格 JSON。"
            )
        else:
            leftover_s = json.dumps(val["leftover_seat_intervals"], ensure_ascii=False)
            unmet_s = json.dumps(val["unmet_demands"][:8], ensure_ascii=False)
            fb = (
                f"【校验通过】当前合法收益={val['revenue']}（共接 {val['accepted_count']} 单）。\n"
                f"剩余空座={leftover_s}\n未满足高价单={unmet_s}\n"
                "请尝试跨座重排或换组合进一步提分，输出严格 JSON。"
            )
        messages.append({"role": "user", "content": fb})

    out_path = Path(__file__).parent / "results" / "exp1_s3_clean.json"
    out_path.write_text(
        json.dumps(
            {
                "exact_optimum": exact["revenue"],
                "greedy_by_total_price": g_tot["revenue"],
                "greedy_by_unit_price": g_unit["revenue"],
                "glm_best_revenue": best_rev,
                "glm_best_opt_ratio_pct": round(best_rev / exact["revenue"] * 100, 2),
                "rounds": rounds,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"✅ S3 补测完成，最佳={best_rev}/{exact['revenue']}，已保存至 {out_path}")


if __name__ == "__main__":
    main()
