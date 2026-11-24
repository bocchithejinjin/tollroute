"""中央道（高井戸〜八王子）の 630 円上限: 上限のある区間（Edge.cap_zone）と、都心通過で上限が外れる規則。

料金は tariffs.NexcoPool.caps と Tariffs.start_run / chain_key。探索（search.py）が総当たり（brute.py）と
一致することを、上限が効く・外れる境目と、深夜・休日割引の境目をまたいで確かめる。
"""
import math
import random
from datetime import datetime

import pytest

from engine.brute import evaluate
from engine.model import Edge, Network, Node
from engine.tariffs import NexcoPool, Step, default_tariffs

from .test_exact_search import MIXED_DEPARTS, all_plans, assert_same_front, mixed_query
from .test_search import tiny

ZONE = "chuo_takaido_hachioji"
WED_NOON = datetime(2026, 11, 25, 12, 0)
WED_1AM = datetime(2026, 11, 25, 1, 0)


def chuo(u, v, km, minutes=1.0, zone=ZONE):
    return Edge(u, v, "nexco", "中央道", km, minutes, "urban", holiday_ok=False, cap_zone=zone)


def run(tariffs, edges, depart=WED_NOON, prior=()):
    steps = [Step(e, depart, depart) for e in edges]
    return tariffs.run_fare(None, edges[0].u, edges[-1].v, steps, prior)


# ---------------------------------------------------------------- ラン単位の上限


def test_run_within_zone_is_capped():
    tariffs = default_tariffs()
    # 25.8km × 29.52 円 + 150 円 → 1,000 円。上限で 630 円
    rf = run(tariffs, [chuo("H", "C", 18.1), chuo("C", "T", 7.7)])
    assert (rf.base, rf.fare, rf.discount) == (630, 630, "630 円上限")
    assert rf.uncapped is not None and rf.uncapped.fare == 1000


def test_short_run_below_cap_is_unchanged():
    rf = run(default_tariffs(), [chuo("K", "H", 8.8)])  # 国立府中→八王子 450 円
    assert (rf.fare, rf.discount, rf.uncapped) == (450, None, None)


def test_run_leaving_zone_is_not_capped():
    """八王子より西（区間の外）へ続くランは「中央道内」ではないので、全体が対距離。"""
    edges = [chuo("T", "H", 25.8), Edge("H", "J", "nexco", "中央道", 10.2, 1, "normal")]
    rf = run(default_tariffs(), edges)
    assert rf.uncapped is None and rf.fare == round(((25.8 * 29.52 + 10.2 * 24.6) + 150) * 1.1, -1)


def test_night_discount_then_cap():
    """深夜割引は対距離の料金から引き、割引後が上限を超えるときだけ上限にする（未確認。高めに出る側）。"""
    tariffs = default_tariffs()
    long = run(tariffs, [chuo("H", "T", 25.8)], WED_1AM)  # 1,000 円の 3 割引 = 700 円 → 630 円
    assert (long.fare, long.discount) == (630, "630 円上限")
    mid = run(tariffs, [chuo("C", "H", 18.1)], WED_1AM)  # 750 円の 3 割引 = 530 円（上限より安い）
    assert (mid.base, mid.fare, mid.discount) == (750, 530, "深夜割引")


def test_cap_never_makes_longer_run_cheaper():
    """上限は min を取るだけなので、区間内の距離が増えても料金は下がらない。"""
    tariffs = default_tariffs()
    fares = [run(tariffs, [chuo("A", "B", km / 10)], t).fare for t in (WED_NOON, WED_1AM)
             for km in range(1, 600)]
    for t in range(2):
        part = fares[t * 599:(t + 1) * 599]
        assert all(a <= b for a, b in zip(part, part[1:]))


def test_validate_rejects_bad_cap():
    with pytest.raises(ValueError):
        NexcoPool(caps={ZONE: 0}).validate()


