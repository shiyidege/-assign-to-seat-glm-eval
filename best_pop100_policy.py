# E097[Cross(E087+E082)]：两亲本同源，差异仅在4个标量参数。失分诊断：①Case1两端剩座过大([2.15,..,3.15])且L1-L3 acc%低→端部容量未充分利用，短单竞争截断仍偏保守；②Case2中段L2-L4 acc%仅~30%→碎片化拒单为主因，需更强的碎片惩罚与端部让利。融合策略：主干沿用E087（2情景鲁棒流体+调和markdown+左贴合tie-break+末端倾销），参数取两者均值并做定向修正：①fcoef基线取中值0.38（比E082强、比E087松，兼顾两案例）；②快车道门限取中(rho<=0.89/fill<0.43)；③comp_cut取0.20；④新增端部让利修正：请求区间触达系统端点(1或M)且对应端段rho<1.0时，竞争需求lam剔除同端短途流再计算，降低端部短单的机会成本高估，提升两端利用率；⑤short_corr取0.855
import math
_exp = math.exp

def _pois_ge(lam, k):
    if k <= 0:
        return 1.0
    if lam <= 1e-9:
        return 0.0
    if lam > 25.0:
        z = (k - 1 - lam) / math.sqrt(lam)
        if z > 4.0:
            return 0.0
        if z < -4.0:
            return 1.0
        return 0.5 * (1.0 - math.erf(z / 1.4142135623730951))
    term = _exp(-lam)
    s = term
    for i in range(1, k):
        term *= lam / i
        s += term
    return max(0.0, 1.0 - s)

def _alloc_demand(blocks, a, b, r, pr):
    L = b - a + 1
    total = 0.0
    cand = []
    for idx, (u, v, c) in enumerate(blocks):
        if u <= a and v >= b and c > 1e-9:
            cand.append(((v - u + 1) - L, -c, idx))
    if not cand:
        return 0.0
    cand.sort()
    for waste, ncm, idx in cand:
        if r <= 1e-9:
            break
        u, v, c = blocks[idx]
        take = c if c < r else r
        total += take * pr * L
        r -= take
        blocks[idx] = (u, v, c - take)
        if u < a:
            blocks.append((u, a - 1, take))
        if b < v:
            blocks.append((b + 1, v, take))
    return total

def _fluid_V(blocks, rem):
    dems = []
    for (a, b), r in rem.items():
        if r > 1e-9:
            dems.append(((b - a + 1) ** 0.8, a, b, r))
    if not dems:
        return 0.0
    dems.sort(key=lambda x: (-x[0], x[1], x[2]))
    tot = 0.0
    for pr, a, b, r in dems:
        tot += _alloc_demand(blocks, a, b, r, pr)
    return tot

def _robust_V(base_blocks, rem):
    v = 0.0
    for sc in (0.85, 1.15):
        rrem = {k: x * sc for k, x in rem.items()}
        v += 0.5 * _fluid_V(list(base_blocks), rrem)
    return v

