import collections
import math
import random
from typing import Callable, Dict, List, Optional, Tuple


# =============================================================================
# 1. 论文核心数据结构：票价、最大连续空闲区间 (Maximal Sequence) 与状态转移
# =============================================================================

def paper_prices(M: int) -> Dict[Tuple[int, int], int]:
    """论文 Section 5.1 合成数据票价公式: p_ij = floor(10 * (j - i + 1)^(4/5))"""
    prices: Dict[Tuple[int, int], int] = {}
    for i in range(1, M + 1):
        for j in range(i, M + 1):
            prices[(i, j)] = int(math.floor(10.0 * ((j - i + 1) ** 0.8)))
    return prices


def seat_maximal_sequences(row: List[int]) -> List[Tuple[int, int]]:
    """返回单个座位 (1-indexed leg) 的所有最大连续空闲区间 [u, v]。"""
    M = len(row)
    seqs: List[Tuple[int, int]] = []
    l = 0
    while l < M:
        if row[l] == 1:
            r = l
            while r + 1 < M and row[r + 1] == 1:
                r += 1
            seqs.append((l + 1, r + 1))
            l = r + 1
        else:
            l += 1
    return seqs


def matrix_maximal_counts(C: List[List[int]]) -> Dict[Tuple[int, int], int]:
    """对应论文式 (7): f(C)_uv = |M_uv(C)|"""
    counts: Dict[Tuple[int, int], int] = {}
    for row in C:
        for uv in seat_maximal_sequences(row):
            counts[uv] = counts.get(uv, 0) + 1
    return counts


def apply_maximal_transition(
    counts: Dict[Tuple[int, int], int],
    u: int,
    v: int,
    i: int,
    j: int,
) -> Dict[Tuple[int, int], int]:
    """对应论文式 (8): 将请求 i->j 分配到 [u, v]，分裂出 [u, i-1] 和 [j+1, v]。"""
    nxt = dict(counts)
    assert nxt.get((u, v), 0) > 0 and u <= i <= j <= v
    nxt[(u, v)] -= 1
    if nxt[(u, v)] == 0:
        del nxt[(u, v)]
    if u < i:
        nxt[(u, i - 1)] = nxt.get((u, i - 1), 0) + 1
    if j < v:
        nxt[(j + 1, v)] = nxt.get((j + 1, v), 0) + 1
    return nxt


def tie_breaking_key(u: int, v: int) -> Tuple[int, int]:
    """论文 Section 5.1 Tie-Breaking 顺序:
    [i, j] < ... < [i, M] < [i-1, j] < ... < [1, M]
    即 u 越大越优先，u 相同时 v 越小越优先。
    """
    return (-u, v)


def feasible_intervals(
    counts: Dict[Tuple[int, int], int], i: int, j: int
) -> List[Tuple[int, int]]:
    cands = [(u, v) for (u, v), cnt in counts.items() if cnt > 0 and u <= i and j <= v]
    cands.sort(key=lambda uv: tie_breaking_key(uv[0], uv[1]))
    return cands


# =============================================================================
# 2. 静态 Assign-to-Seat 校验器、诊断报告与纯 Python 精确裁判（无外部求解器）
# =============================================================================

