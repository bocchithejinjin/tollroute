"""厳密探索の下限・完成案・局所化した境界判定を、総当たり（engine/brute.py）と照合する。

docs/exact-search-design.md の「4. 実装順と検証」に対応するテスト。
時刻は 1/4 分刻みなど 2 進で正確に表せる値で作り、境界の比較に丸めを挟まない。
"""
import math
import random
from datetime import datetime, timedelta

import pytest

from engine.brute import brute_force, evaluate
from engine.model import Edge, Network, Node
from engine.search import Searcher, _reverse_distances, allowed
from engine.tariffs import OdTablePool, OdVersion, default_tariffs

from .test_search import aq, merged_routes, tiny


def assert_same_front(net, tariffs, depart, origin, dest, local, lb=None, budget=None):
    searcher = Searcher(net, tariffs)
    got = searcher.search(depart, origin, dest, local, lb, budget=budget)
    truth = [p for p in brute_force(net, tariffs, depart, origin, dest, local, lb)
             if budget is None or p.fare <= budget]
    assert [(p.minutes, p.fare) for p in got] == [(p.minutes, p.fare) for p in truth]
    for plan in got:  # 報告した経路を計算し直しても同じ時間・料金になる
        if plan.entry is not None:
            again = evaluate(net, tariffs, depart, plan.entry, [s.edge for s in plan.steps], origin, dest)
            assert (again.minutes, again.fare) == (plan.minutes, plan.fare)
    return got, searcher.stats


# ---------------------------------------------------------------- 料金プールを混ぜた小規模乱数網


def mixed_net(seed, n=12):
    """首都高・アクアライン（料金所あり／なし）・横浜新道・料金表・NEXCO を混ぜた網。区間時間は 1/4 分刻み。"""
    rnd = random.Random(seed)
    pts = [(rnd.uniform(0, 50), rnd.uniform(0, 50)) for _ in range(n)]
    net = Network()
    for i, (x, y) in enumerate(pts):
        r = rnd.random()
        net.add_node(Node(f"n{i}", f"n{i}", y, x, can_enter=r > 0.2, can_exit=r > 0.2 or r < 0.1))
    pairs = set()
    for i in range(n):
        near = sorted(range(n), key=lambda j: math.dist(pts[i], pts[j]))[1:4]
        pairs |= {tuple(sorted((i, j))) for j in near}
    table_nodes = set()
    for i, j in sorted(pairs):
        d = round(math.dist(pts[i], pts[j]) * 1.1, 1)
        pool = rnd.choice(["shutoko", "shutoko", "aqualine", "aqualine", "yokohama_shindo", "table", "nexco"])
        minutes = max(1, round(d * rnd.uniform(1.0, 1.4) * 4) / 4)
        spec = dict(pool=pool, road=pool, dist_km=d, time_min=minutes)
        if pool in ("aqualine", "yokohama_shindo") and rnd.random() < 0.6:
            spec["tollgate"] = f"g{i}_{j}"
        if pool == "table":
            table_nodes |= {f"n{i}", f"n{j}"}
        for a, b, direction in ((i, j, "up"), (j, i, "down")):
            net.add_edge(Edge(f"n{a}", f"n{b}", direction=direction, **spec))
    tariffs = default_tariffs()
    nodes = sorted(table_nodes)
    tariffs.pools["table"] = OdTablePool(
        id="table", table={(a, b): 100 + 10 * rnd.randrange(30) for a in nodes for b in nodes if a < b})
    return net, tariffs, pts


