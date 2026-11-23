"""予算内で最速のルートを探すアルゴリズムの候補。

どの方法も「(所要時間, 料金) のパレート集合」を返す。予算 B の答えは、
料金 <= B の中で所要時間が最小のもの（pick() で取り出す）。

- algo_pair_fastest (A): 乗る IC と降りる IC の組ごとに、最速の経路だけを見る。
- algo_pair_kpaths  (B): 組ごとに、速い順に上位 k 本の経路を見る（Yen の方法）。
- algo_labels       (C): 料金と時間の両方で優劣を付けながら探索する（多目的ラベル法）。
- algo_brute        (F): すべての単純経路を調べる（正解を求めるための総当たり）。
"""
from __future__ import annotations

import heapq
import itertools
import math
from dataclasses import dataclass

from datetime import timedelta

from fares import BOUNDARY_HOURS, Fares, Run, aqua_factor, is_holiday, overlaps_night
from model import Edge, Network, Query, at, local_minutes

MAX_HW_SPEED_KMH = 100.0


@dataclass(frozen=True)
class Plan:
    minutes: float
    fare: int
    entry: str | None
    exit: str | None
    edges: tuple[Edge, ...] = ()

    def key(self):
        return (round(self.minutes, 6), self.fare)


def pareto(plans: list[Plan]) -> list[Plan]:
    """所要時間の昇順に並べ、料金が真に下がるものだけを残す。"""
    out: list[Plan] = []
    best_fare = math.inf
    for p in sorted(plans, key=lambda p: (p.minutes, p.fare)):
        if p.fare < best_fare:
            out.append(p)
            best_fare = p.fare
    return out


def pick(front: list[Plan], budget: int) -> Plan:
    ok = [p for p in front if p.fare <= budget]
    return min(ok, key=lambda p: (p.minutes, p.fare))


# ---------------------------------------------------------------- 共通部品


def local_only(q: Query) -> Plan:
    return Plan(local_minutes(q.ox, q.oy, q.dx, q.dy), 0, None, None)


def candidates(net: Network, q: Query, max_candidates: int | None):
    ent = [n for n in net.nodes.values() if n.can_enter]
    ext = [n for n in net.nodes.values() if n.can_exit]
    ent.sort(key=lambda n: local_minutes(q.ox, q.oy, n.x, n.y))
    ext.sort(key=lambda n: local_minutes(n.x, n.y, q.dx, q.dy))
    if max_candidates:
        ent, ext = ent[:max_candidates], ext[:max_candidates]
    return ent, ext


def evaluate(net: Network, fares: Fares, q: Query, entry: str, edges, exit_: str) -> Plan:
    """経路を実際に走ったとして、所要時間と料金を正確に計算する。"""
    n0 = net.nodes[entry]
    t = local_minutes(q.ox, q.oy, n0.x, n0.y)
    fare = 0
    run = None  # [group, entry, t_in, {class: km}, flat]
    node = entry
    for e in edges:
        if run is None or run[0] != e.operator:
            if run is not None:
                fare += fares.run_fare(_close(run, node, t, q))
            run = [e.operator, node, t, {}, 0]
        run[3][e.fare_class] = run[3].get(e.fare_class, 0.0) + e.dist_km
        run[4] += e.flat_yen
        t += e.time_min
        node = e.v
    if run is not None:
        fare += fares.run_fare(_close(run, node, t, q))
    n1 = net.nodes[exit_]
    t += local_minutes(n1.x, n1.y, q.dx, q.dy)
    return Plan(t, fare, entry, exit_, tuple(edges))


def _close(run, exit_node, t, q) -> Run:
    group, entry, t_in, dist, flat = run
    return Run(group, entry, exit_node, tuple(sorted(dist.items())), flat, at(q.depart, t_in), at(q.depart, t))


def dijkstra_time(net: Network, src: str, banned_edges=frozenset(), banned_nodes=frozenset()):
    dist = {src: 0.0}
    prev: dict[str, Edge] = {}
    pq = [(0.0, src)]
    while pq:
        d, u = heapq.heappop(pq)
        if d > dist[u]:
            continue
        for e in net.out[u]:
            if (e.u, e.v, e.operator) in banned_edges or e.v in banned_nodes:
                continue
            nd = d + e.time_min
            if nd < dist.get(e.v, math.inf):
                dist[e.v] = nd
                prev[e.v] = e
                heapq.heappush(pq, (nd, e.v))
    return dist, prev


def path_to(prev, src, dst):
    edges = []
    v = dst
    while v != src:
        e = prev[v]
        edges.append(e)
        v = e.u
    return edges[::-1]


# ---------------------------------------------------------------- A


