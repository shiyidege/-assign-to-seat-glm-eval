import math

_PLEN = {L: int(10 * (L ** 0.8)) for L in range(1, 20)}

def _omega(u, v, rem):
    """单个空闲块 [u,v] 的未来期望收益（长行程优先贪心填充）。"""
    if u > v:
        return 0.0
    seats = 1.0
    val = 0.0
    for L in range(v - u + 1, 0, -1):
        dem = 0.0
        for a in range(u, v - L + 2):
            r = rem.get((a, a + L - 1))
            if r:
                dem += r
        s = dem if dem < seats else seats
        if s > 0.0:
            val += s * _PLEN[L]
            seats -= s
            if seats <= 1e-9:
                break
    return val

def decide(t, T, M, counts, req_i, req_j, prices, remaining_expected):
    p = prices.get((req_i, req_j), _PLEN[req_j - req_j + 1 if False else req_j - req_i + 1])
    rem = remaining_expected

    # ---- 全局稀缺度：该行程涉及区间的 总未来期望需求 / 总剩余容量 ----
    # v2 失败的根因：_omega 把每个块的"未来"都当成必然卖满，导致机会成本
    # 被系统性高估、无脑拒单、座位大量闲置。修正：只有当未来需求相对
    # 剩余容量真的紧张时，机会成本才接近其上限；否则按稀缺度折减。
    cap = [0] * (M + 2)
    for (u, v), c in counts.items():
        if c > 0:
            for l in range(u, v + 1):
                cap[l] += c
    scarcity = 0.0
    for l in range(req_i, req_j + 1):
        dem_l = 0.0
        for (a, b), r in rem.items():
            if r > 0 and a <= l <= b:
                dem_l += r
        if cap[l] > 0:
            ratio = dem_l / cap[l]
            if ratio > scarcity:
                scarcity = ratio
    if scarcity > 1.0:
        scarcity = 1.0

    best_key = None
    for (u, v), c in counts.items():
        if c <= 0 or u > req_i or v < req_j:
            continue
        loss = _omega(u, v, rem) - _omega(u, req_i - 1, rem) - _omega(req_j + 1, v, rem)
        if loss < 0.0:
            loss = 0.0
        # 端部切割打折（保连续性），机会成本再乘全局稀缺度（修正高估）
        edge = (u == req_i) or (v == req_j)
        key = loss * (0.75 if edge else 1.0) * scarcity
        if best_key is None or key < best_key:
            best_key, best_uv = key, (u, v)

    if best_key is None:
        return None

    # 平衡的护留阈值：早期略保守保护长途，随时间衰减；稀缺度低时几乎等于 Myopic
    frac = (T - t) / T if T > 0 else 0.0
    gamma = 1.0 + 0.35 * frac
    if p >= gamma * best_key:
        return best_uv
    return None
