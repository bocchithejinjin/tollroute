"""予算内で最速のルートを探す（多目的ラベル法）。

docs/algorithm-selection.md の比較で採用した方法。所要時間と料金の両方で劣るラベルだけを捨てる。

正しさのための約束:
- 経路は「その場での U ターン」と「乗った IC でそのまま降りる（入口 = 出口のラン）」だけを禁止し、
  ほかの再訪は認める。こうすると、先に着いたラベルは後に着いたラベルの続きをそのまままねできるので、
  時刻の早さで比べても正しい（同じ IC に戻れないと、まねできないことがある）。
- 料金が切り替わる時刻（深夜割引の 0 時・4 時、アクアラインの時間帯、料金改定日など）を
  これから先にまたぐ可能性があるときは、「早く着く」ことを理由に捨てない（遅いほうが安くなることがある）。
  首都高は後続ランの入口、時刻で料金が変わる料金所は通過時刻だけを調べる（判定が起き得る時刻の範囲に
  境目がなければ比べてよい）。現行 NEXCO は後続ランの入口から終了まで、現在ランは終了までの深夜・休日判定を調べる。
  見直し後の制度が有効になり得るときは、従来の広い判定範囲を使う。
- 料金所で確定した金額（pending）と、ランの距離（区分ごと）も比べる。距離は「多いほど高い」ことが前提で、
  料金プールの側でその前提を確かめている（tariffs.NexcoPool.validate）。
- 目的地までの時間下限 h と、これから通る料金所の最低額の和を下限にして、完成案（一般道案を含む）に
  時間・料金とも及ばないラベルを捨てる。浮動小数点の加算順の違いは時間下限を誤差の分だけ小さくして吸収する。

入力の一般道の所要時間（出発地→各 IC、各 IC→目的地）は、ルート検索エンジンで求めて渡す。
"""
from __future__ import annotations

import heapq
import itertools
import math
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from datetime import datetime, timedelta
from operator import attrgetter

from .calendar import is_nexco_holiday_discount_day
from .model import Edge, Network
from .tariffs import NexcoPool, OdDistancePool, RunFare, Step, Tariffs

EPS = 1e-9


@dataclass(frozen=True)
class Plan:
    minutes: float  # 出発から到着まで
    fare: int
    entry: str | None  # None は「高速を使わない」
    exit: str | None
    steps: tuple[Step, ...] = ()
    runs: tuple[RunFare, ...] = ()


@dataclass
class _Label:
    node: str
    t: float
    closed: int  # 確定したランの料金の合計
    pending: int  # 今のランで、料金所を通って確定した金額
    runs: tuple[RunFare, ...]
    pool: str | None
    r_entry: str | None
    r_tin: float
    run_len: int
    km: tuple[tuple[tuple, float], ...]
    entry: str
    parent: "_Label | None"
    edge: Edge | None
    alive: bool = True


def pareto(plans: list[Plan]) -> list[Plan]:
    out, best = [], math.inf
    for p in sorted(plans, key=lambda p: (p.minutes, p.fare)):
        if p.fare < best:
            out.append(p)
            best = p.fare
    return out


def pick(front: list[Plan], budget: int) -> Plan:
    """予算内で所要時間が最小のプラン。front には必ず料金 0 の「高速を使わない」が入っている。"""
    return min((p for p in front if p.fare <= budget), key=lambda p: (p.minutes, p.fare))


def boundary_between(t1: datetime, t2: datetime, hours, moments=()) -> bool:
    """(t1, t2] の間に、料金が切り替わる時刻（毎日の正時 hours、または特定の日時 moments）があるか。"""
    last = _last_boundary(t2, hours, moments)
    return last is not None and t1 < last


def _last_boundary(end: datetime, hours, moments) -> datetime | None:
    last = max((m for m in moments if m <= end), default=None)
    if hours:
        hour = end.replace(minute=0, second=0, microsecond=0)
        daily = hour - timedelta(hours=min((hour.hour - h) % 24 for h in hours))
        if last is None or last < daily:
            last = daily
    return last