def algo_pair_fastest(net, fares, q, max_candidates=None):
    ent, ext = candidates(net, q, max_candidates)
    plans = [local_only(q)]
    for a in ent:
        dist, prev = dijkstra_time(net, a.id)
        for b in ext:
            if b.id == a.id or b.id not in dist:
                continue
            plans.append(evaluate(net, fares, q, a.id, path_to(prev, a.id, b.id), b.id))
    return pareto(plans)


# ---------------------------------------------------------------- B


def yen(net, src, dst, k):
    dist, prev = dijkstra_time(net, src)
    if dst not in dist:
        return []
    paths = [path_to(prev, src, dst)]
    cand = []
    seen = {tuple(paths[0])}
    for _ in range(1, k):
        last = paths[-1]
        for i in range(len(last)):
            spur = last[i].u
            root = last[:i]
            banned_e = set()
            for p in paths:
                if p[:i] == root and len(p) > i:
                    banned_e.add((p[i].u, p[i].v, p[i].operator))
            banned_n = {e.u for e in root}
            d2, p2 = dijkstra_time(net, spur, frozenset(banned_e), frozenset(banned_n))
            if dst not in d2:
                continue
            full = root + path_to(p2, spur, dst)
            tf = tuple(full)
            if tf in seen:
                continue
            seen.add(tf)
            heapq.heappush(cand, (sum(e.time_min for e in full), next(_tie), full))
        if not cand:
            break
        paths.append(heapq.heappop(cand)[2])
    return paths


_tie = itertools.count()


def algo_pair_kpaths(net, fares, q, max_candidates=None, k=5):
    ent, ext = candidates(net, q, max_candidates)
    plans = [local_only(q)]
    for a in ent:
        for b in ext:
            if a.id == b.id:
                continue
            for p in yen(net, a.id, b.id, k):
                plans.append(evaluate(net, fares, q, a.id, p, b.id))
    return pareto(plans)


# ---------------------------------------------------------------- C


@dataclass
class Label:
    node: str
    t: float
    closed: int
    group: str | None
    r_entry: str | None
    r_tin: float
    dn: float  # normal km in run
    du: float  # urban km in run
    flat: int
    entry: str
    parent: "Label | None"
    edge: Edge | None
    alive: bool = True


def _bucket(lab: Label, q: Query):
    if lab.group is None:
        return (lab.node, None)
    tin = at(q.depart, lab.r_tin)
    now = at(q.depart, lab.t)
    if lab.group == "nexco":
        disc = (is_holiday(tin.date()), overlaps_night(tin, now))
    elif lab.group == "aqua":
        disc = aqua_factor(tin)
    else:
        disc = None
    return (lab.node, lab.group, lab.r_entry, disc)


def _dominates(a: Label, b: Label) -> bool:
    return (
        a.t <= b.t + 1e-9
        and a.closed <= b.closed
        and a.dn <= b.dn + 1e-9
        and a.du <= b.du + 1e-9
        and a.flat <= b.flat
    )


def boundary_between(t1, t2, hours) -> bool:
    """(t1, t2] の間に、料金が切り替わる時刻（hours のいずれかの正時）があるか。"""
    d = t1.replace(minute=0, second=0, microsecond=0)
    while d <= t2:
        if d > t1 and d.hour in hours:
            return True
        d += timedelta(hours=1)
    return False


def reach_minutes(net: Network, group: str) -> dict[str, float]:
    """各ノードから、group の区間の始点に着くまでの最短時間（逆向きダイクストラ）。"""
    rev: dict[str, list[Edge]] = {}
    for e in net.edges():
        rev.setdefault(e.v, []).append(e)
    dist = {e.u: 0.0 for e in net.edges() if e.operator == group}
    pq = [(0.0, n) for n in dist]
    heapq.heapify(pq)
    while pq:
        d, v = heapq.heappop(pq)
        if d > dist[v]:
            continue
        for e in rev.get(v, []):
            nd = d + e.time_min
            if nd < dist.get(e.u, math.inf):
                dist[e.u] = nd
                heapq.heappush(pq, (nd, e.u))
    return dist


def _edges_of(lab: Label):
    out = []
    while lab.edge is not None:
        out.append(lab.edge)
        lab = lab.parent
    return out[::-1]