def validate_static_solution(
    C: List[List[int]],
    demands: Dict[Tuple[int, int], int],
    prices: Dict[Tuple[int, int], int],
    assignments: List[Dict[str, int]],
) -> Dict[str, object]:
    """严格检查静态分配方案是否满足论文 Eq.(1) 全部约束，并输出诊断信息。"""
    N = len(C)
    M = len(C[0])
    occ = [[0] * M for _ in range(N)]
    used_demands: Dict[Tuple[int, int], int] = collections.defaultdict(int)
    errors: List[str] = []
    total_revenue = 0

    for idx, item in enumerate(assignments):
        try:
            k = int(item["seat"])
            i = int(item["start"])
            j = int(item["end"])
        except (KeyError, TypeError, ValueError):
            errors.append(f"第 {idx+1} 条记录格式错误: {item}")
            continue

        if not (1 <= k <= N):
            errors.append(f"第 {idx+1} 条座位号越界: seat={k} (有效 1..{N})")
            continue
        if not (1 <= i <= j <= M):
            errors.append(f"第 {idx+1} 条区间非法: ({i},{j}) (有效 1<=i<=j<={M})")
            continue

        bad_init = [l for l in range(i, j + 1) if C[k - 1][l - 1] == 0]
        if bad_init:
            errors.append(f"第 {idx+1} 条 seat={k} 分配 ({i},{j}) 与初始已占区间 {bad_init} 冲突")
            continue

        overlap = [l for l in range(i, j + 1) if occ[k - 1][l - 1] == 1]
        if overlap:
            errors.append(f"第 {idx+1} 条 seat={k} 分配 ({i},{j}) 与同座位其他订单在区间 {overlap} 重叠")
            continue

        used_demands[(i, j)] += 1
        if used_demands[(i, j)] > demands.get((i, j), 0):
            errors.append(
                f"第 {idx+1} 条订单 ({i},{j}) 接受数 {used_demands[(i, j)]} 超过需求上限 {demands.get((i, j), 0)}"
            )
            continue

        for l in range(i, j + 1):
            occ[k - 1][l - 1] = 1
        total_revenue += prices[(i, j)]

    # 生成剩余空缺与未满足高价订单诊断，供迭代反馈使用
    remaining_matrix = [
        [1 if (C[k][l] == 1 and occ[k][l] == 0) else 0 for l in range(M)]
        for k in range(N)
    ]
    leftover_seqs = {
        k + 1: seat_maximal_sequences(remaining_matrix[k])
        for k in range(N)
        if any(remaining_matrix[k])
    }
    unmet_demands = []
    for (i, j), d in sorted(demands.items(), key=lambda x: -prices[x[0]]):
        rem = d - used_demands.get((i, j), 0)
        if rem > 0:
            unmet_demands.append(
                {"trip": [i, j], "unmet": rem, "price": prices[(i, j)]}
            )

    return {
        "feasible": len(errors) == 0,
        "errors": errors,
        "revenue": total_revenue if len(errors) == 0 else 0,
        "accepted_count": len(assignments) if len(errors) == 0 else 0,
        "leftover_seat_intervals": leftover_seqs,
        "unmet_demands": unmet_demands,
    }


def solve_static_greedy(
    C: List[List[int]],
    demands: Dict[Tuple[int, int], int],
    prices: Dict[Tuple[int, int], int],
    by_unit_price: bool = False,
) -> Dict[str, object]:
    """纯规则贪心基线（不调求解器）：按总价或单价降序 + 论文 Tie-Breaking 选座。"""
    N = len(C)
    M = len(C[0])
    cur = [row[:] for row in C]
    items: List[Tuple[int, int]] = []
    for (i, j), cnt in demands.items():
        items.extend([(i, j)] * cnt)

    if by_unit_price:
        items.sort(key=lambda ij: (prices[ij] / (ij[1] - ij[0] + 1), prices[ij]), reverse=True)
    else:
        items.sort(key=lambda ij: (prices[ij], -(ij[1] - ij[0] + 1)), reverse=True)

    assignments: List[Dict[str, int]] = []
    for i, j in items:
        best_seat = None
        best_key = None
        for k in range(N):
            for u, v in seat_maximal_sequences(cur[k]):
                if u <= i and j <= v:
                    key = tie_breaking_key(u, v)
                    if best_key is None or key < best_key:
                        best_key = key
                        best_seat = k
        if best_seat is not None:
            for l in range(i - 1, j):
                cur[best_seat][l] = 0
            assignments.append({"seat": best_seat + 1, "start": i, "end": j})

    res = validate_static_solution(C, demands, prices, assignments)
    res["assignments"] = assignments
    return res