def allowed(lab_edge: Edge | None, e: Edge) -> bool:
    """その場での U ターン（来た区間をそのまま戻る）は禁止。"""
    return lab_edge is None or not (e.v == lab_edge.u and e.u == lab_edge.v)


def _reverse_distances(reverse, seeds, *, time=False):
    dist = dict(seeds)
    tie = itertools.count()
    pq = [(d, next(tie), node) for node, d in dist.items()]
    heapq.heapify(pq)
    while pq:
        d, _, v = heapq.heappop(pq)
        if d > dist[v]:
            continue
        for u, weight in reverse.get(v, ()):
            nd = d + weight
            if time:
                nd = max(d, math.nextafter(nd, -math.inf))
            if nd < dist.get(u, math.inf):
                dist[u] = nd
                heapq.heappush(pq, (nd, next(tie), u))
    return dist


def _forward_time_error(horizon: float, min_edge_time: float) -> float:
    # T 以内の各加算の誤差は ulp(T) 以下。区間ごとに少なくとも
    # 最短区間時間の半分だけ進む場合、その区間数から累積誤差を上から抑える。
    ulp = math.ulp(horizon)
    if min_edge_time <= 2 * ulp:
        return math.inf
    return (2 * (horizon / min_edge_time) + 2) * ulp


_plan_time = attrgetter("minutes")


