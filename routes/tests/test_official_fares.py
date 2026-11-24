"""操作確認版の道路網で、公式の ETC 料金（普通車）と一致することを確かめた区間。

公式の料金: NEXCO 東日本「ドラぷら」で 2026-11-25（水）12:00 出発として検索（docs/research-demo-distances.md）。
一致しない区間（圏央道の短い区間、首都高の方向制限が絡むもの）は、原因を調べてから追加する。
中央道（高井戸〜八王子）の 630 円上限は反映済み（調布→八王子はドラぷら、八王子→高井戸は Google Routes API も 630 円）。
"""
import heapq
from datetime import datetime

import pytest

from engine.brute import brute_force, evaluate
from engine.search import Searcher
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
    ("chofu", "hachioji", 630),               # 中央道（対距離 750 円 → 630 円上限）
    ("hachioji", "takaido", 630),             # 中央道（対距離 1,000 円 → 630 円上限）
    ("yokohama_machida", "takaosan", 1500),   # 東名 → 圏央道（NEXCO として 1 回の利用）
    ("takaido_s", "shinjuku", 420),           # 首都高 4 号新宿線
    ("tamagawa", "hodogaya", 390),            # 第三京浜（料金表）
])
def test_matches_official_fare(a, b, official):
    net, tariffs, _ = demo.build()
    plan = evaluate(net, tariffs, WED_NOON, a, fastest_edges(net, a, b), {a: 0.0}, {b: 0.0})
    assert plan.fare == official


@pytest.mark.parametrize("entry, exit_, reachable", [
    ("takaido_s", "hatagaya", False),  # 都心方向の走行では幡ヶ谷の下り出口へ降りられない
    ("shinjuku", "hatagaya", False),  # デモ網にある西向き本線へ新宿から入れない
    ("takaido_s", "shinjuku", True),
    ("hatagaya", "shinjuku", True),
    ("youga", "nakano_chojabashi", False),  # デモ網は内回りの出口へ続く区間を持たない
    ("youga", "tomigaya", False),
    ("youga", "hatsudai_minami", True),
])
def test_demo_shutoko_ramp_directions(entry, exit_, reachable):
    net, tariffs, _ = demo.build()
    args = (net, tariffs, WED_NOON, {entry: 0}, {exit_: 0}, 30)
    expected = brute_force(*args)
    assert Searcher(net, tariffs).search(*args[2:]) == expected
    assert any(plan.exit == exit_ for plan in expected) == reachable


def test_chuo_cap_with_shutoko_and_through_city():
    """都心発着（中央道 → 首都高）は上限が効き、都心通過（東名 → 首都高 → 中央道）は対距離。"""
    net, tariffs, _ = demo.build()
    to_city = fastest_edges(net, "hachioji", "takaido") + fastest_edges(net, "takaido", "shinjuku")
    plan = evaluate(net, tariffs, WED_NOON, "hachioji", to_city, {"hachioji": 0.0}, {"shinjuku": 0.0})
    assert [r.fare for r in plan.runs] == [630, 420]
    through = (fastest_edges(net, "tomei_kawasaki", "tokyo") + fastest_edges(net, "tokyo", "takaido")
               + fastest_edges(net, "takaido", "hachioji"))
    plan = evaluate(net, tariffs, WED_NOON, "tomei_kawasaki", through, {"tomei_kawasaki": 0.0}, {"hachioji": 0.0})
    assert [r.pool for r in plan.runs] == ["nexco", "shutoko", "nexco"]
    assert plan.runs[-1].fare == 1000


@pytest.mark.parametrize("depart", [WED_NOON, datetime(2026, 11, 24, 23, 40), datetime(2026, 11, 25, 3, 50)],
                         ids=["noon", "before-midnight", "before-4am"])
@pytest.mark.parametrize("origin, dest, local", [
    ({"hachioji": 0}, {"takaido_s": 0, "shinjuku": 0}, 40),
    ({"chofu": 0}, {"hachioji": 0, "hachioji_jct": 0, "takaosan": 0}, 35),
    ({"tomei_kawasaki": 0}, {"hachioji": 0}, 70),   # 都心通過を含む
    ({"hachioji": 0}, {"tomei_kawasaki": 0}, 70),
])
def test_demo_chuo_cap_search_matches_brute(depart, origin, dest, local):
    net, tariffs, _ = demo.build()
    args = (net, tariffs, depart, origin, dest, local)
    assert Searcher(net, tariffs).search(*args[2:]) == brute_force(*args)
