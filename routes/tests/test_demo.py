def test_index(client):
    res = client.get("/", HTTP_HOST="localhost")
    assert res.status_code == 200
    assert "予算内最速ルート" in res.content.decode()


def test_index_link_preview_uses_public_origin(client, settings):
    settings.ALLOWED_HOSTS = [".trycloudflare.com"]
    settings.SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    response = client.get("/?source=chat", HTTP_HOST="demo.trycloudflare.com", HTTP_X_FORWARDED_PROTO="https")

    assert response.status_code == 200
    html = response.content.decode()
    assert 'property="og:title" content="高速代の予算内最速ルート | tollroute"' in html
    assert 'property="og:description"' in html
    assert 'property="og:url" content="https://demo.trycloudflare.com/"' in html
    assert 'property="og:image" content="https://demo.trycloudflare.com/static/routes/link-preview.png"' in html


def test_search_weekday_noon(client):
    res = client.get("/api/search/", {"origin": "yokohama", "dest": "shinjuku",
                                      "depart": "2026-11-25T12:00", "budget": "1000"}, HTTP_HOST="localhost")
    data = res.json()
    assert res.status_code == 200
    assert data["best"]["fare"] <= 1000
    assert data["front"][-1]["entry"] is None  # いちばん安い候補は「高速を使わない」
    fares = [p["fare"] for p in data["front"]]
    assert fares == sorted(fares, reverse=True)  # 速い順に並び、料金は下がっていく


def test_search_bad_input(client, monkeypatch):
    from routes import geocode, views

    def not_found(text):
        raise geocode.AddressNotFound(f"住所が見つかりません: {text}")

    monkeypatch.setattr(views, "geocode", not_found)
    res = client.get("/api/search/", {"origin": "abc", "budget": "1000"}, HTTP_HOST="localhost")
    assert res.status_code == 400
    res = client.get("/api/search/", {"budget": "-1"}, HTTP_HOST="localhost")
    assert res.status_code == 400
    res = client.get("/api/search/", {"origin": "10.0,10.0"}, HTTP_HOST="localhost")
    assert res.status_code == 400


def test_search_by_address(client, monkeypatch):
    from routes import geocode, views

    monkeypatch.setattr(views, "geocode", lambda text: geocode.Place("神奈川県横浜市中区本町六丁目50番", 35.4668, 139.4985, 7))
    res = client.get("/api/search/", {"origin": "横浜市中区本町6-50-10", "dest": "shinjuku",
                                      "depart": "2026-11-25T12:00", "budget": "1000"}, HTTP_HOST="localhost")
    assert res.status_code == 200
    assert res.json()["origin"]["name"].startswith("神奈川県横浜市中区本町六丁目50番（街区・地番まで一致）")


def test_geocoder_unavailable(client, monkeypatch):
    from routes import geocode, views

    def unavailable(text):
        raise geocode.GeocoderUnavailable("住所の辞書が見つかりません")

    monkeypatch.setattr(views, "geocode", unavailable)
    res = client.get("/api/search/", {"origin": "横浜市中区本町6-50-10"}, HTTP_HOST="localhost")
    assert res.status_code == 503


def test_options_with_value(client):
    res = client.get("/api/search/", {"origin": "yokohama", "dest": "shinjuku",
                                      "depart": "2026-11-25T12:00", "budget": "1600"}, HTTP_HOST="localhost")
    data = res.json()
    opts = data["options"]
    assert 3 <= len(opts) <= 5
    assert all(o["fare"] <= 1600 for o in opts)
    assert opts[0]["label"] == "最速"
    assert len({(o["entry"], o["exit"]) for o in opts}) == len(opts)  # 同じルートを重ねない
    labels = [o["label"] for o in opts]
    assert "いちばんお得" in labels
    best_value = min(p["yen_per_min"] for p in data["front"] if p["yen_per_min"] is not None and p["fare"] <= 1600)
    assert next(o for o in opts if o["label"] == "いちばんお得")["yen_per_min"] == best_value
    for o in opts:
        assert o["nav"]["google"].startswith("https://www.google.com/maps/dir/?api=1")
        assert o["nav"]["yahoo"].startswith("yjcarnavi://navi/select?point=")
        assert o["nav"]["yahoo"].count("point=") <= 5


def test_zero_budget_has_no_options(client):
    res = client.get("/api/search/", {"origin": "yokohama", "dest": "shinjuku",
                                      "depart": "2026-11-25T12:00", "budget": "0"}, HTTP_HOST="localhost")
    assert res.json()["options"] == []


def test_falls_back_to_estimate_when_osrm_down(client, monkeypatch):
    from routes import travel

    class Down(travel.EstimateProvider):
        name = "osrm"

        def from_origin(self, origin, points):
            raise travel.TravelTimeError("ルート検索エンジン（OSRM）に接続できません: テスト")

    monkeypatch.setattr("routes.views.get_provider", lambda: Down())
    res = client.get("/api/search/", {"origin": "yokohama", "dest": "shinjuku",
                                      "depart": "2026-11-25T12:00", "budget": "1000"}, HTTP_HOST="localhost")
    assert res.status_code == 200
    assert any("概算に切り替えました" in n for n in res.json()["notes"])
