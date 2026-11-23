"""本番エンジン（engine/）の性能測定。全国規模に近い架空の道路網で、時間・ラベル数・メモリを測る。

使い方: python explore/scale_engine.py [ノード数...] [--cap 秒] [--out 結果.jsonl]
"""
from __future__ import annotations

import json
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


DEPARTS = (datetime(2026, 11, 25, 12), datetime(2026, 11, 27, 23, 10), datetime(2026, 11, 28, 3, 20))


def queries(n: int, seed: int, pts, k: int = 15):
    """シードごとに、3 つの出発時刻それぞれの (出発, 入口候補, 出口候補, 一般道のみの時間, 下限) を作る。"""
    rnd = random.Random(seed + 99)
    out = []
    for dep in DEPARTS:
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
        out.append((dep, origin, dest, loc(o, d), lb))
    return out


def _one(n, seed, qi, max_labels):
    """1 検索を測る（グラフ生成と Searcher の前計算は計測区間の外）。"""
    net, pts = make(n, seed)
    searcher = Searcher(net, default_tariffs())
    dep, origin, dest, local, lb = queries(n, seed, pts)[qi]
    t0 = time.perf_counter()
    front = searcher.search(dep, origin, dest, local, lb, max_labels=max_labels)
    sec = time.perf_counter() - t0
    stats = searcher.stats
    return dict(n=n, seed=seed, dep=dep.strftime("%a %H:%M"), sec=sec, done=True,
                pushed=stats["pushed"], max_bucket=stats["max_bucket"], approx=stats["approximate"],
                **{key: value for key, value in stats.items()
                   if key in ("generated", "expanded") or key.startswith("pruned_")},
                front=len(front))


def _worker(conn, *args):
    conn.send(_one(*args))
    conn.close()


def _capped(cap, n, seed, qi, max_labels):
    """別プロセスで測り、cap 秒を超えたら打ち切って未完了として返す。"""
    import multiprocessing as mp
    parent, child = mp.Pipe(duplex=False)
    proc = mp.Process(target=_worker, args=(child, n, seed, qi, max_labels))
    proc.start()
    # グラフ生成・前計算の時間も含めて待つので、余裕を持たせる
    if parent.poll(cap + 60):
        row = parent.recv()
        proc.join()
        if row["sec"] <= cap:
            return row
    else:
        proc.kill()
        proc.join()
    return dict(n=n, seed=seed, dep=DEPARTS[qi].strftime("%a %H:%M"), sec=cap, done=False)


def run(n: int, seeds=range(3), max_labels: int = 50_000, cap: float | None = None, out=None):
    rows = []
    for seed in seeds:
        for qi in range(len(DEPARTS)):
            row = _capped(cap, n, seed, qi, max_labels) if cap else _one(n, seed, qi, max_labels)
            rows.append(row)
            print(row, flush=True)
            if out:
                with open(out, "a", encoding="utf-8") as f:
                    print(json.dumps(row, ensure_ascii=False), file=f)
    done = [r for r in rows if r["done"]]
    print(f"n={n}: 完了 {len(done)}/{len(rows)}", flush=True)
    if not done:
        return
    secs = [r["sec"] for r in done]
    print(f"n={n}: mean {statistics.mean(secs):.2f}s max {max(secs):.2f}s, "
          f"mean pushed {statistics.mean(r['pushed'] for r in done):.0f}, max pushed {max(r['pushed'] for r in done)}, "
          f"max bucket {max(r['max_bucket'] for r in done)}, "
          f"approx {sum(r['approx'] for r in done)}/{len(done)}", flush=True)
    if "generated" in done[0]:
        generated = [r["generated"] for r in done]
        print(f"n={n}: mean generated {statistics.mean(generated):.0f}, max generated {max(generated)}, "
              f"mean expanded {statistics.mean(r['expanded'] for r in done):.0f}", flush=True)


if __name__ == "__main__":
    # 使い方: python explore/scale_engine.py [ノード数...] [--cap 秒] [--out 結果.jsonl]
    args = sys.argv[1:]
    cap = out = None
    if "--cap" in args:
        i = args.index("--cap")
        cap = float(args[i + 1])
        del args[i:i + 2]
    if "--out" in args:
        i = args.index("--out")
        out = args[i + 1]
        del args[i:i + 2]
    for n in map(int, args or ["500", "2000"]):
        run(n, cap=cap, out=out)
