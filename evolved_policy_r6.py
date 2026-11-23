import math

def _up(a, b):
    L = b - a + 1
    return L ** 0.8  # 与价目 int(10*L^0.8) 同构的单位里程价值

def _fluid_V(blocks, rem, stress):
    """确定性流体近似：按单位里程价降序贪心填充全车最大连续空闲块。
    stress: 按行程长度加权的紧缺乘子（保护长行程）。
    返回 (总未来期望收益, 各长度服务的需求量统计)。"""
    dems = []
    for (a, b), r in rem.items():
        if r > 1e-9:
            L = b - a + 1
            dems.append((_up(a, b) * stress.get(L, 1.0), a, b, r))
    if not dems:
        return 0.0
    dems.sort(key=lambda x: -x[0])
    total = 0.0
    for pr, a, b, r in dems:
        if not blocks:
            break
        L = b - a + 1
        # 块选择：先贴合度(碎片最少/贴合边缘)，再剩余量小(牺牲死块)
        cand = []
        for idx, (u, v, c) in enumerate(blocks):
            if u <= a and v >= b and c > 1e-9:
                gap = (v - u) - L
                edge = 0 if (u == a or v == b) else 1  # 触边切割只产生一个碎片
                cand.append((gap, edge, c, idx))
        if not cand:
            continue
        cand.sort()
        for gap, edge, c, idx in cand:
            if r <= 1e-9:
                break
            take = c if c < r else r
            total += take * pr * L
            r -= take
            u, v, cc = blocks[idx]
            blocks[idx] = (u, v, cc - take)
        blocks = [x for x in blocks if x[2] > 1e-9]
    return total

def _make_blocks(counts):
    return [(u, v, float(c)) for (u, v), c in counts.items() if c > 0]

def _snapshot(blocks):
    return [(u, v, c) for (u, v, c) in blocks]

def decide(t, T, M, counts, req_i, req_j, prices, remaining_expected):
    p = prices.get((req_i, req_j), int(10 * ((req_j - req_i + 1) ** 0.8)))
    rem = remaining_expected
    frac = (T - t) / T if T > 0 else 0.0

    # ---- 紧缺度加权：长行程需求相对长块容量越紧缺，越要保护 ----
    cap = [0.0] * (M + 2)
    blocks = _make_blocks(counts)
    for (u, v, c) in blocks:
        for l in range(u, v + 1):
            cap[l] += c
    stress = {}
    for L in range(1, M + 1):
        dem = 0.0
        supp = 0.0
        for (a, b), r in rem.items():
            if r > 1e-9 and b - a + 1 == L:
                dem += r
                for (u, v, c) in blocks:
                    if u <= a and v >= b:
                        supp += c
                        break
        if dem > 1e-9 and supp < dem:
            stress[L] = 1.0 + 0.35 * (1.0 - supp / dem) * (L / M)
        else:
            stress[L] = 1.0

    V0 = _fluid_V(_snapshot(blocks), rem, stress)

    # ---- 遍历能容纳请求的块，选 p + V_after 最大者 ----
    best = None  # (delta, -edge, -u, v)
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
        V1 = _fluid_V(nb, rem, stress)
        delta = V0 - V1
        if delta < 0.0:
            delta = 0.0
        # 时间衰减：临近结束，未来期望收益价值递减（不过度护留）
        delta *= (0.35 + 0.65 * frac) ** 0.7
        edge = 1 if (u == req_i or v == req_j) else 0  # 平手偏好触边
        key = (delta, -edge, -u, v)
        if best is None or key < best[0]:
            best = (key, (u, v), delta)

    if best is None:
        return None

    uv = best[1]
    delta = best[2]

    # BPC-M：p > 机会成本即接单；临末期几乎无成本
    if p >= delta - 1e-9:
        return uv
    return None
