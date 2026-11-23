import pytest


@pytest.mark.django_db
def test_health(client):
    response = client.get("/health/", HTTP_HOST="localhost")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert isinstance(data["postgis"], str)
    assert data["postgis"]
