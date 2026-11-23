"""本番エンジン（engine/）の性能測定。全国規模に近い架空の道路網で、時間・ラベル数・メモリを測る。

使い方: python explore/scale_engine.py [ノード数...]
"""
from __future__ import annotations

import math
import random
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.model import Edge, Network, Node  # noqa: E402
from engine.search import Searcher  # noqa: E402
from engine.tariffs import default_tariffs  # noqa: E402

SIZE = 400.0  # km 四方（関東〜東海くらいの広さ）


def make(n: int, seed: int):
    rnd = random.Random(seed)
    pts = []
    while len(pts) < n:
        p = (rnd.uniform(0, SIZE), rnd.uniform(0, SIZE))
        if all(math.dist(p, q) > 3 for q in pts[-200:]):
            pts.append(p)
    net = Network()
    for i, (x, y) in enumerate(pts):
        jct = rnd.random() < 0.15
        net.add_node(Node(f"n{i}", f"n{i}", y, x, can_enter=not jct, can_exit=not jct))
    # 格子に分けて近傍を探す（n が大きいので）
    cell = 15.0
    grid: dict[tuple[int, int], list[int]] = {}
    for i, (x, y) in enumerate(pts):
        grid.setdefault((int(x // cell), int(y // cell)), []).append(i)
    pairs = set()
    for i, (x, y) in enumerate(pts):
        cx, cy = int(x // cell), int(y // cell)
        near = [j for dx in (-1, 0, 1) for dy in (-1, 0, 1) for j in grid.get((cx + dx, cy + dy), []) if j != i]
        near.sort(key=lambda j: math.dist(pts[i], pts[j]))
        for j in near[:3]:
            pairs.add(tuple(sorted((i, j))))
    # 全体を連結にする（格子ごとの代表点どうしを近い順につなぐ、クラスカル法）
    parent = list(range(n))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for i, j in pairs:
        parent[find(i)] = find(j)
    cand = []
    for i, (x, y) in enumerate(pts):
        cx, cy = int(x // cell), int(y // cell)
        for dx in (-2, -1, 0, 1, 2):
            for dy in (-2, -1, 0, 1, 2):
                for j in grid.get((cx + dx, cy + dy), []):
                    if i < j:
                        cand.append((math.dist(pts[i], pts[j]), i, j))
    for _, i, j in sorted(cand):
        if find(i) != find(j):
            parent[find(i)] = find(j)
            pairs.add((i, j))
    centers = [(SIZE * 0.35, SIZE * 0.4), (SIZE * 0.7, SIZE * 0.65)]  # 都市高速のある 2 都市
    for i, j in pairs:
        d = math.dist(pts[i], pts[j]) * 1.1
        mid = ((pts[i][0] + pts[j][0]) / 2, (pts[i][1] + pts[j][1]) / 2)
        r = min(math.dist(mid, c) for c in centers)
        if r < 20:
            spec = dict(pool="shutoko", road="都市高速", time_min=d / 50 * 60)
        elif r < 50:
            spec = dict(pool="nexco", road="近郊", time_min=d / 85 * 60, fare_class="urban", holiday_ok=False)
        else:
            spec = dict(pool="nexco", road="地方", time_min=d / 95 * 60)
        for a, b in ((i, j), (j, i)):
            net.add_edge(Edge(f"n{a}", f"n{b}", dist_km=d, **spec))
    return net, pts


def run(n: int, seeds=range(3), k: int = 15):
    rows = []
    for seed in seeds:
        net, pts = make(n, seed)
        tariffs = default_tariffs()
        searcher = Searcher(net, tariffs)
        rnd = random.Random(seed + 99)
        for dep in (datetime(2026, 11, 25, 12), datetime(2026, 11, 27, 23, 10), datetime(2026, 11, 28, 3, 20)):
            while True:
                o = (rnd.uniform(0, SIZE), rnd.uniform(0, SIZE))
                d = (rnd.uniform(0, SIZE), rnd.uniform(0, SIZE))
                if 60 < math.dist(o, d) < 200:
                    break
            loc = lambda p, q: math.dist(p, q) * 1.3 / 30 * 60
            ids = [f"n{i}" for i in range(n)]
            ent = sorted(ids, key=lambda nid: loc(o, pts[int(nid[1:])]))[:k]
            ext = sorted(ids, key=lambda nid: loc(pts[int(nid[1:])], d))[:k]
            origin = {nid: loc(o, pts[int(nid[1:])]) for nid in ent}
            dest = {nid: loc(pts[int(nid[1:])], d) for nid in ext}
            lb = {nid: math.dist(pts[int(nid[1:])], d) / 100 * 60 for nid in ids}
            t0 = time.perf_counter()
            front = searcher.search(dep, origin, dest, loc(o, d), lb, max_labels=50_000)
            sec = time.perf_counter() - t0
            stats = searcher.stats
            rows.append(dict(n=n, seed=seed, dep=dep.strftime("%a %H:%M"), sec=sec,
                             pushed=stats["pushed"], max_bucket=stats["max_bucket"], approx=stats["approximate"],
                             **{key: value for key, value in stats.items()
                                if key in ("generated", "expanded") or key.startswith("pruned_")},
                             front=len(front)))
            print(rows[-1], flush=True)
    secs = [r["sec"] for r in rows]
    print(f"n={n}: mean {statistics.mean(secs):.2f}s max {max(secs):.2f}s, "
          f"mean pushed {statistics.mean(r['pushed'] for r in rows):.0f}, max pushed {max(r['pushed'] for r in rows)}, "
          f"max bucket {max(r['max_bucket'] for r in rows)}, "
          f"approx {sum(r['approx'] for r in rows)}/{len(rows)}", flush=True)
    if "generated" in rows[0]:
        generated = [r["generated"] for r in rows]
        print(f"n={n}: mean generated {statistics.mean(generated):.0f}, max generated {max(generated)}, "
              f"mean expanded {statistics.mean(r['expanded'] for r in rows):.0f}", flush=True)


if __name__ == "__main__":
    for n in map(int, sys.argv[1:] or ["500", "2000"]):
        run(n)
