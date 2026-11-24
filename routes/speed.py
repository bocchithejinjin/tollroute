"""一般道の所要時間を、道路交通センサスの地域別・時間帯別の平均旅行速度で見積もる。

OSRM の時間は信号待ちや渋滞のない値で、都市部では実際の 2〜3 倍速く出る（docs/local-speed-model.md）。
そこで所要時間 = OSRM の経路の距離 ÷ 通る地域の平均旅行速度 とする。
- 地域: 出発点から終点までの直線上の数点を、手元の住所辞書（jageocoder）で市区町村に逆引きし、
  センサスの地域（東京都（特別区）、横浜市、埼玉県（さいたま市を除く）など）に当てる。
- 時間帯: 平日の朝夕（7〜9 時、17〜19 時）は混雑時、それ以外の 7〜19 時（休日の昼も）は非混雑時の速度。
  夜間（19〜7 時）はセンサスに値がないので、非混雑時の速度 × NIGHT_SPEEDUP（推定、未確認）。
- どの時間帯でも、OSRM の渋滞なしの時間より速くはしない。
住所辞書がないときは、呼び出し側が従来の一律の係数に戻す（SpeedModel.available）。
"""
from __future__ import annotations

import json
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from engine.calendar import is_weekend_or_holiday

DATA = json.loads(Path(__file__).with_name("census_speeds.json").read_text(encoding="utf-8"))
SOURCE = DATA["_source"]
AREAS: dict[str, dict[str, float]] = DATA["areas"]
PEAK_HOURS = ((7, 9), (17, 19))  # センサスの「朝夕（混雑時）」
DAY_HOURS = (7, 19)  # センサスの「昼間」
NIGHT_SPEEDUP = 1.25  # 夜間の速度 = 非混雑時 × これ（推定。センサスに夜間の値はない）
SAMPLES = 5  # 直線上で地域を調べる点の数（両端を含む）
FALLBACK_AREA = "東京都（市郡部）"


def band(at: datetime) -> str:
    """'peak'（平日の朝夕）・'offpeak'（昼間のそれ以外）・'night'（19〜7 時）。"""
    hour = at.hour
    if not DAY_HOURS[0] <= hour < DAY_HOURS[1]:
        return "night"
    if not is_weekend_or_holiday(at.date()) and any(a <= hour < b for a, b in PEAK_HOURS):
        return "peak"
    return "offpeak"


def area_key(prefecture: str, city: str) -> str:
    """住所辞書の (都道府県, 市区町村) → センサスの地域名。"""
    if city in AREAS:  # 政令市（横浜市、さいたま市など）
        return city
    if prefecture == "東京都":
        return "東京都（特別区）" if city.endswith("区") else "東京都（市郡部）"
    for key in AREAS:  # 「神奈川県（横浜市、川崎市、相模原市を除く）」など
        if key.startswith(prefecture + "（") and "除く" in key:
            return key
    for key in (prefecture, prefecture + "全域"):
        if key in AREAS:
            return key
    return FALLBACK_AREA


class SpeedModel:
    def __init__(self, reverse=None):
        """reverse(lat, lon) → (都道府県, 市区町村) または None。省略すると jageocoder を使う。"""
        self._reverse = reverse or _jageocoder_reverse()
        self.available = self._reverse is not None

    @lru_cache(maxsize=4096)
    def area_at(self, lat: float, lon: float) -> str:
        found = self._reverse(lat, lon)
        return area_key(*found) if found else FALLBACK_AREA

    def speed(self, area: str, when: datetime) -> float:
        b = band(when)
        speeds = AREAS.get(area) or AREAS[FALLBACK_AREA]
        return speeds["offpeak"] * NIGHT_SPEEDUP if b == "night" else speeds[b]

    def areas_between(self, a, b) -> list[str]:
        points = [(a[0] + (b[0] - a[0]) * i / (SAMPLES - 1), a[1] + (b[1] - a[1]) * i / (SAMPLES - 1))
                  for i in range(SAMPLES)]
        # 約 1km 単位に丸めて逆引きを使い回す
        return [self.area_at(round(lat, 2), round(lon, 2)) for lat, lon in points]

    def minutes(self, a, b, km: float, free_flow_min: float, when: datetime) -> float:
        """a → b を一般道で km 走る所要時間（分）。直線上の各点の地域の速度で、距離を等分して走るとみなす。"""
        areas = self.areas_between(a, b)
        hours = sum(km / len(areas) / self.speed(area, when) for area in areas)
        return max(hours * 60, free_flow_min)


def _jageocoder_reverse():
    import os

    from .geocode import DEFAULT_DB, GeocoderUnavailable, _init

    # 逆引きの索引がないと、最初の逆引きで索引作り（数分）が始まって検索が止まる。
    # 索引は tools/build_reverse_index.py で先に作っておく。なければ従来の係数に戻す。
    db = Path(os.environ.get("JAGEOCODER_DB2_DIR", DEFAULT_DB))
    if not (db / "rtree.dat").exists():
        return None
    try:
        jageocoder = _init()  # 住所検索と同じ辞書（読み取り専用）
    except GeocoderUnavailable:
        return None

    def reverse(lat, lon):
        try:
            found = jageocoder.reverse(lon, lat, level=3)
        except Exception:
            return None
        if not found:
            return None
        names = found[0]["candidate"]["fullname"]
        return (names[0], names[1]) if len(names) >= 2 else None

    return reverse


@lru_cache(maxsize=1)
def default_model() -> SpeedModel:
    return SpeedModel()
