"""比較用の架空の高速道路網を作る。

中心部に metro（入口と出口で料金が決まる都市高速）、その周りに大都市近郊区間、
外側に普通区間の nexco、外れのほうに固定料金で時間帯によって料金が変わる aqua を置く。
"""
from __future__ import annotations

import math
import random
from datetime import datetime

from model import Edge, Network, Node, Query

SIZE_KM = 160.0


def make_network(n: int, seed: int, k: int = 3) -> Network:
    rnd = random.Random(seed)
    c = SIZE_KM / 2
    pts = []
    while len(pts) < n:
        x, y = rnd.uniform(0, SIZE_KM), rnd.uniform(0, SIZE_KM)
        if all(math.hypot(x - a, y - b) > 2.0 for a, b in pts):
            pts.append((x, y))
    net = Network()
    for i, (x, y) in enumerate(pts):
        r = rnd.random()
        if r < 0.15:  # JCT
            node = Node(f"n{i}", x, y, False, False)
        elif r < 0.20:
            node = Node(f"n{i}", x, y, True, False)
        elif r < 0.25:
            node = Node(f"n{i}", x, y, False, True)
        else:
            node = Node(f"n{i}", x, y)
        net.add_node(node)

    pairs = set()
    for i, (x, y) in enumerate(pts):
        near = sorted(range(n), key=lambda j: math.hypot(pts[j][0] - x, pts[j][1] - y))[1 : k + 1]
        for j in near:
            pairs.add((min(i, j), max(i, j)))
    # 連結にする（プリム法で最小全域木の辺を足す）
    inside, rest = {0}, set(range(1, n))
    while rest:
        i, j = min(
            ((a, b) for a in inside for b in rest),
            key=lambda ab: math.hypot(pts[ab[0]][0] - pts[ab[1]][0], pts[ab[0]][1] - pts[ab[1]][1]),
        )
        pairs.add((min(i, j), max(i, j)))
        inside.add(j)
        rest.discard(j)

    pairs = sorted(pairs)
    outer = [p for p in pairs if _mid_r(pts, p, c) > 55]
    aqua = set(rnd.sample(outer, min(2, len(outer))))
    for i, j in pairs:
        d = math.hypot(pts[i][0] - pts[j][0], pts[i][1] - pts[j][1]) * 1.1
        r = _mid_r(pts, (i, j), c)
        if (i, j) in aqua:
            e = Edge(f"n{i}", f"n{j}", "aqua", d, d / 80 * 60, "normal", flat_yen=rnd.choice([600, 800, 1200]))
        elif r < 22:
            e = Edge(f"n{i}", f"n{j}", "metro", d, d / 50 * 60)
        elif r < 50:
            e = Edge(f"n{i}", f"n{j}", "nexco", d, d / 85 * 60, "urban")
        else:
            e = Edge(f"n{i}", f"n{j}", "nexco", d, d / 95 * 60, "normal")
        net.add_edge(e)
    return net


def _mid_r(pts, p, c):
    i, j = p
    mx, my = (pts[i][0] + pts[j][0]) / 2, (pts[i][1] + pts[j][1]) / 2
    return math.hypot(mx - c, my - c)


DEPARTURES = {
    "weekday_noon": datetime(2026, 11, 25, 12, 0),
    "saturday_noon": datetime(2026, 11, 28, 12, 0),
    "weekday_2330": datetime(2026, 11, 25, 23, 30),
    "saturday_1400": datetime(2026, 11, 28, 14, 0),
    "friday_2350": datetime(2026, 11, 27, 23, 50),
}


def make_query(seed: int, depart: datetime) -> Query:
    rnd = random.Random(seed * 7919 + 13)
    while True:
        ox, oy, dx, dy = (rnd.uniform(5, SIZE_KM - 5) for _ in range(4))
        if math.hypot(ox - dx, oy - dy) > 50:
            return Query(ox, oy, dx, dy, depart)
