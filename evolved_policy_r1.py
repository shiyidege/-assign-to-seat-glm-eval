import math
from collections import defaultdict

_PLEN = {}
for _L in range(1, 17):
    _PLEN[_L] = int(10 * (_L ** 0.8))

_omega_cache = {}

def _omega(u, v, remaining_expected):
    """估计空闲块 [u,v] 在未来需求下的期望收益 Ω(u,v)：
    贪心：长行程优先（单位里程价更高、且保护连续性），对每个长度 L，
    统计 [u,v] 内所有长度为 L 的未来期望需求，按可用容量截断累加收益。"""
    if u > v:
        return 0.0
    key = (u, v, tuple(sorted((k, round(val, 4)) for k, val in remaining_expected.items() if val > 1e-6)))
    if key in _omega_cache:
        return _omega_cache[key]
    seats = 1.0  # 单个座位块（counts 中每个条目代表若干块，逐块评估）
    value = 0.0
    L = v - u + 1
    while L >= 1 and seats > 1e-9:
        # 块内所有长度 L 行程的总期望需求
        dem = 0.0
        for a in range(u, v - L + 2):
            dem += remaining_expected.get((a, a + L - 1), 0.0)
        served = min(dem, seats)
        value += served * _PLEN[L]
        seats -= served
        L -= 1
    if len(_omega_cache) < 200000:
        _omega_cache[key] = value
    return value

def decide(t, T, M, counts, req_i, req_j, prices, remaining_expected):
    p = prices.get((req_i, req_j), _PLEN[req_j - req_i + 1])
    # 候选块：能覆盖 [req_i, req_j] 且仍有库存的最大连续空闲区间
    best = None  # (net, (u,v))
    for (u, v), c in counts.items():
        if c <= 0 or u > req_i or v < req_j:
            continue
        # 机会成本 = 保护该块不动未来期望收益 - 接单后碎片期望收益
        loss = _omega(u, v, remaining_expected) \
             - _omega(u, req_i - 1, remaining_expected) \
             - _omega(req_j + 1, v, remaining_expected)
        net = p - loss
        if best is None or net > best[0]:
            best = (net, (u, v))
    if best is None:
        return None
    # 接单条件：收益 >= 机会成本（net >= 0）。
    # 加一点保守余量：前期(t 小)多保护长途，后期放宽清仓
    threshold = 0.0 if t > 0.7 * T else -0.15 * p
    if best[0] >= threshold:
        return best[1]
    return None