def decide(t, T, M, counts, req_i, req_j, prices, remaining_expected):
    Lreq = req_j - req_i + 1
    p = prices.get((req_i, req_j), int(10 * (Lreq ** 0.8)))
    frac = (T - t) / float(T) if T > 0 else 0.0

    rem = {}
    for k, val in remaining_expected.items():
        if k == (req_i, req_j):
            val -= 1.0
        if val > 1e-9:
            rem[k] = val

    blocks0 = [(u, v, float(c)) for (u, v), c in counts.items() if c > 0]
    if not blocks0:
        return None

    # ---- 段级容量与需求强度 ----
    cap_s = [0.0] * (M + 2)
    for (u, v), c in counts.items():
        if c > 0:
            for s in range(u, v + 1):
                cap_s[s] += c
    dem_s = [0.0] * (M + 2)
    for (a, b), r in rem.items():
        for s in range(a, b + 1):
            dem_s[s] += r

    rho = 0.0
    rho_min = 1e9
    rho_mid = 0.0
    inv_harm = 0.0
    fill = 0.0
    seg = req_j - req_i + 1
    segs = []
    for s in range(req_i, req_j + 1):
        lam_s = dem_s[s]
        if cap_s[s] <= 1e-9:
            rho = 3.0; rho_min = 3.0; rho_mid = 3.0; fill = 1.0
            segs = []
            break
        r_s = lam_s / cap_s[s]
        segs.append(r_s)
        rho = max(rho, r_s)
        rho_min = min(rho_min, r_s)
        fill = max(fill, _pois_ge(lam_s, int(cap_s[s] - 1e-9) + 1))
    if segs:
        srt = sorted(segs)
        rho_mid = srt[len(srt) // 2]
        inv_harm = sum(1.0 / max(r, 0.05) for r in srt)
    else:
        inv_harm = float(seg) / 3.0
    rho = min(rho, 3.0)
    if rho_min > 3.0:
        rho_min = 3.0
    if fill < 1e-6:
        fill = 1.0 - _exp(-rho)
    fill = min(max(fill, 0.02), 1.0)
    if rho_min > 1e9:
        rho_min = 1.0
    if inv_harm <= 1e-9:
        rho_harm = rho_min
    else:
        rho_harm = seg / inv_harm

    cands = [(u, v) for (u, v), c in counts.items() if c > 0 and u <= req_i and req_j <= v]

    # ==== 末端倾销（左贴合优先tie-break）====
    no_future = all(r <= 1e-9 for r in rem.values())
    if t >= T or no_future or (frac <= 0.08 and rho < 1.6):
        best = None
        for (u, v) in cands:
            key = (0 if (u == req_i and v == req_j) else 1,
                   (v - u + 1) - Lreq,
                   0 if u == req_i else 1,
                   0 if v == req_j else 1, -u, v)
            if best is None or key < best[0]:
                best = (key, (u, v))
        if best is not None:
            return best[1]

    # ==== exact-fit低紧张直通 ====
    if fill < 0.35 and rho < 1.0:
        for (u, v) in cands:
            if (v - u + 1) == Lreq:
                return (u, v)

    # ==== 快速放行车道（参数取两亲本中值）====
    if rho <= 0.89 and rho_mid <= 0.55 and fill < 0.43 and Lreq <= 5:
        best = None
        for (u, v) in cands:
            edge = 0 if (u == req_i or v == req_j) else 1
            exact = 0 if (v - u + 1) == Lreq else 1
            left = 1 if u == req_i else 0
            key = (exact, edge, (v - u) - Lreq, -left, -u, v)
            if best is None or key < best[0]:
                best = (key, (u, v))
        if best is not None:
            return best[1]

    V0 = _robust_V(blocks0, rem)

    # ---- 竞争流强度（含端部让利修正）----
    up_req = Lreq ** 0.8
    lam = 0.0
    lam_all = 0.0
    # 端部让利：请求触达端点且端段宽松时，剔除同端短途竞争流（它们可用端部碎片，不与本单抢完整区间）
    edge_relax = ((req_i == 1 and rho_min < 1.0) or (req_j == M and rho_min < 1.0)) and fill < 0.5
    for (a, b), r in rem.items():
        lam_all += r
        if a <= req_j and b >= req_i and (b - a + 1) ** 0.8 >= up_req - 1e-9:
            if edge_relax and ((a == 1 and req_i == 1 and b - a + 1 <= 2) or
                               (b == M and req_j == M and b - a + 1 <= 2)):
                continue
            lam += r
    comp = 1.0 - _exp(-lam)
    cv = 0.5 if lam_all <= 4.0 else min(0.5, 1.0 / math.sqrt(lam_all))
    kappa = 0.35 * (1.0 - frac)

    scale = max(rho, 1e-6) ** 0.45
    markdown = max(rho_harm, 0.25) ** 0.55
    if 0.8 < rho < 1.2:
        markdown *= 0.92
    if fill > 0.5:
        f_fill = 0.60 + 0.50 * fill
    elif fill > 0.2:
        f_fill = 0.48 + 0.75 * fill
    else:
        f_fill = 0.42 + 0.30 * fill
    f_comp = 0.52 + 0.48 * comp
    lenw = 0.5 + 0.5 * (Lreq / M)
    stoch = f_fill * f_comp * (1.0 - 0.15 * frac) ** lenw
    short_corr = 0.855 + 0.145 * (Lreq / M)

    if frac >= 0.22:
        theta = 0.65 + 0.35 * frac
    else:
        theta = max(0.35, 0.35 + 0.70 * (frac / 0.22))

    # 碎片系数：两亲本折中（E082=0.34基线偏松致Case2碎片拒单，E087=0.42偏紧伤Case1吞吐，取0.38）
    fcoef = 0.38 + 0.06 * min(1.0, max(0.0, (0.75 - frac) / 0.35))

    best = None
    for (u, v) in cands:
        nb = []
        for (uu, vv, cc) in blocks0:
            if uu == u and vv == v:
                cc -= 1.0
            if cc > 1e-9:
                nb.append((uu, vv, cc))
        if u < req_i:
            nb.append((u, req_i - 1, 1.0))
        if req_j < v:
            nb.append((req_j + 1, v, 1.0))
        V1 = _robust_V(nb, rem)
        delta = V0 - V1
        if delta < 0.0:
            delta = 0.0

        if u < req_i and req_j < v:
            delta += 0.8 * (Lreq / (v - u + 1)) * (0.3 + 0.7 * frac) * (0.7 + 0.3 * scale)
        if (v - u + 1) == Lreq:
            delta *= 0.90

        wasteL = u - req_i
        wasteR = req_j - v
        if wasteL > 0 or wasteR > 0:
            frag_cost = (wasteL ** 0.7 + wasteR ** 0.7) * (1.0 - frac) * fcoef
            if frac > 0.4 and wasteL > 0 and wasteR > 0:
                frag_cost *= 1.15
        else:
            frag_cost = -0.02 * (1.0 - frac) if frac < 0.5 else 0.0

        # 主tie-break：左贴合优先
        key = (delta + frag_cost, -(1 if u == req_i else 0), -u, v)
        if best is None or key < best[0]:
            best = (key, (u, v), delta)

    if best is None:
        return None
    uv = best[1]
    # 竞争截断因子：两亲本折中（E082=0.25偏保守伤Case1端部短单，E087=0.18，取0.20）
    comp_cut = 1.0 + 0.20 * comp * (1.0 - fill)
    delta = best[2] * scale * stoch * markdown * short_corr * (1.0 + kappa * cv) * comp_cut

    if t >= T or p >= delta * theta - 1e-9:
        return uv
    return None
