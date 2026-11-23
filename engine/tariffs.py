"""料金プールと割引の規則。数値の出典は docs/research-fares.md。

料金は「ラン」（同じ料金プールを続けて走った区間）ごとに計算する。
割引は重ならず、いちばん安くなるものだけを適用する（NEXCO・アクアラインの規則）。

【未確認のまま実装している点】（照合テストで確かめる）
- 対距離制で区分（普通・大都市近郊）が混ざるときの長距離逓減の掛け方（距離の比で按分している）
- 割引後の端数処理（割引前の金額から割引額を引き、最後に 10 円単位に丸めている）
- 首都高の新旧料金の切り替え（入口を通った日時で判定している）
"""
from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from functools import lru_cache

from . import calendar as cal
from .model import Edge, Network

TAX = 1.10


def round10(yen: float) -> int:
    """10 円単位に四捨五入。1 万円を超える場合は 100 円未満を切り捨て（NEXCO の規則）。"""
    if yen > 10000:
        return int(yen // 100 * 100)
    return int(math.floor(yen / 10 + 0.5) * 10)


@dataclass(frozen=True)
class Step:
    edge: Edge
    t0: datetime  # この区間に入った時刻
    t1: datetime  # この区間を出た時刻


@dataclass(frozen=True)
class RunFare:
    pool: str
    entry: str
    exit: str
    base: int  # 割引前
    fare: int  # 割引後
    discount: str | None = None


def overlaps(t_in: datetime, t_out: datetime, start: time, hours: float) -> bool:
    """[t_in, t_out] が、毎日 start から hours 時間の窓のどれかと重なるか。"""
    day = t_in.date() - timedelta(days=1)
    while datetime.combine(day, start) <= t_out:
        w0 = datetime.combine(day, start)
        w1 = w0 + timedelta(hours=hours)
        if t_in < w1 and t_out >= w0:
            return True
        day += timedelta(days=1)
    return False


def window_km(steps: list[Step], start: time, hours: float) -> tuple[float, float]:
    """窓（毎日 start から hours 時間）の中で走った距離と、窓の中にいた時間（時間）。各区間は等速とみなす。"""
    km = 0.0
    secs = 0.0
    for s in steps:
        dur = (s.t1 - s.t0).total_seconds()
        if dur <= 0:
            continue
        day = s.t0.date() - timedelta(days=1)
        while datetime.combine(day, start) <= s.t1:
            w0 = datetime.combine(day, start)
            w1 = w0 + timedelta(hours=hours)
            a, b = max(s.t0, w0), min(s.t1, w1)
            if b > a:
                ov = (b - a).total_seconds()
                km += s.edge.dist_km * ov / dur
                secs += ov
            day += timedelta(days=1)
    return km, secs / 3600


# ---------------------------------------------------------------- 料金プール


class Pool:
    id: str
    boundary_hours: tuple[int, ...] = ()  # 料金が切り替わる正時（探索で候補を捨てるかの判定に使う）
    distance_matters: bool = True  # ランの距離が料金に効くか（効かなければ探索の比較で無視する）
    per_gate: bool = False  # 料金所を通った時点で金額が確定するか
    gate_time_invariant: bool = False

    def minimum_gate_fare(self, edge: Edge) -> int:
        """未通過の辺で確定する料金の下限（全時刻）。"""
        return 0

    def run_fare(self, net: Network, entry: str, exit_: str, steps: list[Step]) -> RunFare:
        raise NotImplementedError

    def state_key(self, t_in: datetime, now: datetime, steps):
        """探索で同じ扱いにしてよいランを見分けるための鍵（割引の判定状態）。steps() でランの区間の一覧を得られる。"""
        return None

    def boundary_moments(self) -> tuple[datetime, ...]:
        """料金が切り替わる特定の日時（料金改定日など）。"""
        return ()

    def gate_fare_at(self, edge: Edge, t: datetime) -> int:
        return 0

    def validate(self) -> None:
        """探索の前提（距離が多いほど料金が高い、など）を満たしているかを確かめる。"""


@dataclass
class NightV2:
    """見直し後の深夜割引（22〜翌 5 時に走った分だけ 3 割引、上限距離あり）。施行日は未定。"""

    effective_from: datetime | None = None  # None のあいだは無効
    rate: float = 0.30
    cap_kmh: float = 105.0

    def active(self, t: datetime) -> bool:
        return self.effective_from is not None and t >= self.effective_from

    def discount(self, steps: list[Step], base_raw: float, total_km: float) -> float:
        km, hours = window_km(steps, time(22), 7)
        if km <= 0 or total_km <= 0:
            return 0.0
        if hours <= 4:
            cap = hours * self.cap_kmh
        elif hours <= 4.5:
            cap = 4 * self.cap_kmh
        else:
            cap = (hours - 0.5) * self.cap_kmh
        return base_raw * min(km, cap) / total_km * self.rate


@dataclass
class NexcoPool(Pool):
    """対距離制（NEXCO の高速自動車国道など）。"""

    id: str = "nexco"
    tc: float = 150.0
    # 海峡部等特別区間（108.1 円/km）は本四・アクアラインなど別の料金プールで扱う。同じプールに混ぜると
    # 「距離が多いほど高い」が崩れることがあり、探索が正しくなくなる（validate で検出する）。
    rates: dict[str, float] = field(default_factory=lambda: {"normal": 24.6, "urban": 29.52, "low": 19.68})
    taper: tuple[tuple[float, float], ...] = ((100.0, 1.0), (200.0, 0.75), (math.inf, 0.70))
    holiday_rate: float = 0.30
    night_rate: float = 0.30
    night_v2: NightV2 = field(default_factory=NightV2)
    boundary_hours: tuple[int, ...] = (0, 4, 5, 22)

    def _tapered(self, total: float) -> float:
        rest, prev, acc = total, 0.0, 0.0
        for upto, f in self.taper:
            span = min(rest, upto - prev)
            if span <= 0:
                break
            acc += span * f
            rest -= span
            prev = upto
        return acc

    def run_fare(self, net, entry, exit_, steps):
        total = sum(s.edge.dist_km for s in steps)
        ratio = self._tapered(total) / total if total else 0.0
        by_part = lambda pred: sum(self.rates[s.edge.fare_class] * s.edge.dist_km for s in steps if pred(s.edge)) * ratio
        base_raw = (self.tc + by_part(lambda e: True)) * TAX
        t_in, t_out = steps[0].t0, steps[-1].t1

        options: list[tuple[float, str]] = []
        if cal.is_nexco_holiday_discount_day(t_in.date()) or cal.is_nexco_holiday_discount_day(t_out.date()):
            part = by_part(lambda e: e.holiday_ok) * TAX
            if part > 0:
                options.append((part * self.holiday_rate, "休日割引"))
        night_steps = [s for s in steps if s.edge.night_ok]
        if self.night_v2.active(t_in):
            d = self.night_v2.discount(night_steps, base_raw, total)
            if d > 0:
                options.append((d, "深夜割引"))
        elif night_steps and overlaps(t_in, t_out, time(0), 4):
            part = (self.tc + by_part(lambda e: e.night_ok)) * TAX
            options.append((part * self.night_rate, "深夜割引"))
        base = round10(base_raw)
        if not options:
            return RunFare(self.id, entry, exit_, base, base)
        amount, name = max(options)
        return RunFare(self.id, entry, exit_, base, round10(base_raw - amount), name)

    def state_key(self, t_in, now, steps):
        if self.night_v2.active(t_in):
            # 見直し後は、深夜の時間帯に走った距離と時間で割引額が変わるので、それも鍵に入れる。
            # 丸めて同一視すると割引額の違う状態を混ぜ得るので、集計値の厳密な一致で比べる
            v2 = window_km([s for s in steps() if s.edge.night_ok], time(22), 7)
        else:
            v2 = None
        return (cal.is_nexco_holiday_discount_day(t_in.date()), overlaps(t_in, now, time(0), 4), v2)

    def boundary_moments(self):
        return (self.night_v2.effective_from,) if self.night_v2.effective_from else ()

    def validate(self):
        """区分を混ぜたときも「どの区分の距離が増えても料金が下がらない」ことを、距離ごとに数値で確かめる。"""
        # 休日割引は区間の一部だけを安くするので、いちばん下がった単価で確かめる
        r_max, r_min = max(self.rates.values()), min(self.rates.values()) * (1 - self.holiday_rate)
        d = 0.5
        while d < 3000:
            t, t2 = self._tapered(d), self._tapered(d + 0.01)
            slope, avg = (t2 - t) / 0.01, t / d
            if r_max * (slope - avg) + r_min * avg < -1e-9:
                raise ValueError(f"{self.id}: 単価 {self.rates} と逓減では、距離が増えると安くなる場合がある（{d}km 付近）")
            d += 0.5


@dataclass(frozen=True)
class OdVersion:
    effective_from: datetime
    rate: float
    min_yen: int
    max_yen: int


@dataclass
class OdDistancePool(Pool):
    """入口と出口の間の最短距離で決まる距離制（首都高など）。入口を通った時刻で料金・深夜割引を判定する。"""

    id: str = "shutoko"
    tc: float = 150.0
    versions: tuple[OdVersion, ...] = ()
    night_rate: float = 0.20
    boundary_hours: tuple[int, ...] = (0, 4)
    distance_matters: bool = False

    def __post_init__(self):
        self._od = lru_cache(maxsize=None)(self._od_km)
        self._net = None

    def _od_km(self, a: str, b: str) -> float:
        dist = {a: 0.0}
        pq = [(0.0, a)]
        while pq:
            d, u = heapq.heappop(pq)
            if u == b:
                return d
            if d > dist[u]:
                continue
            for e in self._net.out[u]:
                if e.pool != self.id:
                    continue
                nd = d + e.dist_km
                if nd < dist.get(e.v, math.inf):
                    dist[e.v] = nd
                    heapq.heappush(pq, (nd, e.v))
        return math.inf

    def version_at(self, t: datetime) -> OdVersion:
        vs = [v for v in self.versions if v.effective_from <= t]
        if not vs:
            raise ValueError(f"{self.id}: {t} に有効な料金がない")
        return max(vs, key=lambda v: v.effective_from)

    def run_fare(self, net, entry, exit_, steps):
        if self._net is not net:
            self._net = net
            self._od.cache_clear()
        t_in = steps[0].t0
        v = self.version_at(t_in)
        # 料金距離は「首都高だけを使う場合の最短経路の距離」。往復で違うときは短いほう（research 2-3）
        km = min(self._od(entry, exit_), self._od(exit_, entry))
        raw = (v.rate * km + self.tc) * TAX
        base = min(max(round10(raw), v.min_yen), v.max_yen)
        if t_in.time() < time(4):
            return RunFare(self.id, entry, exit_, base, round10(base * (1 - self.night_rate)), "深夜割引")
        return RunFare(self.id, entry, exit_, base, base)

    def state_key(self, t_in, now, steps):
        return (self.version_at(t_in).effective_from, t_in.time() < time(4))

    def boundary_moments(self):
        return tuple(v.effective_from for v in self.versions)


@dataclass
class OdTablePool(Pool):
    """IC 間の料金表で決まる道路（第三京浜・横浜横須賀道路など）。休日・深夜割引の対象外。"""

    id: str = ""
    table: dict[tuple[str, str], int] = field(default_factory=dict)
    distance_matters: bool = False

    def run_fare(self, net, entry, exit_, steps):
        fare = self.table.get((entry, exit_), self.table.get((exit_, entry)))
        if fare is None:
            raise KeyError(f"{self.id}: {entry}→{exit_} の料金が料金表にない")
        return RunFare(self.id, entry, exit_, fare, fare)


@dataclass
class TollgatePool(Pool):
    """本線料金所を通るたびに料金が決まる道路（横浜新道・アクアラインなど）。

    gate_fare(tollgate, direction, 通過時刻) -> (割引前, 割引後, 割引名) を道路ごとに与える。
    """

    id: str = ""
    gate_fare: object = None
    boundary_hours: tuple[int, ...] = ()
    moments: tuple[datetime, ...] = ()
    distance_matters: bool = False
    per_gate: bool = True

    @property
    def gate_time_invariant(self) -> bool:
        return isinstance(self.gate_fare, _FlatGate)

    def gate_fare_at(self, edge, t):
        return self.gate_fare(edge.tollgate, edge.direction, t)[1] if edge.tollgate else 0

    def minimum_gate_fare(self, edge: Edge) -> int:
        if not edge.tollgate:
            return 0
        if isinstance(self.gate_fare, _FlatGate):
            return self.gate_fare.yen
        if self.gate_fare is aqua_gate:
            column = 2 if edge.direction == "up" else 3
            return min(AQUA_WEEKDAY, min(band[column] for band in AQUA_HOLIDAY))
        return 0

    def boundary_moments(self):
        return self.moments

    def run_fare(self, net, entry, exit_, steps):
        base = fare = 0
        names = []
        for s in steps:
            if s.edge.tollgate:
                b, f, name = self.gate_fare(s.edge.tollgate, s.edge.direction, s.t0)
                base += b
                fare += f
                if name:
                    names.append(name)
        return RunFare(self.id, entry, exit_, base, fare, "・".join(names) or None)


# ---------------------------------------------------------------- 道路ごとの料金所の料金


@dataclass(frozen=True)
class _FlatGate:
    yen: int

    def __call__(self, gate, direction, t):
        return self.yen, self.yen, None


def flat_gate(yen: int):
    return _FlatGate(yen)


AQUA_WEEKDAY = 800
# 土日祝の時間帯別料金（普通車、docs/research-fares.md 5 章）。(開始時, 終了時, 上り, 下り)
AQUA_HOLIDAY = (
    (0, 4, 400, 400), (4, 5, 800, 800), (5, 7, 800, 1000), (7, 13, 800, 800),
    (13, 19, 1600, 800), (19, 20, 800, 800), (20, 24, 400, 800),
)
AQUA_FROM = datetime(2025, 4, 1)  # 時間帯別料金の実施期間（2025-04-01〜2027-03-31）
AQUA_UNTIL = datetime(2027, 4, 1)


def aqua_gate(gate, direction, t: datetime):
    """アクアライン（普通車 ETC）。平日は終日 800 円、土日祝は時間帯別料金。

    深夜割引は通常料金（現金 3,140 円）に対する割引なので、800 円や時間帯別料金より安くならない。
    重ならない規則のため、ここでは考えなくてよい（research 5 章）。
    """
    if AQUA_FROM <= t < AQUA_UNTIL and cal.is_aqua_holiday(t.date()):
        for h0, h1, up, down in AQUA_HOLIDAY:
            if h0 <= t.hour < h1:
                price = up if direction == "up" else down
                return price, price, "時間帯別料金"
    return AQUA_WEEKDAY, AQUA_WEEKDAY, None


@dataclass
class Tariffs:
    pools: dict[str, Pool]

    def run_fare(self, net: Network, entry: str, exit_: str, steps: list[Step]) -> RunFare:
        return self.pools[steps[0].edge.pool].run_fare(net, entry, exit_, steps)


def default_tariffs(od_tables: dict[str, dict[tuple[str, str], int]] | None = None) -> Tariffs:
    """2026-11-23 時点の制度。od_tables は料金表で決まる道路の表（プール ID → 表）。"""
    pools: dict[str, Pool] = {
        "nexco": NexcoPool(),
        "shutoko": OdDistancePool(
            id="shutoko",
            versions=(
                OdVersion(datetime(2022, 4, 1), 29.52, 300, 1950),
                OdVersion(datetime(2026, 10, 1), 32.472, 300, 2130),
            ),
        ),
        "yokohama_shindo": TollgatePool(id="yokohama_shindo", gate_fare=flat_gate(320)),
        "aqualine": TollgatePool(id="aqualine", gate_fare=aqua_gate, boundary_hours=(0, 4, 5, 7, 13, 19, 20),
                                 moments=(AQUA_FROM, AQUA_UNTIL)),
    }
    for pid, table in (od_tables or {}).items():
        pools[pid] = OdTablePool(id=pid, table=table)
    return Tariffs(pools)
