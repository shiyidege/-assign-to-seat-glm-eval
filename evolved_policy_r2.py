import math

# 预算票价表（次加性 p_ij = floor(10 * L^0.8)）
_PLEN = {L: int(10 * (L ** 0.8)) for L in range(1, 20)}

def _omega(u, v, rem):
    """单个空闲块 [u,v] 的未来期望收益近似（无缓存版，快且准）：
    长行程优先贪心填充（长行程单位里程价更高、且最能利用连续性）。
    对每个长度 L 从长到短，把块内所有长度 L 的未来期望需求截断到剩余容量上。"""
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
    p = prices.get((req_i, req_j), _PLEN[req_j - req_i + 1])
    rem = remaining_expected

    best_loss = None
    best_key = None
    best_edge = False
    for (u, v), c in counts.items():
        if c <= 0 or u > req_i or v < req_j:
            continue
        # 机会成本 = 块的未来期望收益 - 接单后左右碎片的期望收益
        loss = _omega(u, v, rem) - _omega(u, req_i - 1, rem) - _omega(req_j + 1, v, rem)
        # Assign-to-Seat 关键：强烈偏好从块的端部切割（u==req_i 或 v==req_j），
        # 端部切割只产生一个碎片，不破坏连续性；中部切割产生两个碎片。
        edge = (u == req_i) or (v == req_j)
        # 排序键：先按机会成本（端部切割给显著折扣），再偏好端部
        key = loss * (0.75 if edge else 1.0)
        if best_key is None or key < best_key - 1e-9 or (abs(key - best_key) <= 1e-9 and edge and not best_edge):
            best_key, best_loss, best_edge, best_uv = key, loss, edge, (u, v)

    if best_key is None:
        return None  # 没有任何连续区间能覆盖请求 → 结构性流失

    # 护留系数 gamma：前期对"拆碎长块"的惩罚放大（保护后期长途），
    # 随时间推进线性衰减到 1（临近结束清仓、不再护留）。
    frac = (T - t) / T if T > 0 else 0.0
    gamma = 1.0 + 0.9 * frac  # 早期 ~1.9x，末期 1.0x

    # 接单条件：票价 >= gamma * 机会成本
    if p >= gamma * max(best_loss, 0.0):
        return best_uv
    return None