def mixed_query(pts, seed):
    rnd = random.Random(seed + 500)
    i = rnd.randrange(len(pts))
    o = (pts[i][0] + rnd.uniform(-3, 3), pts[i][1] + rnd.uniform(-3, 3))
    while True:
        d = (rnd.uniform(0, 50), rnd.uniform(0, 50))
        if math.dist(o, d) > 25:
            break
    loc = lambda p, q: round(math.dist(p, q) * 1.4 / 25 * 60 * 4) / 4
    near = lambda p: sorted(range(len(pts)), key=lambda k: math.dist(p, pts[k]))[:4]
    origin = {f"n{k}": loc(o, pts[k]) for k in near(o)}
    dest = {f"n{k}": loc(pts[k], d) for k in near(d)}
    # 区間時間は直線距離の 0.9 倍以上なので、出口候補までの直線距離から正当な下限を作れる（総当たりを速くする）
    lb = {f"n{k}": min(0.9 * math.dist(p, pts[int(x[1:])]) + m for x, m in dest.items())
          for k, p in enumerate(pts)}
    return origin, dest, loc(o, d), lb


MIXED_DEPARTS = [
    datetime(2026, 11, 28, 18, 40),  # 土曜、アクアライン 19 時の切替の前
    datetime(2026, 11, 27, 23, 40),  # 金曜の深夜（0 時・休日の開始をまたぐ）
    datetime(2026, 11, 28, 3, 40),   # 土曜の早朝（4 時・5 時）
    datetime(2026, 11, 29, 12, 40),  # 日曜、アクアライン 13 時の切替の前
    datetime(2026, 9, 30, 23, 40),   # 首都高の料金改定の前夜
    datetime(2027, 3, 31, 23, 40),   # アクアラインの時間帯別料金の終了
    datetime(2026, 11, 25, 12, 0),   # 平日の昼
]


@pytest.mark.parametrize("seed", range(12))
@pytest.mark.parametrize("depart", MIXED_DEPARTS, ids=lambda d: d.strftime("%m%d-%H%M"))
def test_mixed_pools_match_brute(seed, depart):
    net, tariffs, pts = mixed_net(seed)
    origin, dest, local, lb = mixed_query(pts, seed)
    front, _ = assert_same_front(net, tariffs, depart, origin, dest, local, lb)
    # 予算ちょうど・1 円足りない予算でも、総当たりを予算で絞ったものと一致する
    for budget in sorted({p.fare for p in front} | {p.fare - 1 for p in front if p.fare}):
        assert_same_front(net, tariffs, depart, origin, dest, local, lb, budget)


# ---------------------------------------------------------------- 下限が実値を上回らない


def all_plans(net, tariffs, depart, origin, dest, local):
    """総当たりと同じ規則で、T 以内に着くすべての合法な経路を返す（パレートで絞らない）。"""
    plans = []
    for a, m in origin.items():
        if not net.nodes[a].can_enter:
            continue
        stack = [(a, m, [], a)]
        while stack:
            u, t, edges, r_entry = stack.pop()
            if edges and u != r_entry and u in dest and net.nodes[u].can_exit:
                plans.append(evaluate(net, tariffs, depart, a, edges, origin, dest))
            last = edges[-1] if edges else None
            for e in net.out[u]:
                if not allowed(last, e) or t + e.time_min > local:
                    continue
                if last is not None and e.pool != last.pool:
                    if u == r_entry:
                        continue
                    stack.append((e.v, t + e.time_min, edges + [e], u))
                else:
                    stack.append((e.v, t + e.time_min, edges + [e], r_entry))
    return plans


@pytest.mark.parametrize("seed", [0, 1, 4, 7, 9, 11])
def test_lower_bounds_never_exceed_actual_continuations(seed):
    net, tariffs, pts = mixed_net(seed)
    origin, dest, local, _ = mixed_query(pts, seed)
    depart = MIXED_DEPARTS[0]
    searcher = Searcher(net, tariffs)
    exits = {n: m for n, m in dest.items() if net.nodes[n].can_exit}
    h = _reverse_distances(searcher.reverse_time, exits, time=True)
    gate_lb = _reverse_distances(searcher.reverse_fare, dict.fromkeys(exits, 0))
    plans = all_plans(net, tariffs, depart, origin, dest, local)
    assert plans
    for plan in plans:
        t = origin[plan.entry]
        nodes = [plan.entry] + [s.edge.v for s in plan.steps]
        times = [t]
        for s in plan.steps:
            t += s.edge.time_min
            times.append(t)
        gates = [tariffs.pools[s.edge.pool].gate_fare_at(s.edge, s.t0) if tariffs.pools[s.edge.pool].per_gate else 0
                 for s in plan.steps]
        for k, node in enumerate(nodes):
            assert times[k] + h[node] <= plan.minutes  # 時間下限
            assert gate_lb[node] <= sum(gates[k:])  # これから通る料金所の下限


