"""検索 API の入力チェックと、日時まわりの不具合の回帰テスト。"""
import pytest
from django.test import override_settings

SEARCH = override_settings(SEARCH_RATE_LIMIT_PER_MIN=0, GOOGLE_ROUTES_API_KEY="")


def search(client, **params):
    return client.get("/api/search/", {"budget": "3000", **params}, HTTP_HOST="localhost")


@SEARCH
@pytest.mark.parametrize("depart", ["2026-11-28T07:00+09:00", "2026-11-27T22:00Z"])
def test_departure_with_timezone_is_read_as_japan_time(client, depart):
    response = search(client, depart=depart)
    assert response.status_code == 200
    assert response.json()["depart"] == "2026-11-28 07:00"


@SEARCH
@pytest.mark.parametrize("depart", ["9999-12-31T23:00", "0001-01-01T00:30", "1990-01-01T07:00", "tomorrow"])
def test_unusable_departure_is_a_bad_request(client, depart):
    assert search(client, depart=depart).status_code == 400


@SEARCH
@pytest.mark.parametrize("budget", ["NaN", "-1", "99999999"])
def test_bad_budget_is_a_bad_request(client, budget):
    response = search(client, budget=budget)
    assert response.status_code == 400
    assert "予算" in response.json()["error"]


@SEARCH
@pytest.mark.parametrize("origin", ["43.06,141.35", "27.09,142.19"])
def test_points_far_from_the_demo_network_are_rejected(client, origin):
    response = search(client, origin=origin)
    assert response.status_code == 400
    assert "対応範囲" in response.json()["error"]


@SEARCH
def test_now_search_never_suggests_leaving_earlier(client):
    for depart in ["2026-11-25T04:20", "2026-11-25T00:30", "2026-11-28T05:00"]:
        for origin in ["hachioji", "yokohama", "machida"]:
            data = search(client, origin=origin, depart=depart, now="1", budget="5000").json()
            assert data["shift"] is None or data["shift"]["offset"] > 0


@SEARCH
def test_unregistered_holiday_calendar_is_flagged(client):
    data = search(client, depart="2027-05-03T12:00").json()
    assert data["approximate"] is True
    assert any("適用除外日" in note for note in data["notes"])


@SEARCH
def test_arrival_after_midnight_says_next_day(client):
    data = search(client, origin="hachioji", depart="2026-11-25T23:50").json()
    assert data["local_only"]["arrive"].startswith("翌日 ")
