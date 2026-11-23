"""公開（Cloudflare のクイックトンネル）向けの設定のテスト。"""
import pytest
from django.test import override_settings

from routes import ratelimit


@pytest.fixture(autouse=True)
def _reset_limits():
    ratelimit.reset()
    yield
    ratelimit.reset()


@override_settings(SEARCH_RATE_LIMIT_PER_MIN=2)
def test_search_is_rate_limited_per_client(client):
    params = {"depart": "2026-11-25T12:00", "budget": "1000"}
    assert client.get("/api/search/", params, HTTP_HOST="localhost", HTTP_CF_CONNECTING_IP="203.0.113.1").status_code == 200
    assert client.get("/api/search/", params, HTTP_HOST="localhost", HTTP_CF_CONNECTING_IP="203.0.113.1").status_code == 200
    res = client.get("/api/search/", params, HTTP_HOST="localhost", HTTP_CF_CONNECTING_IP="203.0.113.1")
    assert res.status_code == 429 and "Retry-After" in res
    # 別の接続元は数えない
    assert client.get("/api/search/", params, HTTP_HOST="localhost", HTTP_CF_CONNECTING_IP="203.0.113.2").status_code == 200


def test_admin_only_when_enabled():
    import importlib

    import config.urls

    try:
        with override_settings(ENABLE_ADMIN=False):
            importlib.reload(config.urls)
            assert not any(str(p.pattern) == "admin/" for p in config.urls.urlpatterns)
        with override_settings(ENABLE_ADMIN=True):
            importlib.reload(config.urls)
            assert any(str(p.pattern) == "admin/" for p in config.urls.urlpatterns)
    finally:
        importlib.reload(config.urls)
