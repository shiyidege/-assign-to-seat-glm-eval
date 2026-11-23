import math

def _up(a, b):
    L = b - a + 1
    return L ** 0.8  # 与价目 int(10*L^0.8) 同构的单位里程价值

def _fluid_V(blocks, rem):
    """确定性流体近似：按单位里程价降序贪心填充全车最大连续空闲块。"""
    dems = []
    for (a, b), r in rem.items():
        if r > 1e-9:
            dems.append((_up(a, b), a, b, r))
    if not dems:
        return 0.0
    dems.sort(key=lambda x: -x[0])
    for pr, a, b, r in dems:
        if not blocks:
            return _fluid_V._t
        L = b - a + 1
        # 块选择：先贴合度(浪费最少)，触边切割(只产生一个碎片)优先，再牺牲小死块
        cand = []
        for idx, (u, v, c) in enumerate(blocks):
            if u <= a and v >= b and c > 1e-9:
                gap = (v - u) - L
                edge = 0 if (u == a or v == b) else 1
                cand.append((gap, edge, c, idx))
        if not cand:
            continue
        cand.sort()
        for gap, edge, c, idx in cand:
            if r <= 1e-9:
                break
            take = c if c < r else r
            _fluid_V._t += take * pr * L
            r -= take
            u, v, cc = blocks[idx]
            blocks[idx] = (u, v, cc - take)
        blocks = [x for x in blocks if x[2] > 1e-9]
    return _fluid_V._t

def _make_blocks(counts):
    return [(u, v, float(c)) for (u, v), c in counts.items() if c > 0]

def decide(t, T, M, counts, req_i, req_j, prices, remaining_expected):
    p = prices.get((req_i, req_j), int(10 * ((req_j - req_j + req_i) ** 0.8)) if False
                   else int(10 * ((req_j - req_i + 1) ** 0.8)))
    rem = remaining_expected
    frac = (T - t) / T if T > 0 else 0.0

    blocks = _make_blocks(counts)
    _fluid_V._t = 0.0
    V0 = _fluid_V([(u, v, c) for (u, v, c) in blocks], rem)

    Lreq = req_j - req_i + 1

    # ---- 遍历能容纳请求的块，选机会成本最小者 ----
    best = None  # (delta_adj, -edge, -u, v), (u,v)
    for (u, v), c in counts.items():
        if c <= 0 or u > req_i or v < req_j:
            continue
        nb = _make_blocks(counts)
        for i, (uu, vv, cc) in enumerate(nb):
            if uu == u and vv == v:
                nb[i] = (u, v, cc - 1.0)
                break
        nb = [x for x in nb if x[2] > 1e-9]
        if u < req_i:
            nb.append((u, req_i - 1, 1.0))
        if req_j < v:
            nb.append((req_j + 1, v, 1.0))
        _fluid_V._t = 0.0
        V1 = _fluid_V(nb, rem)
        delta = V0 - V1
        if delta < 0.0:
            delta = 0.0

        # 轻量碎片惩罚：中间双切割（两侧都留碎片）额外计入长连续性损失
        blk_L = v - u + 1
        if u < req_i and req_j < v:  # 双切割
            # 碎片越小越难被未来长需求利用：按被切碎比例计小惩罚
            delta += 0.8 * (Lreq / blk_L) * (0.3 + 0.7 * frac)

        # 平手偏好：触边切割优先（-edge 越大越优先），再按论文 tie-break
        edge = 1 if (u == req_i or v == req_j) else 0
        key = (delta, -edge, -u, v)
        if best is None or key < best[0]:
            best = (key, (u, v), delta)

    if best is None:
        return None

    uv = best[1]
    delta = best[2]

    # BPC-M：p >= 机会成本即接单（纯边际收益准则，无额外时间衰减）
    if p >= delta - 1e-9:
        return uv
    return None