# ---------------------------------------------------------------- 首都高の同一ランは 0 時・改定をまたいでも支配できる


def shutoko_with_far_nexco(depart_minutes=0):
    """A→B→M（2 分）と A→C→M（4 分）の首都高ランが M で合流する。NEXCO は T 以内に届かない先にだけある。"""
    net = merged_routes("shutoko", [Edge("J", "X", "shutoko", "首都高", 10, 2)])
    net.add_node(Node("Z", "Z", 0, 0, can_enter=False, can_exit=False))
    net.add_node(Node("W", "W", 0, 0, can_enter=False, can_exit=True))
    net.add_edge(Edge("X", "Z", "shutoko", "首都高", 10, 20))
    net.add_edge(Edge("Z", "W", "nexco", "NEXCO", 10, 5))
    return net


@pytest.mark.parametrize("depart", [datetime(2026, 11, 27, 23, 57), datetime(2026, 11, 28, 3, 57)],
                         ids=["midnight", "4am"])
def test_shutoko_run_across_boundary_dominates_with_unreachable_nexco(depart):
    """M に 23:59 と 0:01（または 3:59 と 4:01）に着く。入口が同じなので、0 時・4 時をまたいでも早い方が支配する。"""
    net = shutoko_with_far_nexco()
    got, stats = assert_same_front(net, default_tariffs(), depart, {"A": 0}, {"X": 0, "W": 0}, 10)
    assert stats["pruned_dominance"] == 1
    assert [(p.minutes, p.fare) for p in got][0][0] == 5


def test_shutoko_run_with_reachable_nexco_stays_conservative():
    """NEXCO に T 以内で入れるなら、0 時をまたぐラベルは比べない（NEXCO は従来の広い判定）。"""
    net = merged_routes("shutoko", [Edge("J", "X", "shutoko", "首都高", 10, 2)])
    net.add_node(Node("Y", "Y", 0, 0, can_enter=False, can_exit=True))
    net.add_edge(Edge("J", "Y", "nexco", "NEXCO", 10, 2))
    net.add_edge(Edge("X", "Y", "nexco", "NEXCO", 10, 1))  # X からも NEXCO に入れる（行き止まりで比べられないように）
    # M に 23:58 と 0:00、J に 23:59 と 0:01 に着く。どちらで比べても間に 0 時がある。
    _, stats = assert_same_front(net, default_tariffs(), datetime(2026, 11, 27, 23, 56), {"A": 0},
                                 {"X": 0, "Y": 0}, 10)
    # M・J・X では比べない。捨てるのは、どちらも 0 時以降に X から NEXCO に入った Y のラベル 1 件だけ。
    assert stats["pruned_dominance"] == 1


REVISION = datetime(2026, 10, 1, 0, 0, 1)  # 毎日の境目と重ならない改定時刻


def revised_shutoko():
    tariffs = default_tariffs()
    tariffs.pools["shutoko"].night_rate = 0
    tariffs.pools["shutoko"].versions = (OdVersion(datetime(2022, 4, 1), 30, 1600, 1600),
                                        OdVersion(REVISION, 30, 1200, 1200))
    return tariffs


