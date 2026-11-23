import pytest


@pytest.fixture(autouse=True)
def _estimate_travel_times(monkeypatch):
    """テストはルート検索エンジン（OSRM）に依存させない。概算で動かす。"""
    monkeypatch.setenv("TRAVEL_TIME_PROVIDER", "estimate")