def algo_labels(net, fares, q, max_candidates=None, budget=None):
    ent, ext = candidates(net, q, max_candidates)
    ext_ids = {n.id for n in ext}
    lo = local_only(q)
    finals = [lo]
    lb = {
        nid: math.hypot(n.x - q.dx, n.y - q.dy) / MAX_HW_SPEED_KMH * 60.0 for nid, n in net.nodes.items()
    }
    buckets: dict[tuple, list[Label]] = {}
    pq = []
    groups = {e.operator for e in net.edges()}
    reach = {g: reach_minutes(net, g) for g in BOUNDARY_HOURS if g in groups}

    def safe_dominates(a: Label, b: Label) -> bool:
        """a が b より早くて安くても、料金が切り替わる時刻をまたぐ可能性があれば捨てない。"""
        if not _dominates(a, b):
            return False
        if abs(a.t - b.t) < 1e-9:
            return True
        late = max(a.t, b.t)
        horizon = lo.minutes - late
        t1 = at(q.depart, min(a.t, b.t))
        t2 = at(q.depart, late + horizon)
        for g, hours in BOUNDARY_HOURS.items():
            if g not in reach:
                continue
            relevant = a.group == g or b.group == g or reach[g].get(b.node, math.inf) <= horizon
            if relevant and boundary_between(t1, t2, hours):
                return False
        return True

    def push(lab: Label):
        if lab.t + lb[lab.node] > lo.minutes:
            return
        if budget is not None and lab.closed > budget:
            return
        key = _bucket(lab, q)
        lst = buckets.setdefault(key, [])
        for o in lst:
            if o.alive and safe_dominates(o, lab):
                return
        for o in lst:
            if o.alive and safe_dominates(lab, o):
                o.alive = False
        lst[:] = [o for o in lst if o.alive]
        lst.append(lab)
        heapq.heappush(pq, (lab.t, next(_tie), lab))

    for a in ent:
        t0 = local_minutes(q.ox, q.oy, a.x, a.y)
        push(Label(a.id, t0, 0, None, None, t0, 0.0, 0.0, 0, a.id, None, None))

    def close(lab: Label) -> int:
        dist = []
        if lab.dn:
            dist.append(("normal", lab.dn))
        if lab.du:
            dist.append(("urban", lab.du))
        run = Run(lab.group, lab.r_entry, lab.node, tuple(dist), lab.flat, at(q.depart, lab.r_tin), at(q.depart, lab.t))
        return fares.run_fare(run)

    while pq:
        _, _, lab = heapq.heappop(pq)
        if not lab.alive:
            continue
        if lab.group is not None and lab.node in ext_ids:
            n = net.nodes[lab.node]
            total = lab.t + local_minutes(n.x, n.y, q.dx, q.dy)
            finals.append(Plan(total, lab.closed + close(lab), lab.entry, lab.node, tuple(_edges_of(lab))))
        for e in net.out[lab.node]:
            if lab.group == e.operator:
                nl = Label(e.v, lab.t + e.time_min, lab.closed, lab.group, lab.r_entry, lab.r_tin,
                           lab.dn + (e.dist_km if e.fare_class == "normal" else 0.0),
                           lab.du + (e.dist_km if e.fare_class == "urban" else 0.0),
                           lab.flat + e.flat_yen, lab.entry, lab, e)
            else:
                closed = lab.closed + (close(lab) if lab.group is not None else 0)
                nl = Label(e.v, lab.t + e.time_min, closed, e.operator, lab.node, lab.t,
                           e.dist_km if e.fare_class == "normal" else 0.0,
                           e.dist_km if e.fare_class == "urban" else 0.0,
                           e.flat_yen, lab.entry, lab, e)
            if e.operator == "metro":  # 起終点で決まるので距離は比較に使わない
                nl.dn = nl.du = 0.0
            push(nl)
    return pareto(finals)


# ---------------------------------------------------------------- F


def algo_brute(net, fares, q, max_candidates=None):
    ent, ext = candidates(net, q, max_candidates)
    ext_ids = {n.id for n in ext}
    lo = local_only(q)
    plans = [lo]
    lb = {nid: math.hypot(n.x - q.dx, n.y - q.dy) / MAX_HW_SPEED_KMH * 60.0 for nid, n in net.nodes.items()}

    for a in ent:
        t0 = local_minutes(q.ox, q.oy, a.x, a.y)
        stack = [(a.id, t0, [a.id], [])]
        while stack:
            u, t, visited, edges = stack.pop()
            if edges and u in ext_ids:
                plans.append(evaluate(net, fares, q, a.id, edges, u))
            for e in net.out[u]:
                if e.v in visited:
                    continue
                nt = t + e.time_min
                if nt + lb[e.v] > lo.minutes:
                    continue
                stack.append((e.v, nt, visited + [e.v], edges + [e]))
    return pareto(plans)


ALGOS = {
    "A_pair_fastest": algo_pair_fastest,
    "B_pair_k5": algo_pair_kpaths,
    "C_labels": algo_labels,
    "F_brute": algo_brute,
}