@pytest.mark.parametrize("offset", [-1, 0, 1])
@pytest.mark.parametrize("lead_minutes", [3, 0], ids=["merge-straddles", "entry-at-revision"])
def test_current_shutoko_run_dominates_across_revision(offset, lead_minutes):
    """A から首都高に入り、M に 2 分後と 4 分後に着く。

    lead_minutes=3: 入口は改定の 3 分前（±1 マイクロ秒）で、M への到着が改定をまたぐ。入口の料金版のままなので支配できる。
    lead_minutes=0: 入口が改定の直前・ちょうど・直後。料金版は入口時刻で決まる。
    """
    net = merged_routes("shutoko", [Edge("J", "X", "shutoko", "首都高", 10, 2)])
    depart = REVISION - timedelta(minutes=lead_minutes) + timedelta(microseconds=offset)
    got, stats = assert_same_front(net, revised_shutoko(), depart, {"A": 0}, {"X": 0}, 10)
    expected = 1200 if lead_minutes == 0 and offset >= 0 else 1600
    assert [(p.minutes, p.fare) for p in got] == [(5, expected), (10, 0)]
    assert stats["pruned_dominance"] == 1


# ---------------------------------------------------------------- 同じ時間帯の二ラベル、後の判定が境目を挟む


@pytest.mark.parametrize("depart, pool_tail, expected", [
    # 首都高へ J から入る。J に 23:58（深夜割引なし）と 0:00（深夜割引あり）に着く。
    (datetime(2026, 11, 27, 23, 55), "shutoko", [(4, 1590), (6, 1270)]),
    # 日曜の上りアクアライン料金所。J に 18:56 と 18:58、料金所 K に 18:58（1,600 円）と 19:00（800 円）に着く。
    (datetime(2026, 11, 29, 18, 53), "aqualine", [(6, 1600), (8, 800)]),
    # NEXCO（深夜割引の対象外の区間）へ J から入る。J に金曜 23:58 と土曜 0:00 に着き、後者だけ休日割引になる。
    (datetime(2026, 11, 27, 23, 55), "nexco", [(4, 440), (6, 350)]),
])
@pytest.mark.parametrize("slack", [4, 0.5], ids=["loose-T", "tight-T"])
def test_later_event_straddling_boundary_keeps_cheaper_route(depart, pool_tail, expected, slack):
    """M・J では同じ時間帯にいる二ラベルの、後の料金判定（入口・料金所）だけが境目を挟む。安い遅い方が残る。

    tight-T では T を遅い方の到着の 0.5 分後にして、判定時刻の上限（T − 残り時間）が過大に削られないことも確かめる。
    """
    net = merged_routes("yokohama_shindo", [])
    net.add_node(Node("K", "K", 0, 0, can_enter=False, can_exit=False))
    if pool_tail == "shutoko":
        net.add_edge(Edge("J", "X", "shutoko", "首都高", 40, 1))
    elif pool_tail == "nexco":
        net.add_edge(Edge("J", "X", "nexco", "NEXCO", 10, 1, night_ok=False))
    else:
        net.add_edge(aq("J", "K", 2))
        net.add_edge(aq("K", "X", 1, "g"))
    local = expected[-1][0] + slack
    got, _ = assert_same_front(net, default_tariffs(), depart, {"A": 0}, {"X": 0}, local)
    assert [(p.minutes, p.fare) for p in got] == expected + [(local, 0)]


# ---------------------------------------------------------------- T ちょうど・予算ちょうど


@pytest.mark.parametrize("local, expected", [
    (5.5, [(5.25, 320), (5.5, 0)]),   # T の 1/4 分前に着く経路は残る
    (5.375, [(5.25, 320), (5.375, 0)]),  # T の 1/8 分前
    (5.25, [(5.25, 0)]),              # T ちょうどに着く経路は一般道案に支配される
    (5.0, [(5.0, 0)]),
])
def test_arrival_exactly_at_local_only_time(local, expected):
    net = tiny([("A", True, False), ("B", False, False), ("X", False, True)],
               [Edge("A", "B", "yokohama_shindo", "横浜新道", 1, 2.5, tollgate="g"),
                Edge("B", "X", "yokohama_shindo", "横浜新道", 1, 1.5)])
    got, _ = assert_same_front(net, default_tariffs(), datetime(2026, 11, 25, 12), {"A": 0.75}, {"X": 0.5}, local)
    assert [(p.minutes, p.fare) for p in got] == expected


