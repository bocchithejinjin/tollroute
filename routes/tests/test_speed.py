"""一般道の所要時間（道路交通センサスの平均旅行速度）のテスト。住所辞書は使わず、逆引きを差し替える。"""
from datetime import datetime

import pytest

from routes import speed
from routes.speed import AREAS, SpeedModel, area_key, band
from routes.travel import OsrmProvider


@pytest.mark.parametrize("when, expected", [
    (datetime(2026, 11, 25, 8, 0), "peak"),      # 水曜の朝
    (datetime(2026, 11, 25, 18, 59), "peak"),    # 水曜の夕方
    (datetime(2026, 11, 25, 12, 0), "offpeak"),  # 水曜の昼
    (datetime(2026, 11, 25, 9, 0), "offpeak"),   # 朝の混雑時（7〜9 時）の直後
    (datetime(2026, 11, 28, 8, 0), "offpeak"),   # 土曜の朝
    (datetime(2026, 11, 23, 8, 0), "offpeak"),   # 祝日（勤労感謝の日）の朝
    (datetime(2026, 11, 25, 19, 0), "night"),
    (datetime(2026, 11, 25, 6, 59), "night"),
])
def test_band(when, expected):
    assert band(when) == expected


@pytest.mark.parametrize("prefecture, city, expected", [
    ("東京都", "新宿区", "東京都（特別区）"),
    ("東京都", "八王子市", "東京都（市郡部）"),
    ("神奈川県", "横浜市", "横浜市"),
    ("神奈川県", "藤沢市", "神奈川県（横浜市、川崎市、相模原市を除く）"),
    ("埼玉県", "川口市", "埼玉県（さいたま市を除く）"),
    ("山梨県", "甲府市", "山梨県"),
])
def test_area_key(prefecture, city, expected):
    assert area_key(prefecture, city) == expected
    assert expected in AREAS


def test_census_speeds_are_slower_at_peak():
    for name, speeds in AREAS.items():
        assert 5 < speeds["peak"] <= speeds["offpeak"] + 1e-9 < 80, name
    # 都心ほど遅い（令和3年度センサス、一般道路計）
    assert AREAS["東京都（特別区）"]["peak"] < AREAS["東京都（市郡部）"]["peak"] < AREAS["神奈川県全域"]["peak"]


def fixed_model(area_by_lon):
    """経度で東京都（特別区）か横浜市かを決める逆引き。"""
    return SpeedModel(reverse=lambda lat, lon: ("東京都", "新宿区") if lon >= area_by_lon else ("神奈川県", "横浜市"))


def test_minutes_uses_distance_and_area_speed():
    model = fixed_model(139.65)
    a, b = (35.47, 139.62), (35.69, 139.70)  # 5 点のうち横浜市が 2 点、特別区が 3 点になる
    when = datetime(2026, 11, 25, 8, 0)
    areas = model.areas_between(a, b)
    assert areas.count("横浜市") == 2 and areas.count("東京都（特別区）") == 3
    expected = sum(30 / 5 / AREAS[x]["peak"] for x in areas) * 60
    assert model.minutes(a, b, 30, 10, when) == pytest.approx(expected)
    # 昼は速く、夜はさらに速い
    noon = model.minutes(a, b, 30, 10, datetime(2026, 11, 25, 12, 0))
    night = model.minutes(a, b, 30, 10, datetime(2026, 11, 25, 23, 0))
    assert night < noon < expected


def test_never_faster_than_free_flow():
    model = fixed_model(0)
    assert model.minutes((35.6, 139.7), (35.7, 139.7), 1, 30, datetime(2026, 11, 25, 23, 0)) == 30


def test_unknown_place_uses_fallback_area():
    model = SpeedModel(reverse=lambda lat, lon: None)
    assert model.area_at(35.0, 139.0) == speed.FALLBACK_AREA


class FakeOsrm(OsrmProvider):
    def __init__(self, model):
        super().__init__(base_url="http://osrm.invalid", factor=1.8)
        self.speed_model = model
        self.queries = []

    def access_points(self, points):
        return points

    def _get(self, path):
        self.queries.append(path)
        n = len(path.split("?")[0].rsplit("/", 1)[1].split(";"))
        sources = [int(x) for x in path.split("sources=")[1].split("&")[0].split(";")]
        destinations = [int(x) for x in path.split("destinations=")[1].split("&")[0].split(";")]
        assert max(sources + destinations) < n
        return {"code": "Ok", "durations": [[600.0] * len(destinations) for _ in sources],
                "distances": [[12000.0] * len(destinations) for _ in sources]}


def test_osrm_provider_uses_the_speed_model_with_departure_time():
    model = fixed_model(0)  # すべて特別区
    provider = FakeOsrm(model).at(datetime(2026, 11, 25, 8, 0), datetime(2026, 11, 25, 12, 0))
    out = provider.from_origin((35.69, 139.70), [(35.68, 139.71), (35.67, 139.72)])
    peak = 12 / AREAS["東京都（特別区）"]["peak"] * 60
    assert out == pytest.approx([peak, peak])
    assert "annotations=duration,distance" in provider.queries[0]
    back = provider.to_dest([(35.68, 139.71)], (35.69, 139.70))
    assert back == pytest.approx([12 / AREAS["東京都（特別区）"]["offpeak"] * 60])  # 目的地側は到着ごろの時間帯


def test_osrm_provider_without_dictionary_keeps_the_factor():
    provider = FakeOsrm(None)
    assert provider.between((35.69, 139.70), (35.68, 139.71)) == pytest.approx(10 * 1.8)