def solve_static_exact_bb(
    C: List[List[int]],
    demands: Dict[Tuple[int, int], int],
    prices: Dict[Tuple[int, int], int],
    node_limit: int = 300_000,
) -> Dict[str, object]:
    """纯 Python 分支定界精确求解器（仅用作小/中规模裁判，零外部库依赖）。
    按座位逐行枚举可行非重叠子集，并使用剩余需求上界剪枝。
    """
    N = len(C)
    M = len(C[0])
    demand_types = sorted([ij for ij, d in demands.items() if d > 0])
    idx_map = {ij: idx for idx, ij in enumerate(demand_types)}
    init_rem = tuple(demands[ij] for ij in demand_types)

    # 预先为每个座位生成所有可能的非重叠订单组合（按收益降序）
    seat_patterns: List[List[Tuple[int, Tuple[Tuple[int, int], ...]]]] = []
    for k in range(N):
        # 列出该座位初始可用的所有单个订单类型
        avail_trips = [
            ij for ij in demand_types
            if all(C[k][l - 1] == 1 for l in range(ij[0], ij[1] + 1))
        ]
        avail_trips.sort(key=lambda ij: (ij[0], ij[1]))
        patterns: List[Tuple[int, Tuple[Tuple[int, int], ...]]] = []

        def gen(pos: int, last_end: int, chosen: List[Tuple[int, int]], rev: int) -> None:
            patterns.append((rev, tuple(chosen)))
            for p in range(pos, len(avail_trips)):
                i, j = avail_trips[p]
                if i > last_end:
                    chosen.append((i, j))
                    gen(p + 1, j, chosen, rev + prices[(i, j)])
                    chosen.pop()

        gen(0, 0, [], 0)
        patterns.sort(key=lambda x: -x[0])
        seat_patterns.append(patterns)

    # 后缀座位最大可能收益上界
    suffix_seat_max = [0] * (N + 1)
    for k in range(N - 1, -1, -1):
        suffix_seat_max[k] = suffix_seat_max[k + 1] + (seat_patterns[k][0][0] if seat_patterns[k] else 0)

    best_rev = -1
    best_assign: List[Tuple[int, Tuple[Tuple[int, int], ...]]] = []
    nodes = 0
    exhausted = True

    # 先用贪心初始化一个强下界加速剪枝
    g1 = solve_static_greedy(C, demands, prices, by_unit_price=False)
    g2 = solve_static_greedy(C, demands, prices, by_unit_price=True)
    best_rev = max(int(g1["revenue"]), int(g2["revenue"]))
    best_raw = g1["assignments"] if g1["revenue"] >= g2["revenue"] else g2["assignments"]

    # 按剩余座位模式数从小到大排序以减少分支
    seat_order = sorted(range(N), key=lambda k: len(seat_patterns[k]))
    ordered_patterns = [seat_patterns[k] for k in seat_order]
    suffix_ord = [0] * (N + 1)
    for idx_s in range(N - 1, -1, -1):
        suffix_ord[idx_s] = suffix_ord[idx_s + 1] + ordered_patterns[idx_s][0][0]

    cur_choices: List[Tuple[int, Tuple[Tuple[int, int], ...]]] = []
    rem = list(init_rem)

    def dfs(pos: int, cur_rev: int) -> None:
        nonlocal best_rev, best_assign, nodes, exhausted
        nodes += 1
        if nodes > node_limit:
            exhausted = False
            return
        if pos == N:
            if cur_rev > best_rev:
                best_rev = cur_rev
                best_assign = list(cur_choices)
            return

        # 上界 1: 剩余座位最大收益和
        ub_seats = cur_rev + suffix_ord[pos]
        if ub_seats <= best_rev:
            return
        # 上界 2: 剩余需求总价值
        ub_dem = cur_rev + sum(rem[t] * prices[demand_types[t]] for t in range(len(rem)) if rem[t] > 0)
        if ub_dem <= best_rev:
            return

        k = seat_order[pos]
        for pat_rev, trips in ordered_patterns[pos]:
            if cur_rev + pat_rev + suffix_ord[pos + 1] <= best_rev:
                break  # 已按收益降序排好，后续更小可直接 break
            ok = True
            for ij in trips:
                if rem[idx_map[ij]] <= 0:
                    ok = False
                    break
            if not ok:
                continue
            for ij in trips:
                rem[idx_map[ij]] -= 1
            cur_choices.append((k, trips))
            dfs(pos + 1, cur_rev + pat_rev)
            cur_choices.pop()
            for ij in trips:
                rem[idx_map[ij]] += 1

    dfs(0, 0)

    if best_assign:
        assignments = [
            {"seat": k + 1, "start": i, "end": j}
            for k, trips in best_assign
            for (i, j) in trips
        ]
    else:
        assignments = list(best_raw)

    res = validate_static_solution(C, demands, prices, assignments)
    res["assignments"] = assignments
    res["proven_optimal"] = exhausted
    res["nodes_searched"] = nodes
    return res


