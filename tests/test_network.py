from unittest.mock import patch

import pytest
from django.test import Client, override_settings

from learning.network import lan_addresses, serving_addresses


def record(address):
    return (2, 1, 6, "", (address, 0))


def test_lan_is_explicit_and_addresses_are_private():
    with patch("learning.network.socket.getaddrinfo") as lookup:
        assert serving_addresses() == ["127.0.0.1"]
        lookup.assert_not_called()
        lookup.return_value = [
            record(ip)
            for ip in [
                "127.0.0.1",
                "192.168.1.20",
                "192.168.1.20",
                "10.0.0.5",
                "169.254.1.1",
                "8.8.8.8",
            ]
        ]
        assert lan_addresses() == ["10.0.0.5", "192.168.1.20"]
        assert serving_addresses(True, "192.168.1.20") == ["127.0.0.1", "192.168.1.20"]
        with pytest.raises(ValueError):
            serving_addresses(False, "192.168.1.20")
        with pytest.raises(ValueError):
            serving_addresses(True, "0.0.0.0")
        lookup.return_value = [record("127.0.0.1")]
        with pytest.raises(ValueError, match="No private"):
            serving_addresses(True)


@pytest.mark.django_db
def test_lan_host_and_same_origin_csrf(profile, entries, settings):
    settings.STORAGES = {
        **settings.STORAGES,
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
    client = Client(enforce_csrf_checks=True)
    with override_settings(ALLOWED_HOSTS=["127.0.0.1", "192.168.1.20"]):
        assert client.get("/", HTTP_HOST="192.168.1.20:8765").status_code == 200
        assert client.get("/", HTTP_HOST="untrusted.example").status_code == 400
        url = f"/word/{entries[0].pk}/bookmark/"
        assert client.post(url, HTTP_HOST="192.168.1.20:8765").status_code == 403
        token = client.cookies["csrftoken"].value
        assert (
            client.post(
                url,
                HTTP_HOST="192.168.1.20:8765",
                HTTP_ORIGIN="http://192.168.1.20:8765",
                HTTP_X_CSRFTOKEN=token,
            ).status_code
            == 302
        )
        assert (
            client.post(
                url,
                HTTP_HOST="192.168.1.20:8765",
                HTTP_ORIGIN="http://untrusted.example",
                HTTP_X_CSRFTOKEN=token,
            ).status_code
            == 403
        )
