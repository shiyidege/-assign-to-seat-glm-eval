import math

def _unit_price(a, b):
    return (b - a + 1) ** 0.8  # 与价目 p = int(10*L^0.8) 同构的单位里程价值

def _V(counts, rem):
    """全车确定性流体收益近似：对未来期望需求按单位里程价降序贪心填充 counts。"""
    # 需求按单位里程价降序
    dems = [( _unit_price(a, b), a, b, r) for (a, b), r in rem.items() if r > 1e-9]
    if not dems:
        return 0.0
    dems.sort(key=lambda x: -x[0])
    blocks = [(u, v, float(c)) for (u, v), c in counts.items() if c > 0]
    total = 0.0
    for plen, a, b, r in dems:
        if not blocks:
            break
        # 能覆盖 [a,b] 的块：优先正好贴合/端部，其次剩余量小（碎片先牺牲）
        cand = [(u, v, c) for (u, v, c) in blocks if u <= a and v >= b and c > 1e-9]
        if not cand:
            continue
        cand.sort(key=lambda x: ((x[1] - x[0]) - (b - a), x[2]))
        for u, v, c in cand:
            if r <= 1e-9:
                break
            take = c if c < r else r
            total += take * plen * (b - a + 1)
            r -= take
            # 更新块
            for i, (uu, vv, cc) in enumerate(blocks):
                if uu == u and vv == v:
                    blocks[i] = (u, v, c - take)
                    break
        # 清理空块
        blocks = [x for x in blocks if x[2] > 1e-9]
    return total

def decide(t, T, M, counts, req_i, req_j, prices, remaining_expected):
    p = prices.get((req_i, req_j), int(10 * ((req_j - req_i + 1) ** 0.8)))
    rem = remaining_expected

    # 全车接单前未来期望收益
    V0 = _V(counts, rem)

    # 遍历能容纳请求的最大连续空闲块
    best = None  # (delta, neg_u, v, uv)
    for (u, v), c in counts.items():
        if c <= 0 or u > req_i or v < req_j:
            continue
        # 构造接单后的新 counts（Maximal Sequence 已保证块互不重叠）
        new_counts = dict(counts)
        new_counts[(u, v)] = c - 1
        if new_counts[(u, v)] == 0:
            del new_counts[(u, v)]
        if u < req_i:
            new_counts[(u, req_i - 1)] = new_counts.get((u, req_i - 1), 0) + 1
        if req_j < v:
            new_counts[(req_j + 1, v)] = new_counts.get((req_j + 1, v), 0) + 1
        V1 = _V(new_counts, rem)
        delta = V0 - V1  # 机会成本
        key = (delta, -u, v)
        if best is None or key < best[0]:
            best = (key, (u, v), delta)

    if best is None:
        return None

    (delta, _, _), (u, v), delta = best if False else (best[0], best[1], best[0][0])

    # BPC-M 准则：p + V_after > V_before 即 p > 机会成本 则接单
    if p > delta or p + 1e-9 >= delta:
        return (u, v)
    return None