# =============================================================================
# 3. 动态问题事后全知上界 HO（基于论文 Theorem 2 的纯 Python 最小费用流，零求解器）
# =============================================================================

def solve_hindsight_optimum_empty_train(
    N: int,
    M: int,
    demands: Dict[Tuple[int, int], int],
    prices: Dict[Tuple[int, int], int],
) -> int:
    """当初始列车全空 (C = 1_{N x M}, strongly NSE) 时，
    由论文 Theorem 2 与 Section 3，离线最优收益 HO 精确等于聚合网络流问题 (3):
      max sum p_ij * x_ij  s.t. 0 <= x_ij <= d_ij, sum_{i<=l<=j} x_ij <= N.
    建模为 (M+1) 个节点的标准最大权流 (min-cost flow with negative costs):
      - 节点 0..M，每个相邻边 (l-1 -> l) 容量 N、费用 0 (表示该区间未售出的空座流)
      - 每个订单类型 (i, j) 建边 (i-1 -> j) 容量 d_ij、费用 -p_ij (表示售出该订单获得收益 p_ij)
      - 从源点 0 送出总流量 N 到汇点 M，最小费用即 -HO_revenue！
    纯 Python SPFA 实现，复杂度极低、100% 精确、无需任何求解器！
    """
    num_nodes = M + 1
    adj: List[List[List[int]]] = [[] for _ in range(num_nodes)]

    def add_edge(u: int, v: int, cap: int, cost: int) -> None:
        fwd = [v, cap, cost, len(adj[v])]
        rev = [u, 0, -cost, len(adj[u])]
        adj[u].append(fwd)
        adj[v].append(rev)

    # 空座直通边
    for l in range(1, M + 1):
        add_edge(l - 1, l, N, 0)

    # 订单收益边
    for (i, j), cnt in demands.items():
        if cnt > 0:
            add_edge(i - 1, j, cnt, -prices[(i, j)])

    flow = 0
    total_cost = 0
    INF = 10**18

    while flow < N:
        dist = [INF] * num_nodes
        in_q = [False] * num_nodes
        parent_v = [-1] * num_nodes
        parent_e = [-1] * num_nodes
        dist[0] = 0
        q = collections.deque([0])
        in_q[0] = True

        while q:
            u = q.popleft()
            in_q[u] = False
            for ei, (v, cap, cost, _) in enumerate(adj[u]):
                if cap > 0 and dist[u] + cost < dist[v]:
                    dist[v] = dist[u] + cost
                    parent_v[v] = u
                    parent_e[v] = ei
                    if not in_q[v]:
                        q.append(v)
                        in_q[v] = True

        if dist[M] == INF:
            break

        push = N - flow
        v = M
        while v != 0:
            u = parent_v[v]
            ei = parent_e[v]
            push = min(push, adj[u][ei][1])
            v = u

        v = M
        while v != 0:
            u = parent_v[v]
            ei = parent_e[v]
            rev_ei = adj[u][ei][3]
            adj[u][ei][1] -= push
            adj[v][rev_ei][1] += push
            v = u

        flow += push
        total_cost += push * dist[M]

    return -total_cost


# =============================================================================
# 4. 论文 Section 5.1 合成数据到达过程与动态仿真器
# =============================================================================

