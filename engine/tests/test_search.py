"""探索が総当たりと同じ答えを出すか（本番の料金規則で、深夜・休日をまたぐ出発時刻も含めて）。"""
import math
import random
from datetime import datetime, timedelta

import pytest

from engine.brute import brute_force, evaluate
from engine.model import Edge, Network, Node
from engine.search import Searcher, pick
from engine.tariffs import OdVersion, TollgatePool, aqua_gate, default_tariffs


def random_net(seed, n=16):
    rnd = random.Random(seed)
    pts = [(rnd.uniform(0, 80), rnd.uniform(0, 80)) for _ in range(n)]
    net = Network()
    for i, (x, y) in enumerate(pts):
        r = rnd.random()
        net.add_node(Node(f"n{i}", f"n{i}", y, x, can_enter=r > 0.15, can_exit=r > 0.15 or r < 0.05))
    pairs = set()
    for i in range(n):
        near = sorted(range(n), key=lambda j: math.dist(pts[i], pts[j]))[1:3]
        pairs |= {tuple(sorted((i, j))) for j in near}
    for i in range(1, n):  # 連結にする
        j = min(range(i), key=lambda j: math.dist(pts[i], pts[j]))
        pairs.add((j, i))
    od = {}
    for i, j in sorted(pairs):
        d = math.dist(pts[i], pts[j]) * 1.1
        mid = math.dist(((pts[i][0] + pts[j][0]) / 2, (pts[i][1] + pts[j][1]) / 2), (40, 40))
        kind = rnd.random()
        if mid < 15:
            spec = dict(pool="shutoko", road="首都高", time_min=d / 50 * 60)
        elif kind < 0.08:
            spec = dict(pool="aqualine", road="アクアライン", time_min=d / 80 * 60, tollgate=f"g{i}")
        elif kind < 0.16:
            spec = dict(pool="table", road="表の道路", time_min=d / 70 * 60)
        elif kind < 0.22:
            spec = dict(pool="yokohama_shindo", road="横浜新道", time_min=d / 60 * 60, tollgate=f"g{i}")
        else:
            urban = mid < 30
            spec = dict(pool="nexco", road="NEXCO", time_min=d / 85 * 60, fare_class="urban" if urban else "normal",
                        holiday_ok=not urban)
        for a, b, direction in ((i, j, "up"), (j, i, "down")):
            extra = {"direction": direction} if spec["pool"] == "aqualine" else {}
            net.add_edge(Edge(f"n{a}", f"n{b}", dist_km=d, **spec, **extra))
    tariffs = default_tariffs()
    # 料金表の道路: 料金表に全組み合わせを入れる（距離 × 20 円）
    table_nodes = {e.u for e in net.edges() if e.pool == "table"} | {e.v for e in net.edges() if e.pool == "table"}
    from engine.tariffs import OdTablePool
    tbl = {(a, b): 50 + 10 * ((hash((a, b)) % 40)) for a in table_nodes for b in table_nodes if a != b}
    tbl = {k: v for k, v in tbl.items()}
    sym = {}
    for (a, b), v in tbl.items():
        sym[(a, b)] = sym.get((b, a), v)
    tariffs.pools["table"] = OdTablePool(id="table", table=sym)
    return net, tariffs, pts


def query(net, pts, seed):
    rnd = random.Random(seed + 1000)
    o = (rnd.uniform(0, 80), rnd.uniform(0, 80))
    d = (rnd.uniform(0, 80), rnd.uniform(0, 80))
    loc = lambda p, q: math.dist(p, q) * 1.3 / 30 * 60
    origin = {f"n{i}": loc(o, pts[i]) for i in range(len(pts))}
    dest = {f"n{i}": loc(pts[i], d) for i in range(len(pts))}
    lb = {f"n{i}": math.dist(pts[i], d) / 100 * 60 for i in range(len(pts))}
    return origin, dest, loc(o, d), lb


DEPARTS = [
    datetime(2026, 11, 25, 12, 0),   # 平日の昼
    datetime(2026, 11, 28, 13, 0),   # 土曜の昼（アクアラインの境目の前後）
    datetime(2026, 11, 27, 23, 20),  # 金曜の深夜（0 時をまたぐ）
    datetime(2026, 11, 28, 3, 30),   # 土曜の早朝（4 時をまたぐ）
    datetime(2026, 9, 30, 23, 30),   # 首都高の料金改定の前夜
    datetime(2026, 10, 1, 0, 0),    # 首都高の料金改定ちょうど
    datetime(2026, 11, 29, 19, 0),   # アクアラインの休日時間帯の切替
    datetime(2027, 3, 31, 23, 55),  # アクアラインの時間帯別料金の実施期間終了
]


