"""操作確認版の道路網で、公式の ETC 料金（普通車）と一致することを確かめた区間。

公式の料金: NEXCO 東日本「ドラぷら」で 2026-11-25（水）12:00 出発として検索（docs/research-demo-distances.md）。
一致しない区間（圏央道の短い区間、中央道の 630 円上限、首都高の方向制限が絡むもの）は、原因を調べてから追加する。
"""
import heapq
from datetime import datetime

import pytest

from engine.brute import evaluate
from routes import demo

WED_NOON = datetime(2026, 11, 25, 12, 0)


def fastest_edges(net, a, b):
    dist, prev, pq = {a: 0.0}, {}, [(0.0, a)]
    while pq:
        d, u = heapq.heappop(pq)
        if u == b:
            break
        if d > dist[u]:
            continue
        for e in net.out[u]:
            nd = d + e.time_min
            if nd < dist.get(e.v, float("inf")):
                dist[e.v], prev[e.v] = nd, e
                heapq.heappush(pq, (nd, e.v))
    edges, v = [], b
    while v != a:
        edges.append(prev[v])
        v = prev[v].u
    return edges[::-1]


@pytest.mark.parametrize("a,b,official", [
    ("tokyo", "yokohama_machida", 800),       # 東名
    ("tokyo", "atsugi", 1300),                # 東名
    ("kunitachi_fuchu", "hachioji", 450),     # 中央道
    ("chofu", "inagi", 240),                  # 中央道
    ("yokohama_machida", "takaosan", 1500),   # 東名 → 圏央道（NEXCO として 1 回の利用）
    ("takaido_s", "shinjuku", 420),           # 首都高 4 号新宿線
    ("tamagawa", "hodogaya", 390),            # 第三京浜（料金表）
])
def test_matches_official_fare(a, b, official):
    net, tariffs, _ = demo.build()
    plan = evaluate(net, tariffs, WED_NOON, a, fastest_edges(net, a, b), {a: 0.0}, {b: 0.0})
    assert plan.fare == official
