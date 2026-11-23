"""比較用の料金モデル（数値は架空。本物の料金表ではない）。

料金グループごとの仕組み:
- nexco: 対距離制。利用 1 回ごとの定額 + 区分別の km 単価、長距離で逓減。休日割引・深夜割引あり。
- metro: 入口と出口で決まる距離制（グループ内の最短距離で計算）。下限と上限あり。経路に依存しない。
- aqua : 区間ごとの固定料金。曜日と時間帯で料金が変わる。

割引は重ならず、いちばん大きいものだけを適用する。
"""
from __future__ import annotations

import heapq
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from functools import lru_cache

from model import Network

TAX = 1.1
NEXCO_TC = 150
NEXCO_RATE = {"normal": 24.6, "urban": 29.52}
NEXCO_TAPER = [(100.0, 1.0), (200.0, 0.75), (float("inf"), 0.70)]

METRO_TC = 150
METRO_RATE = 29.5
METRO_MIN = 300
METRO_MAX = 1950

# 料金が切り替わる時刻（正時）。0 時は日付が変わり、休日判定も変わる。
BOUNDARY_HOURS = {"nexco": (0, 4), "aqua": (0, 6, 13, 20, 22)}

HOLIDAYS: set[date] = set()  # 祝日（比較用。テストで差し込む）
NO_DISCOUNT_DAYS: set[date] = set()  # 休日割引を適用しない日


def is_holiday(d: date) -> bool:
    if d in NO_DISCOUNT_DAYS:
        return False
    return d.weekday() >= 5 or d in HOLIDAYS


def tapered_km(total: float) -> float:
    """逓減を反映した「換算距離」。"""
    rest, prev, acc = total, 0.0, 0.0
    for upto, factor in NEXCO_TAPER:
        span = min(rest, upto - prev)
        if span <= 0:
            break
        acc += span * factor
        rest -= span
        prev = upto
    return acc


def overlaps_night(t_in: datetime, t_out: datetime) -> bool:
    """[t_in, t_out] が 0:00〜4:00 のどこかと重なるか。"""
    day = t_in.date() - timedelta(days=1)
    while datetime.combine(day, time(0)) <= t_out:
        start = datetime.combine(day, time(0))
        end = start + timedelta(hours=4)
        if t_in < end and t_out >= start:
            return True
        day += timedelta(days=1)
    return False


@dataclass(frozen=True)
class Run:
    group: str
    entry: str
    exit: str
    dist: tuple[tuple[str, float], ...]  # (区分, km)
    flat: int
    t_in: datetime
    t_out: datetime


def nexco_fare(run: Run) -> int:
    dist = dict(run.dist)
    total = sum(dist.values())
    if total <= 0:
        return 0
    base_raw = sum(NEXCO_RATE[c] * d for c, d in dist.items())
    ratio = tapered_km(total) / total
    full = (NEXCO_TC + base_raw * ratio) * TAX
    discounts = [0.0]
    if is_holiday(run.t_in.date()) or is_holiday(run.t_out.date()):
        normal_part = NEXCO_RATE["normal"] * dist.get("normal", 0.0) * ratio * TAX
        discounts.append(normal_part * 0.30)
    if overlaps_night(run.t_in, run.t_out):
        discounts.append(full * 0.30)
    return int(round(full - max(discounts)))


def aqua_factor(t: datetime) -> float:
    h = t.hour
    if is_holiday(t.date()):
        if 13 <= h < 20:
            return 1.5
        if h < 6 or h >= 22:
            return 0.8
        return 1.0
    return 1.0


def aqua_fare(run: Run) -> int:
    return int(round(run.flat * aqua_factor(run.t_in)))


class Fares:
    """ネットワークに結び付いた料金計算。metro の起終点距離をキャッシュする。"""

    def __init__(self, net: Network):
        self.net = net
        self._od = lru_cache(maxsize=None)(self._metro_od_km)

    def _metro_od_km(self, a: str, b: str) -> float:
        dist = {a: 0.0}
        pq = [(0.0, a)]
        while pq:
            d, u = heapq.heappop(pq)
            if u == b:
                return d
            if d > dist.get(u, float("inf")):
                continue
            for e in self.net.out[u]:
                if e.operator != "metro":
                    continue
                nd = d + e.dist_km
                if nd < dist.get(e.v, float("inf")):
                    dist[e.v] = nd
                    heapq.heappush(pq, (nd, e.v))
        return float("inf")

    def run_fare(self, run: Run) -> int:
        if run.group == "nexco":
            return nexco_fare(run)
        if run.group == "metro":
            km = self._od(run.entry, run.exit)
            raw = (METRO_TC + METRO_RATE * km) * TAX
            return int(round(min(max(raw, METRO_MIN), METRO_MAX)))
        if run.group == "aqua":
            return aqua_fare(run)
        raise ValueError(run.group)
