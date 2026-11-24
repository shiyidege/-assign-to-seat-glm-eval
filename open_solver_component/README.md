# 开源求解器可选组件实验

> 对应论文：*Assign-to-Seat: Dynamic Capacity Control for Selling High-Speed Train Tickets*  
> 上级仓库：纯 AI 无求解器进化实验（`../`，冠军策略 `E097`）  
> 本目录目标：给 AI **增加一个可选组件** `solver_toolkit`（SCIP / CBC / OR-Tools GLOP·CLP / HiGHS），**可以调用也可以不调用**，并量化「调用后是否比纯 AI 更好」。

---

## 一、核心结论

1. **百分比怎么算？**  
   对每条随机到达路径：
   \[
   \text{占比} = \frac{\text{策略实际收益}}{\text{HO（事后全知最优）}} \times 100\%
   \]
   Case1 / Case2 各 30 条路径取平均；表格中的「均分」再对两个 Case 取平均。`100%` = 追平上帝视角最优。

2. **调用开源求解器组件，整体优于纯 AI。**  
   最强组合：**BPC-M + OR-Tools GLOP = 95.43%**，比纯 AI `E097`（**94.22%**）高约 **+1.21%**。

3. **方法强度排序（同留出集）：**  
   **BPC-M ≳ RDP > BPC-S ≈ /略强于 纯AI E097 > Myopic**

4. **组件是可选的**：Prompt / AST 审计允许 `import solver_toolkit`，也允许完全不调用、继续写纯 Python 启发式。

---

## 二、留出集全量排名（M=6, N=20, T=100，30+30 路径）

![留出集均分排名](figures/ranking_vs_pure_ai.png)

| 排名 | 方法 | Case1 | Case2 | 均分 |
|---:|---|---:|---:|---:|
| 1 | **BPC-M via GLOP** | 95.82% | 95.04% | **95.43%** |
| 2 | BPC-M via CLP | 95.82% | 95.01% | 95.41% |
| 3 | BPC-M via HiGHS | 95.63% | 95.04% | 95.34% |
| 4 | BPC-M via SCIP | 95.65% | 95.01% | 95.33% |
| 5 | BPC-M via CBC | 95.63% | 94.92% | 95.28% |
| 6 | RDP via GLOP | 95.48% | 94.97% | 95.22% |
| 7 | RDP via CBC | 95.31% | 94.92% | 95.12% |
| 8 | RDP via HiGHS | 95.06% | 94.95% | 95.00% |
| 9 | RDP via SCIP | 94.58% | 95.01% | 94.80% |
| 10 | RDP via CLP | 94.92% | 94.55% | 94.73% |
| 11 | BPC-S via HiGHS | 95.42% | 93.31% | 94.37% |
| 12 | **GLM-5 E097（纯 AI，无求解器）** | 94.88% | 93.57% | **94.22%** |
| 13 | BPC-S via SCIP | 95.40% | 92.86% | 94.13% |
| 14 | BPC-S via CLP | 95.54% | 92.43% | 93.99% |
| 15 | BPC-S via CBC | 95.11% | 92.58% | 93.84% |
| 16 | BPC-S via GLOP | 95.23% | 91.56% | 93.40% |
| 17 | MP（Myopic 贪心） | 90.54% | 85.92% | 88.23% |

原始数值：[`results/all_methods_via_toolkit.json`](results/all_methods_via_toolkit.json)

---

## 三、组件设计（给 AI 用的接口）

```python
from solver_toolkit import available_solvers, solve_lp, preferred_lp_solver

print(available_solvers())
# {'scip': True, 'cbc': True, 'glop': True, 'clp': True, 'highs': True, ...}

res = solve_lp(
    c, A_ub=A, b_ub=b,
    solver="auto",          # 或 "scip" / "cbc" / "glop" / "clp" / "highs"
    time_limit_s=0.5,
)
if res["ok"]:
    x = res["x"]            # 最优解向量
```

本机探测结果：SCIP / CBC / GLOP / CLP / SciPy HiGHS **全部可用**。

---

## 四、代码清单

| 文件 | 说明 |
|---|---|
| `solver_toolkit.py` | 可选开源求解器组件（统一 LP 接口） |
| `seed_bpcm_via_toolkit.py` | 示范：decide 内调用组件复现论文 BPC-M |
| `compare_all_via_toolkit.py` | 论文 MP / BPC-S / BPC-M / RDP × 全部后端，对比纯 AI |
| `evolve_with_solver_option.py` | 短跑进化：Prompt 告知 AI「可调用可不调用」 |
| `results/*.json` | 全部原始结果 |

依赖上级目录模块：`problem_core.py`、`best_pop100_policy.py`、`glm_client.py`（脚本启动时会自动把上级加入 `sys.path`）。

### 复现命令

```bash
# 在本目录执行
pip install --user ortools pulp scipy

# 1) 组件自检
python3 solver_toolkit.py

# 2) 论文全方法 × 开源求解器全量对照（零 API 成本）
python3 compare_all_via_toolkit.py

# 3) 可选：短跑「AI 可选用组件」进化（需要 GLM_API_KEY）
export GLM_API_KEY="你的智谱Coding_Plan_Key"
python3 evolve_with_solver_option.py --rounds 4
```

---

## 五、实践建议

1. **要精度**：优先 **BPC-M + GLOP/HiGHS**（开源即可，不必上商业求解器）。  
2. **要速度 / 线上零求解器**：继续用上级实验的纯 AI 冠军 `E097`（~94.2%，毫秒级）。  
3. **AI 编程范式**：把 `solver_toolkit` 当可选工具告诉模型；它既可写纯启发式，也可在 decide 里解小 LP——本实验验证后一种路径确实能再抬 1 个点左右。
