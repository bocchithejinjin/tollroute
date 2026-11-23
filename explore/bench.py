"""アルゴリズムの比較実験。

使い方: python bench.py small   # 総当たり(F)を正解として、A/B/C の正しさを比べる
        python bench.py large   # 全国規模に近い大きさで、C を基準に A/B の正しさと速さを比べる
"""
from __future__ import annotations

import json
import statistics
import sys
import time

from algos import ALGOS, evaluate, pick
from fares import Fares
from synth import DEPARTURES, make_network, make_query


def budgets_from(front):
    fs = sorted({p.fare for p in front})
    out = set(fs)
    for a, b in zip(fs, fs[1:]):
        out.add((a + b) // 2)
    return sorted(out)


def check_consistent(net, fares, q, front):
    """各アルゴリズムが報告した料金・時間が、経路を正確に計算し直した値と一致するか。"""
    for p in front:
        if p.entry is None:
            continue
        again = evaluate(net, fares, q, p.entry, p.edges, p.exit)
        if again.fare != p.fare or abs(again.minutes - p.minutes) > 1e-6:
            return False
    return True


def run(mode: str):
    if mode == "night":
        from datetime import datetime, timedelta
        import synth
        base = datetime(2026, 11, 27, 22, 30)  # 金曜 22:30 から 10 分刻み
        synth.DEPARTURES = {f"fri+{i*10}m": base + timedelta(minutes=10 * i) for i in range(13)}
        globals()["DEPARTURES"] = synth.DEPARTURES
        sizes, seeds, names, ref, maxc = [20], range(10), ["A_pair_fastest", "C_labels", "F_brute"], "F_brute", None
    elif mode == "small":
        sizes, seeds, names, ref, maxc = [22, 28], range(12), ["A_pair_fastest", "B_pair_k5", "C_labels", "F_brute"], "F_brute", None
    else:
        sizes, seeds, names, ref, maxc = [300, 1500], range(3), ["A_pair_fastest", "C_labels"], "C_labels", 12
    rows = []
    for n in sizes:
        for seed in seeds:
            net = make_network(n, seed)
            fares = Fares(net)
            for dep_name, dep in DEPARTURES.items():
                q = make_query(seed, dep)
                res, secs = {}, {}
                for name in names:
                    t0 = time.perf_counter()
                    res[name] = ALGOS[name](net, fares, q, max_candidates=maxc)
                    secs[name] = time.perf_counter() - t0
                print(n, seed, dep_name, {k: round(v, 3) for k, v in secs.items()}, flush=True)
                truth = res[ref]
                for name in names:
                    regrets = []
                    for b in budgets_from(truth):
                        regrets.append(pick(res[name], b).minutes - pick(truth, b).minutes)
                    rows.append({
                        "n": n, "seed": seed, "dep": dep_name, "algo": name,
                        "sec": secs[name],
                        "max_regret_min": max(regrets),
                        "wrong_budgets": sum(r > 1e-6 for r in regrets),
                        "budgets": len(regrets),
                        "better_than_ref": sum(r < -1e-6 for r in regrets),
                        "consistent": check_consistent(net, fares, q, res[name]),
                        "front": len(res[name]),
                    })
    summarize(rows)
    with open(f"bench_{mode}.json", "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=1)


def summarize(rows):
    algos = sorted({r["algo"] for r in rows})
    sizes = sorted({r["n"] for r in rows})
    print(f"{'n':>5} {'algo':16} {'queries':>7} {'wrong%':>7} {'budgetWrong%':>12} {'maxRegret':>9} {'better':>6} {'consist':>7} {'mean s':>8} {'p95 s':>8}")
    for n in sizes:
        for a in algos:
            rs = [r for r in rows if r["n"] == n and r["algo"] == a]
            secs = sorted(r["sec"] for r in rs)
            p95 = secs[min(len(secs) - 1, int(len(secs) * 0.95))]
            wrong_q = sum(r["wrong_budgets"] > 0 for r in rs) / len(rs) * 100
            wb = sum(r["wrong_budgets"] for r in rs) / sum(r["budgets"] for r in rs) * 100
            print(f"{n:>5} {a:16} {len(rs):>7} {wrong_q:>6.1f}% {wb:>11.1f}% {max(r['max_regret_min'] for r in rs):>9.1f}"
                  f" {sum(r['better_than_ref'] for r in rs):>6} {str(all(r['consistent'] for r in rs)):>7}"
                  f" {statistics.mean(secs):>8.3f} {p95:>8.3f}")


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "small")
