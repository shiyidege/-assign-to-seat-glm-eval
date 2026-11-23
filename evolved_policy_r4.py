import math

_PLEN = {L: int(10 * (L ** 0.8)) for L in range(1, 20)}

def _omega(u, v, rem):
    """空闲块 [u,v] 的未来期望收益（长行程优先贪心填充近似 V(u,v)）。"""
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
    Lreq = req_j - req_i + 1

    # ============ 第一步：腿级稀缺度 + 未来加权单位里程价值 ============
    # v3 诊断：端部区间 1/M 大量剩座，中间区间耗尽、长途全靠"撞库存"。
    # 根因：几乎不拒短单 → 短单反复切割中间区间 → 长连续区间消失。
    # 修正：用"腿级未来需求 vs 剩余容量"算稀缺度 s_l，
    # 以及该腿上未来期望需求的加权单位里程价 vbar_l。
    cap = [0] * (M + 2)
    for (u, v), c in counts.items():
        if c > 0:
            for l in range(u, v + 1):
                cap[l] += c
    dem = [0.0] * (M + 2)     # 未来期望需求数（人次）
    wval = [0.0] * (M + 2)    # 未来期望需求 * 单位里程价 累计
    for (a, b), r in rem.items():
        if r > 0:
            pl = _PLEN.get(b - a + 1, prices.get((a, b), 0)) / (b - a + 1)
            for l in range(a, b + 1):
                dem[l] += r
                wval[l] += r * pl

    # 请求覆盖的腿中：最大稀缺度 & 最高未来单位里程价
    s_max = 0.0
    vbar_max = 0.0
    for l in range(req_i, req_j + 1):
        if dem[l] > 1e-9 and wval[l] > 1e-9:
            s = (dem[l] - cap[l]) / dem[l]  # >0 表示未来该腿供不应求
            if s > s_max:
                s_max = s
            vb = wval[l] / dem[l]
            if vb > vbar_max:
                vbar_max = vb

    # ============ 第二步：护留决策 ============
    # 若该请求单位里程价低于"未来更高价值用途"的单位里程价，
    # 且相关腿未来供不应求（s_max 大），则主动拒单。
    # 护留强度随时间衰减（临近结束不再护留）。
    my_pl = p / Lreq
    frac = (T - t) / T if T > 0 else 0.0
    if s_max > 0.0 and my_pl < vbar_max:
        # 溢价缺口 * 稀缺度 * 紧迫度因子；短途且切割中间区间时惩罚更重
        gap = (vbar_max - my_pl) * Lreq          # 该单的潜在"价值损失上限"
        margin = gap * (s_max ** 1.5) * (0.5 + 0.8 * frac)
        if p < margin:
            # 中间切割（req 两侧都不在块端）额外更难被接受已由选块处理；
            # 这里直接拒单以保护长连续区间
            return None

    # ============ 第三步：Assign-to-Seat 选块 ============
    # 在能覆盖请求的块中选"接单后期望损失最小"的块：
    # 1) 端部切割打折（只产生一个碎片，保护连续性）；
    # 2) 偏好小而"死"的块（未来期望价值低的块先被牺牲）。
    best_key = None
    for (u, v), c in counts.items():
        if c <= 0 or u > req_i or v < req_j:
            continue
        loss = _omega(u, v, rem) - _omega(u, req_i - 1, rem) - _omega(req_j + 1, v, rem)
        if loss < 0.0:
            loss = 0.0
        edge = (u == req_i) or (v == req_j)
        # 端部切割 0.7 折；块越小未来价值越低 → loss 本身就越小，天然优先
        key = loss * (0.7 if edge else 1.0)
        if best_key is None or key < best_key:
            best_key, best_uv = key, (u, v)

    if best_key is None:
        return None

    # 简单机会成本闸门（防极端拆碎），晚期放宽
    gamma = 1.0 + 0.3 * frac
    if p >= gamma * best_key:
        return best_uv
    return None