class Searcher:
    def __init__(self, net: Network, tariffs: Tariffs):
        self.net = net
        self.tariffs = tariffs
        edges = list(net.edges())
        pools = {e.pool for e in edges}
        for pid in pools:
            tariffs.pools[pid].validate()
        self.timed = {
            pid: (p.boundary_hours, tuple(p.boundary_moments()))
            for pid, p in tariffs.pools.items()
            if pid in pools and (p.boundary_hours or p.boundary_moments())
        }
        self.reverse_time = {}
        self.reverse_fare = {}
        incoming_pools = {}
        for e in edges:
            self.reverse_time.setdefault(e.v, []).append((e.u, e.time_min))
            incoming_pools.setdefault(e.v, set()).add(e.pool)
            minimum = tariffs.pools[e.pool].minimum_gate_fare(e)
            self.reverse_fare.setdefault(e.v, []).append((e.u, minimum))
        self.has_gate_minimum = any(weight for links in self.reverse_fare.values() for _, weight in links)
        self.min_edge_time = min((e.time_min for e in edges), default=math.inf)

        self.reach = {}
        self.events = {}
        self.nexco = {}
        entry_events = {pid for pid in self.timed if isinstance(tariffs.pools[pid], OdDistancePool)
                        or type(tariffs.pools[pid]) is NexcoPool}
        if entry_events:
            reverse_pool = {}
            previous_pools = {node: (None, *sorted(incoming_pools.get(node, ()))) for node in net.nodes}
            for e in edges:
                reverse_pool.setdefault((e.v, e.pool), []).extend(
                    ((e.u, previous), e.time_min) for previous in previous_pools[e.u]
                )
        for pid, pool in tariffs.pools.items():
            if pid not in pools or (pid not in self.timed and (not pool.per_gate or pool.gate_time_invariant)):
                continue
            pool_edges = [e for e in edges if e.pool == pid]
            if pid in entry_events:
                seeds = {(e.u, previous): 0.0 for e in pool_edges
                         for previous in previous_pools[e.u] if previous != pid}
                entry_dist = _reverse_distances(reverse_pool, seeds, time=True)
                if type(pool) is NexcoPool:
                    run_nodes = {e.v for e in pool_edges}
                    switches = [e for node in run_nodes for e in net.out[node] if e.pool != pid]
                    self.nexco[pid] = (entry_dist, run_nodes, switches)
                else:
                    self.events[pid] = (entry_dist, pool_edges, True)
            elif pool.per_gate:
                gates = [e for e in pool_edges if e.tollgate]
                seeds = {e.u: 0.0 for e in gates}
                self.events[pid] = (_reverse_distances(self.reverse_time, seeds, time=True), gates, False)
            else:
                seeds = {e.u: 0.0 for e in pool_edges}
                self.reach[pid] = _reverse_distances(self.reverse_time, seeds, time=True)
        self.stats: dict[str, int] = {}

    def search(
        self,
        depart: datetime,
        origin_min: dict[str, float],
        dest_min: dict[str, float],
        local_only_min: float,
        lower_bound_min: dict[str, float] | None = None,
        budget: int | None = None,
        max_labels: int = 200_000,
    ) -> list[Plan]:
        """パレート集合を返す。self.stats["approximate"] が True なら近似の結果。

        正確な探索のラベル数が max_labels を超えたら、時刻の境目の扱いを簡略化した近似モードでやり直す
        （近似モードでは「早く着くほうが優れている」とみなす。境目の前後で、遅いほうが安くなる候補を落とすことがある）。
        generated、expanded、pruned_* は両方の試行を合算し、pushed と max_bucket は最後の試行を数える。
        """
        exits = {nid: m for nid, m in dest_min.items() if nid in self.net.nodes and self.net.nodes[nid].can_exit}
        h = _reverse_distances(self.reverse_time, exits, time=True)
        gate_lb = {}
        if self.has_gate_minimum:
            gate_lb = _reverse_distances(self.reverse_fare, dict.fromkeys(exits, 0))
        bounds = (h, lower_bound_min or {}, gate_lb)
        try:
            front = self._search(depart, origin_min, exits, local_only_min, bounds, budget, True, max_labels)
            self.stats["approximate"] = False
        except _TooManyLabels:
            exact_stats = self.stats
            front = self._search(depart, origin_min, exits, local_only_min, bounds, budget, False, None)
            for name in exact_stats:
                if name in ("generated", "expanded") or name.startswith("pruned_"):
                    self.stats[name] += exact_stats[name]
            self.stats["approximate"] = True
        return front

    def _search(self, depart, origin_min, dest_min, local_only_min, bounds, budget, exact, max_labels):
        net, tariffs = self.net, self.tariffs
        h, external_lb, gate_lb = bounds
        time_error = _forward_time_error(local_only_min, self.min_edge_time)
        at = lambda m: depart + timedelta(minutes=m)
        legacy_windows = {}
        event_windows = []
        nexco_closures = {}
        nexco_entries = []

        def latest_event(remaining):
            # イベント後の必要時間を下向きに丸め、イベントが起き得る時刻の上限を得る。
            remaining = math.nextafter(remaining, -math.inf)
            return min(local_only_min, math.nextafter(local_only_min - remaining + time_error, math.inf))

        if exact:
            end = at(local_only_min)
            for pid, dist in self.reach.items():
                last = _last_boundary(end, *self.timed[pid])
                if last is not None and last > depart:
                    legacy_windows[pid] = (dist, last)
            for pid, (dist, edges, by_pool) in self.events.items():
                # イベントは辺の始点で起きるので、その辺の走行も残り時間に含める。
                remaining = min((e.time_min + h.get(e.v, math.inf) for e in edges), default=math.inf)
                if math.isfinite(remaining):
                    latest = latest_event(remaining)
                    if latest >= 0:
                        boundaries = self.timed.get(pid)
                        last = _last_boundary(at(latest), *boundaries) if boundaries else None
                        # 時刻が変わるか不明な料金所では、到達可能な限り異時刻を比較しない。
                        if boundaries is None or (last is not None and last > depart):
                            event_windows.append((dist, by_pool, latest, last))
            for pid, (entry_dist, run_nodes, switches) in self.nexco.items():
                if self.tariffs.pools[pid].night_v2.active(end):
                    # 見直し後は走行時刻によって割引額が連続的に変わり得る。
                    legacy_windows[pid] = (None, end)
                    continue
                # ランが閉じるのは高速を降りるか、別の料金プールへ移るとき。
                exit_tail = min((dest_min.get(node, math.inf) for node in run_nodes), default=math.inf)
                switch_tail = min((e.time_min + h.get(e.v, math.inf) for e in switches), default=math.inf)
                remaining = min(exit_tail, switch_tail)
                if math.isinf(remaining):
                    continue
                latest = latest_event(remaining)
                if latest < 0:
                    continue
                last_close = at(latest)
                midnight = _last_boundary(last_close, (0,), ())
                holiday_change = midnight
                while holiday_change > depart and is_nexco_holiday_discount_day(holiday_change.date()) == (
                    is_nexco_holiday_discount_day((holiday_change - timedelta(days=1)).date())
                ):
                    holiday_change -= timedelta(days=1)
                nexco_closures[pid] = (midnight, holiday_change)
                last = _last_boundary(last_close, (0, 4), ())
                if last > depart:
                    nexco_entries.append((entry_dist, latest, last))
        finals = [Plan(local_only_min, 0, None, None)]
        buckets: dict[tuple, list[_Label]] = {}
        pq: list = []
        tie = itertools.count()
        stats = dict.fromkeys(("generated", "pushed", "expanded", "max_bucket", "pruned_time",
                               "pruned_budget", "pruned_completed", "pruned_dominance"), 0)
        self.stats = stats

        def steps_of(lab: _Label, n: int) -> list[Step]:
            out = []
            while n > 0:
                # 区間に入った時刻は、親ラベルの時刻をそのまま使う（引き算で戻すと誤差が出る。検算 brute と同じ値にする）
                out.append(Step(lab.edge, at(lab.parent.t), at(lab.t)))
                lab = lab.parent
                n -= 1
            return out[::-1]

        def close(lab: _Label) -> RunFare:
            return tariffs.run_fare(net, lab.r_entry, lab.node, steps_of(lab, lab.run_len))

        def key(lab: _Label):
            # 来た方向（直前のノード）も鍵に入れる。U ターン禁止で、来た方向によって進める先が変わるため
            if lab.pool is None:
                return (lab.node,)
            # 区間の一覧は、必要な料金プール（見直し後の深夜割引など）だけが呼び出して作る
            st = tariffs.pools[lab.pool].state_key(at(lab.r_tin), at(lab.t), lambda: steps_of(lab, lab.run_len))
            # 現在ランですでに成立した割引条件は、ランを延長しても消えない。
            current_window = legacy_windows.get(lab.pool)
            same_time = lab.t if current_window is not None and at(lab.t) < current_window[1] else None
            closure = nexco_closures.get(lab.pool)
            if closure is not None:
                holiday, night, _ = st
                midnight, holiday_change = closure
                now = at(lab.t)
                if (not night and now < midnight) or (not holiday and now < holiday_change):
                    same_time = lab.t
            # 境目をまたぐ後続 NEXCO ランがあり得る間は、異時刻の比較でバケットを膨らませない。
            if same_time is None and nexco_entries:
                position = (lab.node, lab.pool)
                for dist, latest, last in nexco_entries:
                    earliest = time_lower(lab.t, dist.get(position, math.inf))
                    if earliest <= latest and at(earliest) < last:
                        same_time = lab.t
                        break
            return (lab.node, lab.edge.u, lab.pool, lab.r_entry, st, same_time)

        def dominates(a: _Label, b: _Label) -> bool:
            if a.t > b.t + (0 if exact else EPS) or a.closed + a.pending > b.closed + b.pending:
                return False
            # 厳密モードでは距離も誤差を許さずに比べる（わずかに長い距離で料金の丸めが変わり得るため）
            tol = 0.0 if exact else EPS
            bk = dict(b.km)
            for k, v in a.km:
                if v > bk.get(k, 0.0) + tol:
                    return False
            if a.t == b.t or not exact:
                return True
            for pid, (dist, last) in legacy_windows.items():
                distance = (dist.get(b.node, math.inf) if dist is not None
                            else self.nexco[pid][0].get((b.node, b.pool), math.inf))
                if (a.pool == pid or time_lower(b.t, distance) <= local_only_min) and at(a.t) < last:
                    return False
            for dist, by_pool, latest, last in event_windows:
                position = (b.node, b.pool) if by_pool else b.node
                distance = dist.get(position, math.inf)
                if time_lower(b.t, distance) <= latest and (last is None or at(time_lower(a.t, distance)) < last):
                    return False
            return True

        def time_lower(t, remaining):
            if math.isinf(remaining):
                return remaining
            start_plus_remaining = math.nextafter(t + remaining, -math.inf)
            return max(t, math.nextafter(start_plus_remaining - time_error, -math.inf))

        def covered(t, fare):
            i = bisect_right(finals, t, key=_plan_time)
            return i > 0 and finals[i - 1].fare <= fare

        def pruned(t, fare):
            if t > local_only_min:
                stats["pruned_time"] += 1
            elif budget is not None and fare > budget:
                stats["pruned_budget"] += 1
            elif covered(t, fare):
                stats["pruned_completed"] += 1
            else:
                return False
            return True

        def push(lab: _Label):
            stats["generated"] += 1
            remaining = max(h.get(lab.node, math.inf), external_lb.get(lab.node, 0.0))
            t = time_lower(lab.t, remaining)
            fare = lab.closed + lab.pending + gate_lb.get(lab.node, 0)
            if pruned(t, fare):
                return
            lst = buckets.setdefault(key(lab), [])
            if any(o.alive and dominates(o, lab) for o in lst):
                stats["pruned_dominance"] += 1
                return
            for o in lst:
                if o.alive and dominates(lab, o):
                    o.alive = False
                    stats["pruned_dominance"] += 1
            lst[:] = [o for o in lst if o.alive]
            lst.append(lab)
            stats["pushed"] += 1
            if max_labels is not None and stats["pushed"] > max_labels:
                raise _TooManyLabels
            stats["max_bucket"] = max(stats["max_bucket"], len(lst))
            heapq.heappush(pq, (t, next(tie), fare, lab))

        for nid, m in origin_min.items():
            if nid in net.nodes and net.nodes[nid].can_enter:
                push(_Label(nid, m, 0, 0, (), None, None, m, 0, (), nid, None, None))

        while pq:
            t, _, fare, lab = heapq.heappop(pq)
            if not lab.alive or pruned(t, fare):
                continue
            stats["expanded"] += 1
            can_close = lab.pool is not None and lab.node != lab.r_entry
            rf = None
            if can_close and lab.node in dest_min:
                rf = close(lab)
                arrival, cost = lab.t + dest_min[lab.node], lab.closed + rf.fare
                if (budget is None or cost <= budget) and not covered(arrival, cost):
                    i = j = bisect_left(finals, arrival, key=_plan_time)
                    while j < len(finals) and finals[j].fare >= cost:
                        j += 1
                    finals[i:j] = [Plan(arrival, cost, lab.entry, lab.node,
                                        tuple(steps_of(lab, _depth(lab))), lab.runs + (rf,))]
            for e in net.out[lab.node]:
                if not allowed(lab.edge, e):
                    continue
                pool = tariffs.pools[e.pool]
                kk = (e.fare_class, e.holiday_ok, e.night_ok)
                gate = pool.gate_fare_at(e, at(lab.t)) if pool.per_gate else 0
                if lab.pool == e.pool:
                    km = dict(lab.km)
                    if pool.distance_matters:
                        km[kk] = km.get(kk, 0.0) + e.dist_km
                    nl = _Label(e.v, lab.t + e.time_min, lab.closed, lab.pending + gate, lab.runs, lab.pool,
                                lab.r_entry, lab.r_tin, lab.run_len + 1, tuple(sorted(km.items())), lab.entry, lab, e)
                else:
                    closed, runs = lab.closed, lab.runs
                    if lab.pool is not None:
                        if not can_close:  # 入口 = 出口のランは作れない
                            continue
                        if rf is None:
                            rf = close(lab)
                        closed, runs = closed + rf.fare, runs + (rf,)
                    km = ((kk, e.dist_km),) if pool.distance_matters else ()
                    nl = _Label(e.v, lab.t + e.time_min, closed, gate, runs, e.pool, lab.node, lab.t, 1, km,
                                lab.entry, lab, e)
                push(nl)
        return finals


class _TooManyLabels(Exception):
    pass


def _depth(lab: _Label) -> int:
    n = 0
    while lab.edge is not None:
        n += 1
        lab = lab.parent
    return n
