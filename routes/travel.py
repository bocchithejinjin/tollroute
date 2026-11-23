"""一般道の所要時間（有料道路を使わない）を求める部品。差し替えられるようにしておく。

使う実装は環境変数 TRAVEL_TIME_PROVIDER で選ぶ。
- osrm（既定）: 手元の OSRM（関東のグラフ、`exclude=toll`）に問い合わせる。接続できなければ estimate に切り替える
- estimate: 直線距離 × 1.3 ÷ 時速 20km の概算（外部に何も送らない）

OSRM の時間は渋滞のない状態の値なので、都市部の混雑を見込んで LOCAL_CONGESTION_FACTOR（既定 1.8）倍する。
郊外も都心も同じ係数を掛ける粗い補正（docs/routing-eval.md）。
"""
from __future__ import annotations

import json
import math
import os
import urllib.error
import urllib.request
from typing import Protocol

LatLon = tuple[float, float]


class TravelTimeError(RuntimeError):
    """所要時間を求められなかった（接続できない、応答が不正など）。"""


class TravelTimeProvider(Protocol):
    name: str
    approximate: bool  # 直線距離からの概算かどうか（画面の注記に使う）
    description: str  # 画面の注記に出す説明

    def from_origin(self, origin: LatLon, points: list[LatLon]) -> list[float | None]:
        """出発地 → 各地点の所要時間（分）。到達できなければ None。"""

    def to_dest(self, points: list[LatLon], dest: LatLon) -> list[float | None]:
        """各地点 → 目的地の所要時間（分）。"""

    def between(self, a: LatLon, b: LatLon) -> float | None:
        """a → b の所要時間（分）。"""


def _km(a: LatLon, b: LatLon) -> float:
    x = math.radians(b[1] - a[1]) * math.cos(math.radians((a[0] + b[0]) / 2))
    y = math.radians(b[0] - a[0])
    return 6371.0 * math.hypot(x, y)


class EstimateProvider:
    name = "estimate"
    approximate = True
    detour = 1.3
    kmh = 20.0
    description = "一般道の所要時間は、直線距離 × 1.3 ÷ 時速 20km で推定した概算です。"

    def _min(self, a: LatLon, b: LatLon) -> float:
        return _km(a, b) * self.detour / self.kmh * 60

    def from_origin(self, origin, points):
        return [self._min(origin, p) for p in points]

    def to_dest(self, points, dest):
        return [self._min(p, dest) for p in points]

    def between(self, a, b):
        return self._min(a, b)


class OsrmProvider:
    """手元の OSRM（MLD、car プロファイル）。有料道路を除外した所要時間を Table API でまとめて求める。"""

    name = "osrm"
    approximate = False
    # IC の点が有料道路の上にあると「有料道路を除外」では到達できない。その IC の近く（約 200〜700m）の
    # 一般道上の点から、到達できて IC にいちばん近い点を「出入り口」として使う。基準点は東京駅付近
    REFERENCE = (35.6812, 139.7671)
    RINGS = (0.002, 0.004, 0.007)  # 度（約 200m・400m・700m）

    def __init__(self, base_url: str | None = None, factor: float | None = None, timeout: float = 5.0):
        self.base_url = (base_url or os.environ.get("OSRM_URL", "http://osrm:5000")).rstrip("/")
        self.factor = factor if factor is not None else float(os.environ.get("LOCAL_CONGESTION_FACTOR", "1.8"))
        self.timeout = timeout
        self._access: dict[tuple[float, float], LatLon] = {}
        self.description = (
            f"一般道の所要時間は、OpenStreetMap の道路データから OSRM で求めた時間（渋滞なし）に、"
            f"混雑を見込んで {self.factor:g} 倍した目安です。"
        )

    # ---------------------------------------------------------------- HTTP
    def _get(self, path: str) -> dict:
        url = f"{self.base_url}{path}"
        try:
            with urllib.request.urlopen(url, timeout=self.timeout) as res:
                data = json.load(res)
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            raise TravelTimeError(f"ルート検索エンジン（OSRM）に接続できません: {exc}") from exc
        if data.get("code") != "Ok":
            raise TravelTimeError(f"OSRM の応答が不正です: {data.get('code')} {data.get('message', '')}")
        return data

    @staticmethod
    def _coords(points: list[LatLon]) -> str:
        return ";".join(f"{lon:.6f},{lat:.6f}" for lat, lon in points)

    def _table(self, points: list[LatLon], sources: list[int], destinations: list[int]) -> list[list[float | None]]:
        q = (f"/table/v1/driving/{self._coords(points)}?exclude=toll&annotations=duration"
             f"&sources={';'.join(map(str, sources))}&destinations={';'.join(map(str, destinations))}")
        return self._get(q)["durations"]

    # ---------------------------------------------------------------- IC の出入り口
    def access_points(self, points: list[LatLon]) -> list[LatLon]:
        """各点を、有料道路を使わずに到達できる点に置き換える（できなければ元の点のまま）。"""
        key = lambda p: (round(p[0], 6), round(p[1], 6))
        todo = [p for p in points if key(p) not in self._access]
        if todo:
            ref = self.REFERENCE
            durs = self._table([ref, *todo], [0], list(range(1, len(todo) + 1)))[0]
            for p, d in zip(todo, durs):
                self._access[key(p)] = p if d is not None else self._find_access(p)
        return [self._access[key(p)] for p in points]

    def _find_access(self, p: LatLon) -> LatLon:
        lat, lon = p
        cands = [(lat + r * math.sin(2 * math.pi * i / 12), lon + r * math.cos(2 * math.pi * i / 12) / math.cos(math.radians(lat)))
                 for r in self.RINGS for i in range(12)]
        data = self._get(f"/table/v1/driving/{self._coords([self.REFERENCE, *cands])}?exclude=toll"
                         f"&annotations=duration&sources=0")
        best, best_km = p, math.inf
        for d, wp in zip(data["durations"][0][1:], data["destinations"][1:]):
            if d is None:
                continue
            snapped = (wp["location"][1], wp["location"][0])
            km = _km(p, snapped)
            if km < best_km:
                best, best_km = snapped, km
        return best

    # ---------------------------------------------------------------- 公開する操作
    def _scale(self, sec: float | None) -> float | None:
        return None if sec is None else sec / 60 * self.factor

    def from_origin(self, origin, points):
        acc = self.access_points(points)
        row = self._table([origin, *acc], [0], list(range(1, len(acc) + 1)))[0]
        return [self._scale(s) for s in row]

    def to_dest(self, points, dest):
        acc = self.access_points(points)
        n = len(acc)
        rows = self._table([*acc, dest], list(range(n)), [n])
        return [self._scale(r[0]) for r in rows]

    def between(self, a, b):
        return self._scale(self._table([a, b], [0], [1])[0][0])


def get_provider() -> TravelTimeProvider:
    name = os.environ.get("TRAVEL_TIME_PROVIDER", "osrm")
    if name == "estimate":
        return EstimateProvider()
    if name == "osrm":
        return OsrmProvider()
    raise ValueError(f"未対応の TRAVEL_TIME_PROVIDER: {name}")