@pytest.mark.parametrize("budget", [319, 320, 640, 959, 960, None])
def test_budget_exact_with_gate_lower_bound(budget):
    """料金所 3 か所（各 320 円）の経路と 2 か所の遠回り。予算ちょうどの案は残る。"""
    net = tiny([("A", True, False), ("B", False, False), ("C", False, False), ("X", False, True)],
               [Edge("A", "B", "yokohama_shindo", "s", 1, 1, tollgate="g1"),
                Edge("B", "C", "yokohama_shindo", "s", 1, 1, tollgate="g2"),
                Edge("C", "X", "yokohama_shindo", "s", 1, 1, tollgate="g3"),
                Edge("B", "X", "yokohama_shindo", "s", 1, 4, tollgate="g4"),
                Edge("A", "C", "nexco", "n", 30, 3.5)])
    assert_same_front(net, default_tariffs(), datetime(2026, 11, 25, 12), {"A": 0}, {"X": 0}, 9, budget=budget)


def test_float_sum_order_does_not_hide_a_plan_just_before_T():
    """逆向きの下限は区間を逆順に足す。順方向の加算 (6.0 + 0.1) + 1.1 + 1/3 は、逆順に足した値より 1 ulp 小さい。

    T を順方向の到着時刻の 1 ulp 後にすると、経路は T より前に着くので残る（下限を誤差の分だけ小さく見積もる必要がある）。
    """
    net = tiny([("A", True, False), ("B", False, False), ("X", False, True)],
               [Edge("A", "B", "yokohama_shindo", "横浜新道", 1, 0.1, tollgate="g"),
                Edge("B", "X", "yokohama_shindo", "横浜新道", 1, 1.1)])
    origin, dest = {"A": 6.0}, {"X": 1 / 3}
    arrival = 6.0 + 0.1 + 1.1 + 1 / 3
    assert 6.0 + (1 / 3 + 1.1 + 0.1) > arrival  # 逆順の和の方が大きい
    local = math.nextafter(arrival, math.inf)
    got, _ = assert_same_front(net, default_tariffs(), datetime(2026, 11, 25, 12), origin, dest, local)
    assert [(p.minutes, p.fare) for p in got] == [(arrival, 320), (local, 0)]


@pytest.mark.parametrize("pool_tail, depart, generated", [
    # J から首都高に入る。J には 23:43 と 23:45 に着き、首都高の入口は T までの 0 時より十分前にしか間に合わない。
    ("shutoko", datetime(2026, 11, 27, 23, 40), 8),
    # 日曜のアクアライン料金所。料金所には 12:4x にしか間に合わず、13 時の切替は T の前だが判定範囲の外。
    ("aqualine", datetime(2026, 11, 29, 12, 40), 9),
])
def test_boundary_before_T_but_outside_event_window_allows_dominance(pool_tail, depart, generated):
    """T までに境目（0 時・13 時）はあるが、後続の料金判定が起き得る範囲には境目がない。M で早い方が支配する。

    従来の判定（境目が (A の時刻, T] にあれば比べない）では支配できなかったケース。
    """
    net = merged_routes("yokohama_shindo", [])
    if pool_tail == "shutoko":
        net.add_edge(Edge("J", "X", "shutoko", "首都高", 10, 10))
    else:
        net.add_node(Node("K", "K", 0, 0, can_enter=False, can_exit=False))
        net.add_edge(aq("J", "K", 1, "g"))
        net.add_edge(aq("K", "X", 9))
    got, stats = assert_same_front(net, default_tariffs(), depart, {"A": 0}, {"X": 0}, 25)
    assert len(got) == 2 and got[0].minutes == 13
    # M で遅い方を捨てるので、その後続（J 以降）のラベルは作られない
    assert stats["pruned_dominance"] == 1 and stats["generated"] == generated
