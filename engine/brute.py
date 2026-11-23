"""検証用: 経路を正確に計算する関数と、すべての経路を調べる総当たり（小さい道路網専用）。

経路の約束は探索（search.py）と同じ: その場での U ターンと、入口 = 出口のランは禁止。ほかの再訪は認める。
"""
from __future__ import annotations

from datetime import datetime, timedelta

from .model import Edge, Network
from .search import Plan, allowed, pareto
from .tariffs import Step, Tariffs


def evaluate(net: Network, tariffs: Tariffs, depart: datetime, entry: str, edges: list[Edge],
             origin_min: dict[str, float], dest_min: dict[str, float]) -> Plan:
    t = origin_min[entry]
    steps: list[Step] = []
    for e in edges:
        t0 = depart + timedelta(minutes=t)
        t += e.time_min
        steps.append(Step(e, t0, depart + timedelta(minutes=t)))
    runs, fare = [], 0
    i, node = 0, entry
    while i < len(steps):
        j = i
        while j < len(steps) and steps[j].edge.pool == steps[i].edge.pool:
            j += 1
        rf = tariffs.run_fare(net, node, steps[j - 1].edge.v, steps[i:j])
        runs.append(rf)
        fare += rf.fare
        node = steps[j - 1].edge.v
        i = j
    exit_ = edges[-1].v
    return Plan(t + dest_min[exit_], fare, entry, exit_, tuple(steps), tuple(runs))


def brute_force(net: Network, tariffs: Tariffs, depart: datetime, origin_min, dest_min, local_only_min,
                lower_bound_min=None) -> list[Plan]:
    lb = lower_bound_min or {}
    plans = [Plan(local_only_min, 0, None, None)]
    for a, m in origin_min.items():
        if not net.nodes[a].can_enter:
            continue
        # (ノード, 時刻, 区間の列, 今のランの入口)
        stack = [(a, m, [], a)]
        while stack:
            u, t, edges, r_entry = stack.pop()
            last = edges[-1] if edges else None
            node = net.nodes[u]
            if last is not None and u != r_entry and u in dest_min and node.can_exit and node.permits_exit_from(last.u):
                plans.append(evaluate(net, tariffs, depart, a, edges, origin_min, dest_min))
            for e in net.out[u]:
                if last is None and not node.permits_entry_towards(e.v):
                    continue
                if not allowed(last, e):
                    continue
                nt = t + e.time_min
                if nt + lb.get(e.v, 0.0) > local_only_min:
                    continue
                if last is not None and e.pool != last.pool:
                    if u == r_entry:
                        continue
                    stack.append((e.v, nt, edges + [e], u))
                else:
                    stack.append((e.v, nt, edges + [e], r_entry))
    return pareto(plans)