@pytest.mark.parametrize("seed", range(8))
@pytest.mark.parametrize("depart", DEPARTS, ids=lambda d: d.strftime("%m%d-%H%M"))
def test_search_matches_brute(seed, depart):
    net, tariffs, pts = random_net(seed)
    origin, dest, local, lb = query(net, pts, seed)
    truth = brute_force(net, tariffs, depart, origin, dest, local, lb)
    got = Searcher(net, tariffs).search(depart, origin, dest, local, lb)
    assert [(p.minutes, p.fare) for p in got] == [(p.minutes, p.fare) for p in truth]
    for p in got:  # 報告した料金が、経路を計算し直した料金と一致する
        if p.entry:
            again = evaluate(net, tariffs, depart, p.entry, [s.edge for s in p.steps], origin, dest)
            assert again.fare == p.fare and math.isclose(again.minutes, p.minutes)


def test_pick_budget():
    net, tariffs, pts = random_net(3)
    origin, dest, local, lb = query(net, pts, 3)
    front = Searcher(net, tariffs).search(DEPARTS[0], origin, dest, local, lb)
    assert pick(front, 0).entry is None
    for p in front:
        assert pick(front, p.fare).minutes <= p.minutes


# ---------------------------------------------------------------- Codex レビュー r01 の反例


def tiny(nodes, edges):
    net = Network()
    for nid, enter, exit_ in nodes:
        net.add_node(Node(nid, nid, 0, 0, can_enter=enter, can_exit=exit_))
    for e in edges:
        net.add_edge(e)
    return net


def front_of(net, depart, origin, dest, local, tariffs=None):
    tariffs = tariffs or default_tariffs()
    got = Searcher(net, tariffs).search(depart, origin, dest, local)
    truth = brute_force(net, tariffs, depart, origin, dest, local)
    assert [(p.minutes, p.fare) for p in got] == [(p.minutes, p.fare) for p in truth]
    for plan in got:
        if plan.entry is not None:
            assert plan == evaluate(net, tariffs, depart, plan.entry, [s.edge for s in plan.steps], origin, dest)
    return got


def aq(u, v, t, gate=None):
    return Edge(u, v, "aqualine", "アクアライン", 1.0, t, tollgate=gate, direction="up")


def test_r01_tollgate_fares_already_fixed():
    """合流点で、料金所を 19 時前に通った経路（1,600 円）が 19 時以降の経路（800 円）を捨ててはいけない。"""
    # B と C の先で M に合流し、同じ方向（M）から X に入る（来た方向が同じなので同じグループで比べられる）
    net = tiny([("A", True, False), ("B", False, False), ("C", False, False), ("M", False, False), ("X", False, True)],
               [aq("A", "B", 1), aq("B", "M", 3, "g1"), aq("A", "C", 2), aq("C", "M", 3, "g2"), aq("M", "X", 1)])
    got = front_of(net, datetime(2026, 11, 28, 18, 58), {"A": 0}, {"X": 0}, 10)
    assert pick(got, 800).fare == 800 and pick(got, 800).entry == "A"


def test_r01_revisit_needed_to_mimic():
    """先に着いたラベルが、後のラベルの続き（すでに通った B に戻る）をまねできる必要がある。"""
    net = tiny([("S", True, False), ("B", False, False), ("C", False, False), ("M", False, False), ("Y", False, True)],
               [aq("S", "B", 1), aq("B", "M", 4), aq("S", "C", 3), aq("C", "M", 3), aq("M", "B", 1),
                aq("B", "Y", 1, "g")])
    got = front_of(net, datetime(2026, 11, 28, 18, 55), {"S": 0}, {"Y": 0}, 30)
    assert pick(got, 800).fare == 800 and pick(got, 800).entry == "S"


def test_r01_distance_classes_compared_both_ways():
    net = tiny([("A", True, False), ("B", False, True)],
               [Edge("A", "B", "nexco", "u", 10, 1, "urban", holiday_ok=False),
                Edge("A", "B", "nexco", "n", 10, 2, "normal")])
    got = front_of(net, datetime(2026, 11, 25, 12, 0), {"A": 0}, {"B": 0}, 30)
    assert [p.fare for p in got] == [490, 440, 0]


def merged_routes(pool, tail):
    return tiny(
        [("A", True, False), ("B", False, False), ("C", False, False),
         ("M", False, False), ("J", False, False), ("X", False, True)],
        [Edge(u, v, pool, pool, 10, minutes) for u, v, minutes in
         [("A", "B", 1), ("B", "M", 1), ("A", "C", 2), ("C", "M", 2), ("M", "J", 1)]] + tail,
    )


def test_shutoko_current_run_dominates_across_midnight():
    net = merged_routes("shutoko", [Edge("J", "X", "shutoko", "首都高", 10, 2)])
    tariffs = default_tariffs()
    depart = datetime(2026, 11, 27, 23, 56)
    query_args = (depart, {"A": 0}, {"X": 0}, 10)
    searcher = Searcher(net, tariffs)
    got = searcher.search(*query_args)
    assert got == brute_force(net, tariffs, *query_args)
    assert searcher.stats["pruned_dominance"] == 1
    assert got[0].minutes == 5