# ---------------------------------------------------------------- 都心発着と都心通過


def city_net():
    """W(東名) → T(東京) → 首都高 → K(高井戸) → 中央道 → H(八王子)。"""
    net = tiny([("W", True, True), ("T", True, True), ("K", True, True), ("H", True, True)], [])
    for a, b, e in [("W", "T", dict(pool="nexco", road="東名", dist_km=19.7, time_min=10, fare_class="urban",
                                    holiday_ok=False)),
                    ("T", "K", dict(pool="shutoko", road="首都高", dist_km=15.0, time_min=15)),
                    ("K", "H", dict(pool="nexco", road="中央道", dist_km=25.8, time_min=15, fare_class="urban",
                                    holiday_ok=False, cap_zone=ZONE))]:
        net.add_edge(Edge(a, b, **e))
        net.add_edge(Edge(b, a, **e))
    return net


def path(net, nodes):
    return [next(e for e in net.out[u] if e.v == v) for u, v in zip(nodes, nodes[1:])]


@pytest.mark.parametrize("nodes, fares", [
    (["K", "H"], [630]),                 # 中央道内
    (["T", "K", "H"], [700, 630]),       # 都心発着（首都高 → 中央道）
    (["H", "K", "T"], [630, 700]),       # 都心発着（中央道 → 首都高）
    (["W", "T", "K", "H"], [800, 700, 1000]),  # 都心通過（東名 → 首都高 → 中央道）
    (["H", "K", "T", "W"], [1000, 700, 800]),  # 都心通過（中央道 → 首都高 → 東名）。中央道の上限が後から外れる
])
def test_through_city_drops_cap(nodes, fares):
    net = city_net()
    plan = evaluate(net, default_tariffs(), WED_NOON, nodes[0], path(net, nodes), {nodes[0]: 0}, {nodes[-1]: 0})
    assert [r.fare for r in plan.runs] == fares
    assert plan.fare == sum(fares)


@pytest.mark.parametrize("depart", [WED_NOON, WED_1AM, datetime(2026, 11, 24, 23, 50)],
                         ids=["noon", "1am", "before-midnight"])
@pytest.mark.parametrize("origin, dest", [({"W": 0}, {"H": 0}), ({"H": 0}, {"W": 0}), ({"T": 0}, {"H": 0})])
def test_city_net_search_matches_brute(depart, origin, dest):
    assert_same_front(city_net(), default_tariffs(), depart, origin, dest, 200)


def test_capped_label_with_pending_revoke_does_not_dominate():
    """首都高の同じ入口から同じ区間に進む 2 つのラベル。

    A 発: 中央道の上限で 630 円（対距離 1,140 円）→ 先に着き、ここまでは安い。
    B 発: 区間の外の NEXCO 650 円 → 後に着く。
    この先さらに NEXCO へ移ると A 発は上限が外れて 1,140 円になるので、A 発が B 発を捨ててはいけない。
    """
    net = tiny([("A", True, False), ("B", True, False), ("T", False, False), ("K", False, False),
                ("Y", False, True)],
               [chuo("A", "T", 30, 5),
                Edge("B", "T", "nexco", "東名", 15, 6, "urban", holiday_ok=False),
                Edge("T", "K", "shutoko", "首都高", 5, 3),
                Edge("K", "Y", "nexco", "東北道", 10, 5, "normal")])
    got, _ = assert_same_front(net, default_tariffs(), WED_NOON, {"A": 0, "B": 0}, {"Y": 0}, 100)
    assert [(p.minutes, p.fare) for p in got if p.entry] == [(13, 1140 + 340 + 440), (14, 650 + 340 + 440)]


