import io
import json
from unittest.mock import patch
from urllib.error import HTTPError

import pytest
from django.test import override_settings

from routes import demo, views

ORIGIN = demo.PLACES["yokohama"][1:]
DEST = demo.PLACES["shinjuku"][1:]
GOOGLE = override_settings(GOOGLE_ROUTES_API_KEY="test-key", SEARCH_RATE_LIMIT_PER_MIN=0, GOOGLE_ROUTES_DAILY_SEARCHES=0)


def route(name, seconds, yen=None, path=None, unknown=False):
    body = {"description": name, "duration": f"{seconds}s", "distanceMeters": 34500,
            "polyline": {"encodedPolyline": path or name}}
    if unknown:
        body["travelAdvisory"] = {"tollInfo": {}}
    elif yen is not None:
        body["travelAdvisory"] = {"tollInfo": {"estimatedPrice": [{"currencyCode": "JPY", "units": str(yen)}]}}
    return body


def local_route(payload):
    return [route("一般道の区間", 600, path="local" + json.dumps(payload["destination"]))]


class FakeGoogle:
    """問い合わせの種類ごとに決まった応答を返す。スレッドから呼ばれても順序に依存しない。

    種類: normal / free（出発地→目的地）、to_entry / from_exit（案の一般道の区間）、highway（案の高速の区間）
    """

    def __init__(self, normal, free=(), highway=lambda payload: [], local=local_route, fail=()):
        self.normal, self.free, self.highway, self.local, self.fail = normal, free, highway, local, fail
        self.payloads = []

    @staticmethod
    def kind(payload):
        o = payload["origin"]["location"]["latLng"]
        d = payload["destination"]["location"]["latLng"]
        is_o = (o["latitude"], o["longitude"]) == ORIGIN
        is_d = (d["latitude"], d["longitude"]) == DEST
        if is_o and is_d:
            return "free" if payload["routeModifiers"].get("avoidTolls") else "normal"
        if is_o:
            return "to_entry"
        if is_d:
            return "from_exit"
        return "highway"

    def __call__(self, request, timeout):
        payload = json.loads(request.data)
        self.payloads.append(payload)
        kind = self.kind(payload)
        if kind in self.fail:
            raise HTTPError(request.full_url, 500, "error", {}, None)
        if kind == "normal":
            routes = self.normal
        elif kind == "free":
            routes = self.free
        elif kind == "highway":
            routes = self.highway(payload)
        else:
            routes = self.local(payload)
        return io.BytesIO(json.dumps({"routes": list(routes)}).encode())

    def kinds(self):
        return [self.kind(p) for p in self.payloads]


@pytest.fixture(autouse=True)
def _reset_quota():
    views._google_quota.update(day=None, used=0)


@pytest.fixture
def local_sides(monkeypatch):
    """OSRM の代わりに、IC の座標を少しずらした点を「IC のそばの一般道の地点」にする。"""
    monkeypatch.setattr(views, "local_side", lambda provider, nodes: {
        n.id: (round(n.lat + 0.001, 6), round(n.lon, 6)) for n in nodes})


def highway_by_entry(payload):
    """案ごとに料金と時間を変える（速いほど高い）。"""
    o = payload["origin"]["location"]["latLng"]
    seed = int(o["latitude"] * 1e4) % 7
    return [route(f"高速{seed}", 1200 - seed * 60, 300 + seed * 40,
                  path="hw" + json.dumps(payload["origin"]) + json.dumps(payload["destination"]))]


@GOOGLE
def test_picks_fastest_route_within_budget_from_google_tolls(client):
    fake = FakeGoogle(
        normal=[route("料金不明の高速", 2100, unknown=True), route("予算超過の高速", 2200, 1100),
                route("第三京浜道路", 2592, 790)],
        free=[route("一般道", 4200, path="free")],
    )
    with patch("routes.google_routes.urlopen", side_effect=fake):
        response = client.get("/api/search/", {"budget": 1000}, HTTP_HOST="localhost")

    assert response.status_code == 200
    assert response["Cache-Control"] == "no-store"
    assert b"test-key" not in response.content
    normal = next(p for p in fake.payloads if fake.kind(p) == "normal")
    assert "departureTime" not in normal
    assert normal["routeModifiers"]["tollPasses"] == ["JP_ETC"]
    assert normal["extraComputations"] == ["TOLLS"]
    data = response.json()
    assert data["best"]["description"] == "第三京浜道路"
    assert data["best"]["minutes"] == 43.2
    assert data["routes"][0]["fare"] is None  # 料金の分かる最速より速いので参考として残る
    assert data["routes"][-1]["fare"] == 0
    assert data["cheapest_index"] == len(data["routes"]) - 1


