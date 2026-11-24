import io
import json
from unittest.mock import patch
from urllib.error import HTTPError

import pytest
from django.test import override_settings

from routes import views

GOOGLE = override_settings(GOOGLE_ROUTES_API_KEY="test-key", SEARCH_RATE_LIMIT_PER_MIN=0, GOOGLE_ROUTES_DAILY_SEARCHES=0)


def route(name, seconds, yen=None, path=None, unknown=False):
    body = {"description": name, "duration": f"{seconds}s", "distanceMeters": 34500,
            "polyline": {"encodedPolyline": path or name}}
    if unknown:
        body["travelAdvisory"] = {"tollInfo": {}}
    elif yen is not None:
        body["travelAdvisory"] = {"tollInfo": {"estimatedPrice": [{"currencyCode": "JPY", "units": str(yen)}]}}
    return body


class FakeGoogle:
    """問い合わせの種類（通常・有料回避・経由地あり）ごとに決まった応答を返す。スレッドから呼ばれても順序に依存しない。"""

    def __init__(self, normal, free=(), via=lambda payload: [], fail=()):
        self.normal, self.free, self.via, self.fail = normal, free, via, fail
        self.payloads = []

    def __call__(self, request, timeout):
        payload = json.loads(request.data)
        self.payloads.append(payload)
        kind = ("via" if "intermediates" in payload else
                "free" if payload["routeModifiers"].get("avoidTolls") else "normal")
        if kind in self.fail:
            raise HTTPError(request.full_url, 500, "error", {}, None)
        routes = {"normal": self.normal, "free": self.free}.get(kind) or (
            self.via(payload) if kind == "via" else [])
        return io.BytesIO(json.dumps({"routes": list(routes)}).encode())

    def kinds(self):
        return sorted("via" if "intermediates" in p else "free" if p["routeModifiers"].get("avoidTolls") else "normal"
                      for p in self.payloads)


@pytest.fixture(autouse=True)
def _reset_quota():
    views._google_quota.update(day=None, used=0)


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
    normal = next(p for p in fake.payloads if "intermediates" not in p and not p["routeModifiers"].get("avoidTolls"))
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
def test_engine_ic_hints_add_middle_routes(client):
    """Google 自身は「全部高速」と「一般道」しか返さなくても、IC を指定した中間の案が加わる。"""
    def via(payload):
        n = len(fake.payloads)
        return [route(f"経由案{n}", 3000 - n * 10, 300 + n * 10, path=f"via{n}")]

    fake = FakeGoogle(normal=[route("高速", 2400, 1300)], free=[route("一般道", 4200, path="free")], via=via)
    with patch("routes.google_routes.urlopen", side_effect=fake):
        data = client.get("/api/search/", {"budget": 1000}, HTTP_HOST="localhost").json()

    assert fake.kinds().count("via") >= 2
    for payload in fake.payloads:
        if "intermediates" in payload:
            assert payload["computeAlternativeRoutes"] is False
            assert all(point["via"] for point in payload["intermediates"])
    middle = [r for r in data["routes"] if r["source"] == "ic"]
    assert middle and all(0 < r["fare"] < 1300 for r in middle)
    assert all("→" in r["description"] and "waypoints=" in r["nav"]["google"] for r in middle)
    assert data["best"]["source"] == "ic"  # 予算 1,000 円の最速は中間の案
    fares = [r["fare"] for r in data["routes"]]
    assert fares == sorted(fares, reverse=True)  # 速い候補ほど高い（優劣のない候補だけ）
    assert data["balance_index"] is None or data["routes"][data["balance_index"]]["source"] == "ic"


@GOOGLE
def test_via_result_that_skips_the_highway_is_dropped(client):
    fake = FakeGoogle(normal=[route("高速", 2400, 790)], free=[route("一般道", 4200, path="free")],
                      via=lambda payload: [route("素通り", 3500, path="skip")])
    with patch("routes.google_routes.urlopen", side_effect=fake):
        data = client.get("/api/search/", {"budget": 1000}, HTTP_HOST="localhost").json()
    assert [r["description"] for r in data["routes"]] == ["高速", "一般道"]


@GOOGLE
def test_auxiliary_failures_still_return_google_routes(client):
    fake = FakeGoogle(normal=[route("高速", 2400, 790)], fail=("free", "via"))
    with patch("routes.google_routes.urlopen", side_effect=fake):
        data = client.get("/api/search/", {"budget": 1000}, HTTP_HOST="localhost").json()
    assert data["low_cost_search_failed"] is True
    assert [r["fare"] for r in data["routes"]] == [790]


@GOOGLE
def test_main_failure_is_reported(client):
    fake = FakeGoogle(normal=[], fail=("normal",))
    with patch("routes.google_routes.urlopen", side_effect=fake):
        response = client.get("/api/search/", {"budget": 1000}, HTTP_HOST="localhost")
    assert response.status_code == 502


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


def test_google_hints_cover_a_range_of_fares():
    from datetime import datetime

    from engine.search import Searcher
    from routes import demo
    from routes.travel import EstimateProvider

    net, tariffs, _ = demo.build()
    o, d = demo.PLACES["yokohama"][1:], demo.PLACES["shinjuku"][1:]
    times = views.local_times(EstimateProvider(), net, o, d)
    front = views._search(Searcher(net, tariffs), datetime(2026, 11, 25, 12, 0), times)
    hints = views.google_hints(front, net, 1000)
    assert 2 <= len(hints) <= views.GOOGLE_HINTS
    keys = [(h["entry"], h["exit"], tuple(via)) for via, h in hints]
    assert len(set(keys)) == len(keys)
    fares = {h["engine_fare"] for _, h in hints}
    assert len(fares) >= 2
    assert all(len(via) >= 1 for via, _ in hints)
