#!/usr/bin/env python3
"""
可选开源求解器组件（给 AI 策略代码调用）。

设计目标：
- AI 写 decide(...) 时【可以】调用本组件，也【可以】完全不调用（纯启发式）。
- 统一封装本机已验证可用的开源后端：OR-Tools SCIP / CBC / GLOP / CLP，以及 SciPy HiGHS。
- 禁止直接暴露 gurobipy / coptpy 等商业求解器。

推荐用法（策略代码内）：
    from solver_toolkit import available_solvers, solve_lp

    info = available_solvers()          # {'scip': True, 'cbc': True, ...}
    res = solve_lp(c, A_ub=A, b_ub=b, solver="scip")  # 或 "auto"/"cbc"/"glop"/"highs"
    if res["ok"]:
        x = res["x"]
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

# ---------------------------------------------------------------------------
# Backend detection
# ---------------------------------------------------------------------------

_BACKENDS: Dict[str, bool] = {}


def _probe() -> Dict[str, bool]:
    global _BACKENDS
    if _BACKENDS:
        return _BACKENDS
    out = {
        "scip": False,
        "cbc": False,
        "glop": False,
        "clp": False,
        "highs": False,
        "ortools": False,
        "scipy_highs": False,
    }
    try:
        from ortools.linear_solver import pywraplp  # noqa: F401

        out["ortools"] = True
        for name, key in [("SCIP", "scip"), ("CBC", "cbc"), ("GLOP", "glop"), ("CLP", "clp")]:
            try:
                s = pywraplp.Solver.CreateSolver(name)
                out[key] = s is not None
            except Exception:
                out[key] = False
    except Exception:
        pass
    try:
        from scipy.optimize import linprog  # noqa: F401

        out["scipy_highs"] = True
        out["highs"] = True
    except Exception:
        pass
    _BACKENDS = out
    return out


def available_solvers() -> Dict[str, bool]:
    """返回各开源求解器是否可用。"""
    return dict(_probe())


def preferred_lp_solver() -> str:
    """自动挑选一个可用的 LP 求解器名称。"""
    a = _probe()
    for name in ("scip", "glop", "clp", "cbc", "highs"):
        if a.get(name):
            return name
    raise RuntimeError("没有可用的开源 LP 求解器（需要 ortools 或 scipy）")


# ---------------------------------------------------------------------------
# Unified LP interface
# ---------------------------------------------------------------------------

def solve_lp(
    c: Sequence[float],
    A_ub: Optional[Any] = None,
    b_ub: Optional[Sequence[float]] = None,
    A_eq: Optional[Any] = None,
    b_eq: Optional[Sequence[float]] = None,
    bounds: Optional[Sequence[Tuple[Optional[float], Optional[float]]]] = None,
    solver: str = "auto",
    time_limit_s: float = 1.0,
) -> Dict[str, Any]:
    """
    解标准形式 LP：
        minimize  c · x
        s.t.      A_ub x <= b_ub
                  A_eq x == b_eq
                  bounds_i[0] <= x_i <= bounds_i[1]

    Parameters
    ----------
    solver : "auto" | "scip" | "cbc" | "glop" | "clp" | "highs"
    time_limit_s : 单次求解时间上限（秒）

    Returns
    -------
    dict with keys:
      ok: bool
      x: list[float] | None
      obj: float | None
      status: str
      solver: str  (实际使用的后端)
      message: str
    """
    c_arr = np.asarray(c, dtype=float).ravel()
    n = int(c_arr.size)
    if bounds is None:
        bounds_list: List[Tuple[Optional[float], Optional[float]]] = [(0.0, None)] * n
    else:
        bounds_list = [(None if lo is None else float(lo), None if hi is None else float(hi)) for lo, hi in bounds]
        if len(bounds_list) != n:
            raise ValueError(f"bounds 长度 {len(bounds_list)} != 变量数 {n}")

    name = preferred_lp_solver() if solver == "auto" else solver.lower().strip()
    avail = _probe()
    if name in ("scip", "cbc", "glop", "clp"):
        if not avail.get(name):
            return {"ok": False, "x": None, "obj": None, "status": "unavailable", "solver": name, "message": f"{name} 不可用"}
        return _solve_lp_ortools(c_arr, A_ub, b_ub, A_eq, b_eq, bounds_list, name, time_limit_s)
    if name in ("highs", "scipy", "scipy_highs"):
        if not avail.get("highs"):
            return {"ok": False, "x": None, "obj": None, "status": "unavailable", "solver": "highs", "message": "SciPy HiGHS 不可用"}
        return _solve_lp_scipy(c_arr, A_ub, b_ub, A_eq, b_eq, bounds_list)
    return {"ok": False, "x": None, "obj": None, "status": "unknown_solver", "solver": name, "message": f"未知求解器: {name}"}


def _as_dense(mat: Any, n_rows_hint: Optional[int], n_cols: int) -> np.ndarray:
    if mat is None:
        return np.zeros((0, n_cols), dtype=float)
    if hasattr(mat, "toarray"):
        return np.asarray(mat.toarray(), dtype=float)
    arr = np.asarray(mat, dtype=float)
    if arr.ndim == 1:
        arr = arr.reshape(1, -1)
    if arr.shape[1] != n_cols:
        raise ValueError(f"矩阵列数 {arr.shape[1]} != 变量数 {n_cols}")
    if n_rows_hint is not None and arr.shape[0] != n_rows_hint:
        # allow mismatch only if b length will validate separately
        pass
    return arr


def _solve_lp_ortools(
    c: np.ndarray,
    A_ub: Any,
    b_ub: Optional[Sequence[float]],
    A_eq: Any,
    b_eq: Optional[Sequence[float]],
    bounds: List[Tuple[Optional[float], Optional[float]]],
    solver_name: str,
    time_limit_s: float,
) -> Dict[str, Any]:
    from ortools.linear_solver import pywraplp

    key = {"scip": "SCIP", "cbc": "CBC", "glop": "GLOP", "clp": "CLP"}[solver_name]
    solver = pywraplp.Solver.CreateSolver(key)
    if solver is None:
        return {"ok": False, "x": None, "obj": None, "status": "create_failed", "solver": solver_name, "message": f"CreateSolver({key}) failed"}

    solver.SetTimeLimit(int(max(time_limit_s, 0.01) * 1000))
    n = c.size
    xs = []
    for i in range(n):
        lo, hi = bounds[i]
        lb = -solver.infinity() if lo is None else float(lo)
        ub = solver.infinity() if hi is None else float(hi)
        xs.append(solver.NumVar(lb, ub, f"x{i}"))

    objective = solver.Objective()
    for i, coef in enumerate(c):
        if coef != 0.0:
            objective.SetCoefficient(xs[i], float(coef))
    objective.SetMinimization()

    if A_ub is not None and b_ub is not None:
        A = _as_dense(A_ub, len(b_ub), n)
        for r, rhs in enumerate(b_ub):
            ct = solver.Constraint(-solver.infinity(), float(rhs))
            row = A[r]
            for j, a in enumerate(row):
                if a != 0.0:
                    ct.SetCoefficient(xs[j], float(a))

    if A_eq is not None and b_eq is not None:
        A = _as_dense(A_eq, len(b_eq), n)
        for r, rhs in enumerate(b_eq):
            ct = solver.Constraint(float(rhs), float(rhs))
            row = A[r]
            for j, a in enumerate(row):
                if a != 0.0:
                    ct.SetCoefficient(xs[j], float(a))

    status = solver.Solve()
    ok = status == pywraplp.Solver.OPTIMAL or status == pywraplp.Solver.FEASIBLE
    status_map = {
        pywraplp.Solver.OPTIMAL: "optimal",
        pywraplp.Solver.FEASIBLE: "feasible",
        pywraplp.Solver.INFEASIBLE: "infeasible",
        pywraplp.Solver.UNBOUNDED: "unbounded",
        pywraplp.Solver.ABNORMAL: "abnormal",
        pywraplp.Solver.NOT_SOLVED: "not_solved",
    }
    if not ok:
        return {
            "ok": False,
            "x": None,
            "obj": None,
            "status": status_map.get(status, str(status)),
            "solver": solver_name,
            "message": f"OR-Tools {key} status={status}",
        }
    x = [xs[i].solution_value() for i in range(n)]
    return {
        "ok": True,
        "x": x,
        "obj": float(objective.Value()),
        "status": status_map.get(status, str(status)),
        "solver": solver_name,
        "message": "ok",
    }


def _solve_lp_scipy(
    c: np.ndarray,
    A_ub: Any,
    b_ub: Optional[Sequence[float]],
    A_eq: Any,
    b_eq: Optional[Sequence[float]],
    bounds: List[Tuple[Optional[float], Optional[float]]],
) -> Dict[str, Any]:
    from scipy.optimize import linprog

    res = linprog(
        c,
        A_ub=A_ub,
        b_ub=None if b_ub is None else np.asarray(b_ub, dtype=float),
        A_eq=A_eq,
        b_eq=None if b_eq is None else np.asarray(b_eq, dtype=float),
        bounds=bounds,
        method="highs",
    )
    if not res.success:
        return {
            "ok": False,
            "x": None,
            "obj": None,
            "status": "failed",
            "solver": "highs",
            "message": str(res.message),
        }
    return {
        "ok": True,
        "x": [float(v) for v in res.x],
        "obj": float(res.fun),
        "status": "optimal",
        "solver": "highs",
        "message": "ok",
    }


# ---------------------------------------------------------------------------
# Optional convenience: tiny demo LP (for smoke tests)
# ---------------------------------------------------------------------------

def smoke_test() -> Dict[str, Any]:
    """解一个极小 LP，验证各后端。"""
    # min -x-y  s.t. x+y <= 1, x,y>=0  => opt -1 at e.g. (1,0)
    c = [-1.0, -1.0]
    A_ub = [[1.0, 1.0]]
    b_ub = [1.0]
    out = {"available": available_solvers(), "runs": {}}
    for name in ("scip", "cbc", "glop", "clp", "highs"):
        if not out["available"].get(name):
            continue
        out["runs"][name] = solve_lp(c, A_ub=A_ub, b_ub=b_ub, solver=name, time_limit_s=0.5)
    return out


if __name__ == "__main__":
    import json

    print(json.dumps(smoke_test(), ensure_ascii=False, indent=2))
