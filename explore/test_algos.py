"""探索アルゴリズムの比較で見つけた、間違えやすい例のテスト。"""
from datetime import datetime

import pytest

from algos import algo_brute, algo_labels, algo_pair_fastest, evaluate, pick
from fares import Fares
from model import Edge, Network, Node, Query


def line_net():
    """a から y へ: 速くて高い metro 直通と、遅くて安い nexco 迂回。"""
    net = Network()
    for nid, x in [("a", 0), ("m", 10), ("y", 20)]:
        net.add_node(Node(nid, x, 0))
    net.add_node(Node("j", 10, 3, False, False))
    net.add_edge(Edge("a", "y", "metro", 20, 15))  # 速いが上限近くまで高い
    net.add_edge(Edge("a", "j", "nexco", 11, 9, "normal"))
    net.add_edge(Edge("j", "y", "nexco", 11, 9, "normal"))
    return net


def test_fastest_only_misses_cheaper_path():
    net = line_net()
    fares = Fares(net)
    q = Query(0, 0, 20, 0, datetime(2026, 11, 25, 12, 0))
    fast = evaluate(net, fares, q, "a", [e for e in net.out["a"] if e.v == "y"], "y")
    cheap_budget = fast.fare - 1
    best_c = pick(algo_labels(net, fares, q), cheap_budget)
    best_a = pick(algo_pair_fastest(net, fares, q), cheap_budget)
    assert best_c.entry == "a" and best_c.fare <= cheap_budget
    assert best_a.entry is None  # A は高速を諦めて一般道だけになる
    assert best_c.minutes < best_a.minutes


def night_net():
    """X までの 2 経路: 速くて短い経路と、遅くて少し長い経路。どちらも nexco。"""
    net = Network()
    net.add_node(Node("a", 0, 0, True, False))
    net.add_node(Node("x", 10, 0, False, False))
    net.add_node(Node("m", 5, 2, False, False))
    net.add_node(Node("y", 15, 0, False, True))
    net.add_edge(Edge("a", "x", "nexco", 10, 10, "normal"))
    net.add_edge(Edge("a", "m", "nexco", 6, 9, "normal"))
    net.add_edge(Edge("m", "x", "nexco", 6, 9, "normal"))
    net.add_edge(Edge("x", "y", "nexco", 5, 5, "normal"))
    return net


@pytest.mark.parametrize("depart", [datetime(2026, 11, 25, 23, 40), datetime(2026, 11, 27, 23, 40)])
def test_labels_match_brute_across_midnight(depart):
    """0 時をまたぐと、遅い経路のほうが深夜割引（金曜→土曜は休日割引も）で安くなる。"""
    net = night_net()
    fares = Fares(net)
    q = Query(0, 0, 15, 0, depart)
    truth = algo_brute(net, fares, q)
    got = algo_labels(net, fares, q)
    assert [p.key() for p in got] == [p.key() for p in truth]
    assert len(truth) == 3  # 一般道だけ・速い経路・遅いが安い経路


def test_metro_fare_independent_of_path():
    net = Network()
    for nid, x, y in [("a", 0, 0), ("b", 10, 0), ("c", 5, 5)]:
        net.add_node(Node(nid, x, y))
    net.add_edge(Edge("a", "b", "metro", 10, 12))
    net.add_edge(Edge("a", "c", "metro", 7, 8))
    net.add_edge(Edge("c", "b", "metro", 7, 8))
    fares = Fares(net)
    q = Query(0, 0, 10, 0, datetime(2026, 11, 25, 12, 0))
    direct = evaluate(net, fares, q, "a", [e for e in net.out["a"] if e.v == "b"], "b")
    detour = evaluate(net, fares, q, "a",
                      [next(e for e in net.out["a"] if e.v == "c"), next(e for e in net.out["c"] if e.v == "b")], "b")
    assert direct.fare == detour.fare


def test_holiday_discount_only_on_normal_section():
    net = Network()
    for nid, x in [("a", 0), ("b", 30), ("c", 60)]:
        net.add_node(Node(nid, x, 0))
    net.add_edge(Edge("a", "b", "nexco", 30, 20, "urban"))
    net.add_edge(Edge("b", "c", "nexco", 30, 20, "normal"))
    fares = Fares(net)
    path = [next(e for e in net.out["a"] if e.v == "b"), next(e for e in net.out["b"] if e.v == "c")]
    weekday = evaluate(net, fares, Query(0, 0, 60, 0, datetime(2026, 11, 25, 12)), "a", path, "c").fare
    saturday = evaluate(net, fares, Query(0, 0, 60, 0, datetime(2026, 11, 28, 12)), "a", path, "c").fare
    normal_part = round(24.6 * 30 * 1.1 * 0.3)
    assert weekday - saturday == normal_part
