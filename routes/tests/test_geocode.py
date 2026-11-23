"""駅名検索（HeartRails Express）と住所検索の振り分け。ネットワークには出ない（HTTP 呼び出しを差し替える）。"""
import io
import json
import urllib.error

import pytest

from routes import geocode as g

SHINJUKU_SANCHOME = {"name": "新宿三丁目", "prefecture": "東京都", "line": "東京メトロ丸ノ内線",
                     "x": 139.704553, "y": 35.690853, "postal": "1600022", "prev": "新宿御苑前", "next": "新宿"}
FUCHU = [
    {"name": "府中", "prefecture": "東京都", "line": "京王線", "x": 139.479887, "y": 35.672245},
    {"name": "府中", "prefecture": "広島県", "line": "JR福塩線", "x": 133.235818, "y": 34.570046},
    {"name": "府中本町", "prefecture": "東京都", "line": "JR南武線", "x": 139.477142, "y": 35.665885},
]


@pytest.fixture(autouse=True)
def fake_api(monkeypatch):
    """_fetch_stations を差し替え、呼ばれた駅名を記録する。"""
    calls = []
    table = {"新宿三丁目": [SHINJUKU_SANCHOME], "府中": FUCHU, "新宿": [
        {"name": "新宿", "prefecture": "東京都", "line": "JR山手線", "x": 139.700464, "y": 35.689729}]}

    def fake(name):
        calls.append(name)
        return table.get(name, [])

    g.clear_cache()
    monkeypatch.setattr(g, "_fetch_stations", fake)
    yield calls
    g.clear_cache()


def address_not_found(monkeypatch):
    def nf(text):
        raise g.AddressNotFound(f"住所が見つかりません: {text}")

    monkeypatch.setattr(g, "geocode_address", nf)


def test_station_name_with_eki(fake_api, monkeypatch):
    monkeypatch.setattr(g, "geocode_address", lambda t: pytest.fail("住所検索は呼ばれないはず"))
    p = g.geocode("新宿三丁目駅")
    assert p.name == "新宿三丁目駅"
    assert p.level == g.STATION_LEVEL and p.level_label == "駅"
    assert (p.lat, p.lon) == (35.690853, 139.704553)
    assert p.detail == "東京都 東京メトロ丸ノ内線"
    assert p.others == ()
    assert fake_api == ["新宿三丁目"]  # 送るのは「駅」を除いた駅名だけ


def test_cache(fake_api):
    g.geocode("新宿三丁目駅")
    g.geocode(" 新宿三丁目駅 ")
    assert fake_api == ["新宿三丁目"]


def test_exact_match_and_others(fake_api):
    p = g.geocode("府中駅")
    assert p.name == "府中駅"
    assert p.detail == "東京都 京王線"
    assert p.others == ("広島県 JR福塩線",)  # 府中本町は完全一致ではないので入らない


def test_station_not_found(monkeypatch):
    monkeypatch.setattr(g, "geocode_address", lambda t: pytest.fail("住所検索は呼ばれないはず"))
    with pytest.raises(g.AddressNotFound, match="駅が見つかりません"):
        g.geocode("存在しない駅")


def test_short_text_falls_back_to_station(fake_api, monkeypatch):
    address_not_found(monkeypatch)
    p = g.geocode("新宿")
    assert p.name == "新宿駅" and p.level == g.STATION_LEVEL


def test_short_text_not_station_keeps_address_error(monkeypatch):
    address_not_found(monkeypatch)
    with pytest.raises(g.AddressNotFound, match="住所が見つかりません"):
        g.geocode("あいうえお")


def test_address_is_not_sent(fake_api, monkeypatch):
    address_not_found(monkeypatch)
    with pytest.raises(g.AddressNotFound):
        g.geocode("新宿区歌舞伎町1-4-1")
    assert fake_api == []  # 番地を含む入力は駅名検索に送らない


def test_address_first(fake_api, monkeypatch):
    place = g.Place("東京都新宿区西新宿二丁目", 35.69, 139.67, 6)
    monkeypatch.setattr(g, "geocode_address", lambda t: place)
    assert g.geocode("新宿区西新宿2") is place
    assert fake_api == []