@pytest.mark.parametrize("declare_boundaries", [True, False])
def test_future_tollgate_keeps_cheaper_later_route(declare_boundaries):
    # 合流地点の時刻はいずれも 0 時前。料金所へは一方だけ 0 時以降に着く。
    net = merged_routes("aqualine", [])
    net.add_node(Node("K", "K", 0, 0, can_enter=False, can_exit=False))
    net.add_edge(aq("J", "K", 2))
    net.add_edge(aq("K", "X", 1, "g"))
    tariffs = default_tariffs()
    if not declare_boundaries:
        tariffs.pools["aqualine"] = TollgatePool(id="aqualine", gate_fare=aqua_gate)
    got = front_of(net, datetime(2026, 11, 27, 23, 54), {"A": 0}, {"X": 0}, 10, tariffs)
    assert [(p.minutes, p.fare) for p in got] == [(6, 800), (8, 400), (10, 0)]
    assert got[1].steps[-1].t0 == datetime(2026, 11, 28, 0, 1)


@pytest.mark.parametrize("offset, expected", [(-1, [(4, 1600), (6, 1200)]),
                                            (0, [(4, 1200)]), (1, [(4, 1200)])])
def test_future_shutoko_entry_at_revision(offset, expected):
    old_pool = "yokohama_shindo"
    net = merged_routes(old_pool, [Edge("J", "X", "shutoko", "首都高", 10, 1)])
    tariffs = default_tariffs()
    revision = datetime(2026, 10, 1, 0, 0, 1)
    tariffs.pools["shutoko"].versions = (
        OdVersion(datetime(2022, 4, 1), 30, 1600, 1600),
        OdVersion(revision, 30, 1200, 1200),
    )
    # 深夜割引を切って、毎日の境目から離れた改定時刻の前後だけを比べる。
    tariffs.pools["shutoko"].night_rate = 0
    depart = revision - timedelta(minutes=3) + timedelta(microseconds=offset)
    got = front_of(net, depart, {"A": 0}, {"X": 0}, 10, tariffs)
    assert [(p.minutes, p.fare) for p in got] == expected + [(10, 0)]


def test_bounds_keep_a_plan_at_the_exact_budget():
    net = merged_routes("aqualine", [aq("J", "X", 1, "g")])
    tariffs = default_tariffs()
    depart = datetime(2026, 11, 28, 0)
    query_args = (depart, {"A": 0}, {"X": 0}, 10)
    truth = brute_force(net, tariffs, *query_args)
    searcher = Searcher(net, tariffs)
    for budget in (399, 400):
        assert searcher.search(*query_args, budget=budget) == [p for p in truth if p.fare <= budget]
        if budget == 399:
            assert searcher.stats["pruned_budget"] == 1


def test_completed_plan_prunes_already_queued_route():
    net = tiny(
        [("A", True, False), ("B", False, False), ("C", True, False), ("X", False, True)],
        [aq("A", "X", 1, "g"), aq("A", "B", 2), aq("B", "X", 1, "g")],
    )
    tariffs = default_tariffs()
    searcher = Searcher(net, tariffs)
    args = (datetime(2026, 11, 28, 0), {"A": 0, "C": 0}, {"B": 0, "X": 2}, 10)
    assert searcher.search(*args) == brute_force(net, tariffs, *args)
    assert searcher.stats["generated"] == 4
    assert searcher.stats["pushed"] == 3
    assert searcher.stats["expanded"] == 2
    assert searcher.stats["pruned_time"] == 1
    assert searcher.stats["pruned_completed"] == 1


@pytest.mark.parametrize("seed", range(4))
def test_night_v2_matches_brute(seed):
    """見直し後の深夜割引を有効にしても、総当たりと一致する。"""
    from engine.tariffs import NightV2
    net, tariffs, pts = random_net(seed)
    tariffs.pools["nexco"].night_v2 = NightV2(effective_from=datetime(2026, 4, 1))
    origin, dest, local, lb = query(net, pts, seed)
    depart = datetime(2026, 11, 25, 21, 40)
    truth = brute_force(net, tariffs, depart, origin, dest, local, lb)
    got = Searcher(net, tariffs).search(depart, origin, dest, local, lb)
    assert [(round(p.minutes, 6), p.fare) for p in got] == [(round(p.minutes, 6), p.fare) for p in truth]


def test_label_cap_falls_back_to_approximate():
    net, tariffs, pts = random_net(2)
    origin, dest, local, lb = query(net, pts, 2)
    depart = datetime(2026, 11, 27, 23, 20)
    s = Searcher(net, tariffs)
    exact = s.search(depart, origin, dest, local, lb)
    assert s.stats["approximate"] is False
    approx = s.search(depart, origin, dest, local, lb, max_labels=3)
    assert s.stats["approximate"] is True
    assert approx[0].minutes == exact[0].minutes  # 最速は近似でも同じ
    for p in approx:  # 近似でも、報告する料金と時間は経路どおりに正しい（候補を落とすことがあるだけ）
        if p.entry:
            again = evaluate(net, tariffs, depart, p.entry, [st.edge for st in p.steps], origin, dest)
            assert again.fare == p.fare and math.isclose(again.minutes, p.minutes)
