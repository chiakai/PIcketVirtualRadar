import json
import math
import unittest

from picket_virtual_radar.config import OpenSkyConfig
from picket_virtual_radar.geometry import EARTH_RADIUS_KM, RadarGeometry
from picket_virtual_radar.opensky import (
    AuthenticationError,
    HttpResponse,
    OpenSkyClient,
    OpenSkyDataLayer,
    RateLimitError,
    TokenManager,
    bounding_box,
    parse_states,
)


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def request(self, url, **kwargs):
        self.requests.append((url, kwargs))
        return self.responses.pop(0)


def state(*, icao="abc123", callsign="TEST1 ", longitude=121.56, latitude=25.03, altitude=10000, velocity=200, heading=90):
    return [icao, callsign, "TW", 0, 1234567890, longitude, latitude, altitude, False, velocity, heading, 0, None, None, None, False, 0]


class OpenSkyTests(unittest.TestCase):
    def setUp(self):
        self.geometry = RadarGeometry(latitude=25.03, longitude=121.56, radius_km=50)
        self.config = OpenSkyConfig(client_id="id", client_secret="secret")

    def test_bounding_box_accounts_for_longitude_scale(self):
        box = bounding_box(RadarGeometry(latitude=60, longitude=10, radius_km=50))
        lat_span = box["lamax"] - box["lamin"]
        lon_span = box["lomax"] - box["lomin"]
        self.assertAlmostEqual(lon_span / lat_span, 2.0, places=2)

    def test_parse_filters_missing_and_outside_positions(self):
        far_latitude = 25.03 + math.degrees(60 / EARTH_RADIUS_KM)
        payload = {"time": 1, "states": [state(), state(icao="missing", latitude=None), state(icao="far", latitude=far_latitude)]}
        result = parse_states(json.dumps(payload).encode(), self.geometry)
        self.assertEqual([item.icao24 for item in result], ["abc123"])
        self.assertEqual(result[0].callsign, "TEST1")

    def test_parse_rejects_bad_schema(self):
        with self.assertRaises(Exception):
            parse_states(b'{"states":{}}', self.geometry)

    def test_token_is_cached_and_secret_is_only_in_post_body(self):
        clock = lambda: 100.0
        transport = FakeTransport([HttpResponse(200, b'{"access_token":"token","expires_in":1800}', {})])
        manager = TokenManager(self.config, transport, clock)
        self.assertEqual(manager.get(), "token")
        self.assertEqual(manager.get(), "token")
        self.assertEqual(len(transport.requests), 1)
        url, kwargs = transport.requests[0]
        self.assertNotIn("secret", url)
        self.assertIn(b"client_secret=secret", kwargs["data"])

    def test_client_uses_bearer_and_parses_states(self):
        responses = [
            HttpResponse(200, b'{"access_token":"token","expires_in":1800}', {}),
            HttpResponse(200, json.dumps({"states": [state()]}).encode(), {}),
        ]
        transport = FakeTransport(responses)
        client = OpenSkyClient(self.config, self.geometry, transport=transport, clock=lambda: 0)
        self.assertEqual(len(client.fetch()), 1)
        states_url, kwargs = transport.requests[1]
        self.assertIn("lamin=", states_url)
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer token")

    def test_rate_limit_retry_after(self):
        responses = [
            HttpResponse(200, b'{"access_token":"token","expires_in":1800}', {}),
            HttpResponse(429, b"", {"Retry-After": "42"}),
        ]
        client = OpenSkyClient(self.config, self.geometry, transport=FakeTransport(responses), clock=lambda: 0)
        with self.assertRaises(RateLimitError) as caught:
            client.fetch()
        self.assertEqual(caught.exception.retry_after, 42)

    def test_authentication_error_does_not_contain_secret(self):
        transport = FakeTransport([HttpResponse(401, b"denied", {})])
        with self.assertRaises(AuthenticationError) as caught:
            TokenManager(self.config, transport).get()
        self.assertNotIn("secret", str(caught.exception))

    def test_error_status_preserves_last_successful_aircraft(self):
        aircraft = parse_states(json.dumps({"states": [state()]}).encode(), self.geometry)
        layer = OpenSkyDataLayer(self.config, self.geometry)
        layer._set_status("OK", tuple(aircraft))
        layer._set_status("ERROR")
        snapshot = layer.snapshot()
        self.assertEqual(snapshot.status, "ERROR")
        self.assertEqual(snapshot.aircraft, tuple(aircraft))
        self.assertIsNotNone(snapshot.last_success_monotonic)

    def test_data_layer_updates_query_geometry(self):
        layer = OpenSkyDataLayer(self.config, self.geometry)
        updated = RadarGeometry(latitude=24.5, longitude=120.8, radius_km=30)
        layer.set_geometry(updated)
        self.assertIs(layer.client.geometry, updated)


if __name__ == "__main__":
    unittest.main()