def test_no_dictionary_short_text_uses_station(monkeypatch):
    def unavailable(text):
        raise g.GeocoderUnavailable("住所の辞書が見つかりません")

    monkeypatch.setattr(g, "geocode_address", unavailable)
    assert g.geocode("新宿").name == "新宿駅"
    with pytest.raises(g.GeocoderUnavailable):
        g.geocode("横浜市中区本町6-50-10")


def test_looks_like_station():
    assert g.looks_like_station("新宿三丁目駅")
    assert g.looks_like_station("センター北駅")
    assert not g.looks_like_station("新宿三丁目駅前")
    assert not g.looks_like_station("駅")
    assert not g.looks_like_station("新宿区新宿3-1駅")


# ---- HTTP 呼び出しそのもの（urlopen を差し替える） ----

class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def test_fetch_stations_request(monkeypatch):
    monkeypatch.undo()  # fake_api の差し替えを戻し、本物の _fetch_stations を使う
    seen = {}

    def urlopen(req, timeout):
        seen["url"], seen["ua"], seen["timeout"] = req.full_url, req.get_header("User-agent"), timeout
        return FakeResponse(json.dumps({"response": {"station": [SHINJUKU_SANCHOME]}}).encode())

    monkeypatch.setattr(g.urllib.request, "urlopen", urlopen)
    assert g._fetch_stations("新宿三丁目") == [SHINJUKU_SANCHOME]
    assert seen["url"] == ("https://express.heartrails.com/api/json?method=getStations"
                           "&name=%E6%96%B0%E5%AE%BF%E4%B8%89%E4%B8%81%E7%9B%AE")
    assert seen["ua"] == "tollroute/0.1"
    assert seen["timeout"] == 3.0


def test_fetch_stations_not_found(monkeypatch):
    monkeypatch.undo()
    body = {"response": {"error": "Station 'xxx' not found."}}
    monkeypatch.setattr(g.urllib.request, "urlopen", lambda req, timeout: FakeResponse(json.dumps(body).encode()))
    assert g._fetch_stations("xxx") == []


def test_fetch_stations_network_error(monkeypatch):
    monkeypatch.undo()

    def boom(req, timeout):
        raise urllib.error.URLError("timed out")

    monkeypatch.setattr(g.urllib.request, "urlopen", boom)
    with pytest.raises(g.StationLookupUnavailable, match="駅名検索"):
        g._fetch_stations("新宿三丁目")
    # 「駅」で終わる入力なら、そのまま 503 用のエラーになる
    g.clear_cache()
    with pytest.raises(g.GeocoderUnavailable):
        g.geocode("新宿三丁目駅")


# ---- ビュー ----

def test_api_search_by_station(client):
    res = client.get("/api/search/", {"origin": "yokohama", "dest": "新宿三丁目駅",
                                      "depart": "2026-11-25T12:00", "budget": "1000"}, HTTP_HOST="localhost")
    assert res.status_code == 200
    assert res.json()["dest"]["name"] == "新宿三丁目駅（駅）"


def test_api_search_station_errors(client, monkeypatch):
    res = client.get("/api/search/", {"origin": "存在しない駅"}, HTTP_HOST="localhost")
    assert res.status_code == 400
    assert "駅が見つかりません" in res.json()["error"]

    def down(name):
        raise g.StationLookupUnavailable("駅名検索（HeartRails Express）に接続できませんでした。")

    monkeypatch.setattr(g, "_fetch_stations", down)
    res = client.get("/api/search/", {"origin": "渋谷駅"}, HTTP_HOST="localhost")
    assert res.status_code == 503
    assert "駅名検索" in res.json()["error"]


def test_same_name_station_prefers_kanto(monkeypatch):
    from routes import geocode

    geocode.clear_cache()
    monkeypatch.setattr(geocode, "_fetch_stations", lambda name: [
        {"name": "府中", "x": 134.43, "y": 34.05, "prefecture": "徳島県", "line": "JR徳島線"},
        {"name": "府中", "x": 139.4795, "y": 35.6720, "prefecture": "東京都", "line": "京王線"},
    ])
    place = geocode.geocode_station("府中駅")
    assert place.detail.startswith("東京都")
    assert "徳島県" in place.others[0]