def test_zone_and_non_zone_distance_compared_separately():
    """区間の外を 1km 走って先に M に着く経路と、区間内だけを走って後に着く経路。

    距離を区間の内外で分けずに比べると、先の経路が後の経路を捨て、M→X の後で上限が効く後者を失う。
    """
    net = tiny([("A", True, False), ("M", False, False), ("X", False, True)],
               [Edge("A", "M", "nexco", "中央道", 1, 1, "urban", holiday_ok=False), chuo("A", "M", 1, 2),
                chuo("M", "X", 40, 1)])
    got, _ = assert_same_front(net, default_tariffs(), WED_NOON, {"A": 0}, {"X": 0}, 30)
    assert [(p.minutes, p.fare) for p in got] == [(2, 1500), (3, 630), (30, 0)]


# ---------------------------------------------------------------- 乱数網で総当たりと照合


def cap_net(seed, n=11):
    """上限区間の NEXCO・ほかの NEXCO（休日割引あり／なし、深夜割引あり／なし）・首都高を混ぜた網。"""
    rnd = random.Random(seed)
    pts = [(rnd.uniform(0, 45), rnd.uniform(0, 45)) for _ in range(n)]
    net = Network()
    for i, (x, y) in enumerate(pts):
        r = rnd.random()
        net.add_node(Node(f"n{i}", f"n{i}", y, x, can_enter=r > 0.2, can_exit=r > 0.2 or r < 0.1))
    pairs = set()
    for i in range(n):
        near = sorted(range(n), key=lambda j: math.dist(pts[i], pts[j]))[1:4]
        pairs |= {tuple(sorted((i, j))) for j in near}
    for i, j in sorted(pairs):
        d = round(math.dist(pts[i], pts[j]) * 1.1, 1)
        kind = rnd.choice(["zone", "zone", "nexco", "shutoko", "shutoko"])
        minutes = max(1, round(d * rnd.uniform(1.0, 1.4) * 4) / 4)
        if kind == "shutoko":
            spec = dict(pool="shutoko", road="首都高")
        elif kind == "zone":
            spec = dict(pool="nexco", road="中央道", fare_class="urban", holiday_ok=False, cap_zone="z")
        else:
            spec = dict(pool="nexco", road="NEXCO", fare_class=rnd.choice(["urban", "normal"]),
                        holiday_ok=rnd.random() < 0.6, night_ok=rnd.random() < 0.8)
        for a, b in ((i, j), (j, i)):
            net.add_edge(Edge(f"n{a}", f"n{b}", dist_km=d, time_min=minutes, **spec))
    tariffs = default_tariffs()
    tariffs.pools["nexco"].caps = {"z": 400}  # 上限が効く・外れる境目を増やす
    return net, tariffs, pts


@pytest.mark.parametrize("seed", range(10))
@pytest.mark.parametrize("depart", MIXED_DEPARTS, ids=lambda d: d.strftime("%m%d-%H%M"))
def test_cap_networks_match_brute(seed, depart):
    net, tariffs, pts = cap_net(seed)
    origin, dest, local, lb = mixed_query(pts, seed)
    front, _ = assert_same_front(net, tariffs, depart, origin, dest, local, lb)
    for budget in sorted({p.fare for p in front} | {p.fare - 1 for p in front if p.fare}):
        assert_same_front(net, tariffs, depart, origin, dest, local, lb, budget)


def test_cap_networks_exercise_the_rules():
    """乱数網の照合が、上限・都心通過の両方を実際に通っていることを確かめる（テストの空振り防止）。"""
    capped = revoked = 0
    for seed in range(10):
        net, tariffs, pts = cap_net(seed)
        origin, dest, local, lb = mixed_query(pts, seed)
        for plan in assert_same_front(net, tariffs, WED_NOON, origin, dest, local, lb)[0]:
            capped += any(r.uncapped is not None for r in plan.runs)
        for plan in all_plans(net, tariffs, WED_NOON, origin, dest, local):
            pools = [r.pool for r in plan.runs]
            revoked += any(pools[k:k + 3] == ["nexco", "shutoko", "nexco"] for k in range(len(pools)))
    assert capped and revoked