def build_arrival_schedule(M: int, T: int, case: int = 2) -> List[Dict[Tuple[int, int], float]]:
    """构造论文 Section 5.1 的每步到达概率 lambda^t_ij (t = 1..T)。
    case=1: 均匀平稳到达 (lambda_0 = 0.2)
    case=2: 非平稳到达，短途先来、长途后来 (论文最难的 Case 2，lambda_0 = 0.2)
    """
    all_od = [(i, j) for i in range(1, M + 1) for j in range(i, M + 1)]
    num_od = len(all_od)
    schedule: List[Dict[Tuple[int, int], float]] = []

    if case == 1:
        p_each = 0.8 / num_od
        dist = {od: p_each for od in all_od}
        for _ in range(T):
            schedule.append(dist)
        return schedule

    # Case 2: 分 M 个阶段，第 s 阶段长度为 s 的短/中/长途占 0.5，其余占 0.3
    for t in range(1, T + 1):
        s = min(M, int(math.ceil(t * M / T)))
        len_s = [od for od in all_od if (od[1] - od[0] + 1) == s]
        others = [od for od in all_od if (od[1] - od[0] + 1) != s]
        dist: Dict[Tuple[int, int], float] = {}
        for od in len_s:
            dist[od] = 0.5 / len(len_s)
        for od in others:
            dist[od] = 0.3 / len(others)
        schedule.append(dist)
    return schedule


def precompute_remaining_expected_demand(
    schedule: List[Dict[Tuple[int, int], float]]
) -> List[Dict[Tuple[int, int], float]]:
    """预计算从第 t 步到第 T 步 (含 t) 的期望总需求 lambda_{[t, T]}。"""
    T = len(schedule)
    suffix: List[Dict[Tuple[int, int], float]] = [{} for _ in range(T + 1)]
    acc: Dict[Tuple[int, int], float] = collections.defaultdict(float)
    for t in range(T - 1, -1, -1):
        for od, p in schedule[t].items():
            acc[od] += p
        suffix[t] = dict(acc)
    return suffix


def sample_path(
    schedule: List[Dict[Tuple[int, int], float]], seed: int
) -> List[Optional[Tuple[int, int]]]:
    rng = random.Random(seed)
    path: List[Optional[Tuple[int, int]]] = []
    for dist in schedule:
        r = rng.random()
        cum = 0.0
        chosen: Optional[Tuple[int, int]] = None
        for od, p in dist.items():
            cum += p
            if r < cum:
                chosen = od
                break
        path.append(chosen)
    return path


def myopic_policy(
    t: int,
    T: int,
    M: int,
    counts: Dict[Tuple[int, int], int],
    req_i: int,
    req_j: int,
    prices: Dict[Tuple[int, int], int],
    remaining_expected: Dict[Tuple[int, int], float],
) -> Optional[Tuple[int, int]]:
    """论文 Section 5.1 Myopic Policy (MP): 有可行座位就接，按论文 Tie-Breaking 选座。"""
    cands = feasible_intervals(counts, req_i, req_j)
    return cands[0] if cands else None


def simulate_dynamic_policy(
    N: int,
    M: int,
    path: List[Optional[Tuple[int, int]]],
    prices: Dict[Tuple[int, int], int],
    suffix_expected: List[Dict[Tuple[int, int], float]],
    policy_fn: Callable[
        [int, int, int, Dict[Tuple[int, int], int], int, int, Dict[Tuple[int, int], int], Dict[Tuple[int, int], float]],
        Optional[Tuple[int, int]],
    ],
) -> Dict[str, object]:
    """在单条样本路径上仿真动态策略，返回收益与详细诊断统计。"""
    T = len(path)
    counts: Dict[Tuple[int, int], int] = {(1, M): N}
    revenue = 0
    accepted_by_len: Dict[int, int] = collections.defaultdict(int)
    rejected_by_len: Dict[int, int] = collections.defaultdict(int)
    stockout_by_len: Dict[int, int] = collections.defaultdict(int)
    invalid_decisions = 0

    for idx, req in enumerate(path):
        if req is None:
            continue
        i, j = req
        trip_len = j - i + 1
        cands = feasible_intervals(counts, i, j)
        if not cands:
            stockout_by_len[trip_len] += 1
            continue

        # 传入只读拷贝防止策略篡改状态
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

    # 计算剩余空闲座位数（按 leg 统计）
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