@GOOGLE
def test_engine_ic_hints_add_middle_routes(client, local_sides):
    """Google 自身は「全部高速」と「一般道」しか返さなくても、IC を指定した中間の案が加わる。"""
    fake = FakeGoogle(normal=[route("高速", 2400, 1300)], free=[route("一般道", 4200, path="free")],
                      highway=highway_by_entry)
    with patch("routes.google_routes.urlopen", side_effect=fake):
        data = client.get("/api/search/", {"budget": 1000}, HTTP_HOST="localhost").json()

    kinds = fake.kinds()
    assert kinds.count("highway") >= 2 and "to_entry" in kinds and "from_exit" in kinds
    for payload in fake.payloads:
        kind = fake.kind(payload)
        if kind in ("to_entry", "from_exit"):
            assert payload["routeModifiers"]["avoidTolls"] is True  # 一般道の区間は有料道路を避ける
        if kind not in ("normal", "free"):
            assert payload["computeAlternativeRoutes"] is False
    middle = [r for r in data["routes"] if r["source"] == "ic"]
    assert middle and all(300 <= r["fare"] < 1300 for r in middle)
    assert all("から乗る案" in r["description"] and "waypoints=" in r["nav"]["google"] for r in middle)
    assert data["best"]["source"] == "ic"  # 予算 1,000 円の最速は中間の案
    fares = [r["fare"] for r in data["routes"]]
    assert fares == sorted(fares, reverse=True)  # 速い候補ほど高い（優劣のない候補だけ）


@GOOGLE
def test_highway_leg_departs_when_the_car_reaches_the_entry(client, local_sides):
    fake = FakeGoogle(normal=[route("高速", 2400, 790)], free=[route("一般道", 4200, path="free")],
                      highway=highway_by_entry)
    with patch("routes.google_routes.urlopen", side_effect=fake):
        client.get("/api/search/", {"budget": 1000, "depart": "2030-01-08T23:50"}, HTTP_HOST="localhost")
    starts = {}
    for payload in fake.payloads:
        starts.setdefault(fake.kind(payload), payload["departureTime"])
    assert starts["normal"].startswith("2030-01-08T23:50")
    assert starts["highway"].startswith("2030-01-09T00:00")  # 一般道の区間 10 分のあと


@GOOGLE
def test_plan_whose_local_leg_uses_tolls_is_dropped(client, local_sides):
    fake = FakeGoogle(normal=[route("高速", 2400, 790)], free=[route("一般道", 4200, path="free")],
                      highway=highway_by_entry,
                      local=lambda payload: [route("有料を通る区間", 300, 100, path="t" + json.dumps(payload["destination"]))])
    with patch("routes.google_routes.urlopen", side_effect=fake):
        data = client.get("/api/search/", {"budget": 1000}, HTTP_HOST="localhost").json()
    assert [r["description"] for r in data["routes"]] == ["高速", "一般道"]


@GOOGLE
def test_auxiliary_failures_still_return_google_routes(client, local_sides):
    fake = FakeGoogle(normal=[route("高速", 2400, 790)], fail=("free", "highway"))
    with patch("routes.google_routes.urlopen", side_effect=fake):
        data = client.get("/api/search/", {"budget": 1000}, HTTP_HOST="localhost").json()
    assert data["low_cost_search_failed"] is True
    assert [r["fare"] for r in data["routes"]] == [790]


@GOOGLE
def test_main_failure_falls_back_to_engine(client):
    fake = FakeGoogle(normal=[], fail=("normal",))
    with patch("routes.google_routes.urlopen", side_effect=fake):
        response = client.get("/api/search/", {"budget": 1000}, HTTP_HOST="localhost")
    assert response.status_code == 200
    data = response.json()
    assert "provider" not in data and data["options"]  # 自作エンジンの結果で答える
    assert any("Google の経路を取得できなかった" in note for note in data["notes"])


@GOOGLE
def test_rejects_past_departure_without_calling_api(client):
    with patch("routes.google_routes.urlopen") as fetch:
        response = client.get("/api/search/", {"depart": "2000-01-01T12:00"}, HTTP_HOST="localhost")
    assert response.status_code == 400
    fetch.assert_not_called()


@override_settings(GOOGLE_ROUTES_API_KEY="test-key", SEARCH_RATE_LIMIT_PER_MIN=0, GOOGLE_ROUTES_DAILY_SEARCHES=1)
def test_daily_limit_falls_back_to_engine(client):
    fake = FakeGoogle(normal=[route("高速", 2400, 790)])
    with patch("routes.google_routes.urlopen", side_effect=fake):
        first = client.get("/api/search/", {"budget": 1000}, HTTP_HOST="localhost").json()
        calls = len(fake.payloads)
        second = client.get("/api/search/", {"budget": 1000}, HTTP_HOST="localhost").json()
    assert first["provider"] == "google_routes"
    assert "provider" not in second and second["options"]
    assert len(fake.payloads) == calls
    assert any("上限" in note for note in second["notes"])


def test_google_hints_cover_a_range_of_fares(local_sides):
    from datetime import datetime

    from engine.search import Searcher
    from routes.travel import EstimateProvider

    net, tariffs, _ = demo.build()
    depart = datetime(2026, 11, 25, 12, 0)
    times = views.local_times(EstimateProvider(), net, ORIGIN, DEST)
    front = views._search(Searcher(net, tariffs), depart, times)
    hints = views.google_hints(front, net, 1000, depart, None)
    assert 2 <= len(hints) <= views.GOOGLE_HINTS
    assert len(set(hints)) == len(hints)
    assert len({h.info["engine_fare"] for h in hints}) >= 2
    assert all(h.to_exit_min > 0 for h in hints)
