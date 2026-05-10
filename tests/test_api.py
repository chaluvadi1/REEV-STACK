"""
tests/test_api.py

pytest test suite for the FastAPI server.
Uses FastAPI's TestClient (no real server needed).

Run: pytest tests/test_api.py -v
"""

import pytest
from fastapi.testclient import TestClient

from api.main import app


# ---------------------------------------------------------------------------
# Client fixture — spins up the app in-process
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Root + health
# ---------------------------------------------------------------------------

class TestRoot:
    def test_root_ok(self, client):
        r = client.get("/")
        assert r.status_code == 200
        assert r.json()["project"] == "REEV Stack"
        assert r.json()["status"] == "ok"

    def test_docs_reachable(self, client):
        r = client.get("/docs")
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# GET /api/v1/vehicle/state
# ---------------------------------------------------------------------------

class TestGetState:
    def test_returns_200(self, client):
        r = client.get("/api/v1/vehicle/state")
        assert r.status_code == 200

    def test_required_fields_present(self, client):
        d = client.get("/api/v1/vehicle/state").json()
        required = {
            "battery_soc_pct", "battery_kwh", "speed_kmh",
            "mode", "ev_range_km", "total_range_km",
            "fuel_level_pct", "odometer_km", "timestamp",
        }
        assert required.issubset(d.keys())

    def test_initial_soc_is_80(self, client):
        d = client.get("/api/v1/vehicle/state").json()
        assert abs(d["battery_soc_pct"] - 80.0) < 0.01

    def test_soc_in_valid_range(self, client):
        d = client.get("/api/v1/vehicle/state").json()
        assert 0 <= d["battery_soc_pct"] <= 100

    def test_mode_is_valid_string(self, client):
        d = client.get("/api/v1/vehicle/state").json()
        valid_modes = {"EV_ONLY", "HYBRID", "COASTING", "CHARGING"}
        assert d["mode"] in valid_modes


# ---------------------------------------------------------------------------
# GET /api/v1/config
# ---------------------------------------------------------------------------

class TestGetConfig:
    def test_returns_200(self, client):
        r = client.get("/api/v1/config")
        assert r.status_code == 200

    def test_config_fields(self, client):
        d = client.get("/api/v1/config").json()
        assert d["battery_capacity_kwh"] == 18.0
        assert d["motor_peak_kw"] == 100.0
        assert d["hybrid_threshold_soc_pct"] == 20.0

    def test_config_has_name(self, client):
        d = client.get("/api/v1/config").json()
        assert isinstance(d["name"], str)
        assert len(d["name"]) > 0


# ---------------------------------------------------------------------------
# POST /api/v1/vehicle/drive
# ---------------------------------------------------------------------------

class TestDrive:
    def test_basic_drive_step(self, client):
        r = client.post("/api/v1/vehicle/drive", json={"speed_kmh": 80.0})
        assert r.status_code == 200

    def test_drive_returns_state(self, client):
        d = client.post("/api/v1/vehicle/drive", json={"speed_kmh": 60.0}).json()
        assert "battery_soc_pct" in d
        assert "mode" in d

    def test_drive_depletes_battery(self, client):
        initial = client.get("/api/v1/vehicle/state").json()["battery_soc_pct"]
        for _ in range(100):
            client.post("/api/v1/vehicle/drive", json={"speed_kmh": 100.0})
        after = client.get("/api/v1/vehicle/state").json()["battery_soc_pct"]
        assert after < initial

    def test_drive_with_acceleration(self, client):
        r = client.post("/api/v1/vehicle/drive", json={
            "speed_kmh": 50.0,
            "acceleration_ms2": 2.0,
        })
        assert r.status_code == 200

    def test_drive_with_grade(self, client):
        r = client.post("/api/v1/vehicle/drive", json={
            "speed_kmh": 60.0,
            "grade_pct": 8.0,
        })
        assert r.status_code == 200

    def test_drive_invalid_speed_rejected(self, client):
        r = client.post("/api/v1/vehicle/drive", json={"speed_kmh": 999.0})
        assert r.status_code == 422  # Unprocessable Entity

    def test_drive_negative_speed_rejected(self, client):
        r = client.post("/api/v1/vehicle/drive", json={"speed_kmh": -10.0})
        assert r.status_code == 422

    def test_odometer_increments(self, client):
        client.post("/api/v1/vehicle/reset", json={})
        before = client.get("/api/v1/vehicle/state").json()["odometer_km"]
        for _ in range(10):
            client.post("/api/v1/vehicle/drive", json={"speed_kmh": 90.0})
        after = client.get("/api/v1/vehicle/state").json()["odometer_km"]
        assert after > before


# ---------------------------------------------------------------------------
# POST /api/v1/vehicle/charge
# ---------------------------------------------------------------------------

class TestCharge:
    def test_charge_increases_soc(self, client):
        # First deplete a bit
        for _ in range(200):
            client.post("/api/v1/vehicle/drive", json={"speed_kmh": 100.0})
        before = client.get("/api/v1/vehicle/state").json()["battery_soc_pct"]

        client.post("/api/v1/vehicle/charge", json={
            "power_kw": 11.0,
            "duration_minutes": 60.0,
        })
        after = client.get("/api/v1/vehicle/state").json()["battery_soc_pct"]
        assert after > before

    def test_charge_mode_in_response(self, client):
        d = client.post("/api/v1/vehicle/charge", json={
            "power_kw": 7.4,
            "duration_minutes": 30.0,
        }).json()
        assert d["mode"] == "CHARGING"

    def test_charge_invalid_power_rejected(self, client):
        r = client.post("/api/v1/vehicle/charge", json={
            "power_kw": 0.0,       # below minimum of 1.0
            "duration_minutes": 30,
        })
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# POST /api/v1/vehicle/reset
# ---------------------------------------------------------------------------

class TestReset:
    def test_reset_default(self, client):
        # Deplete first
        for _ in range(300):
            client.post("/api/v1/vehicle/drive", json={"speed_kmh": 120.0})
        assert client.get("/api/v1/vehicle/state").json()["battery_soc_pct"] < 80.0

        r = client.post("/api/v1/vehicle/reset", json={})
        assert r.status_code == 200
        assert r.json()["ok"] is True

        soc = client.get("/api/v1/vehicle/state").json()["battery_soc_pct"]
        assert abs(soc - 80.0) < 0.01

    def test_reset_custom_soc(self, client):
        client.post("/api/v1/vehicle/reset", json={"initial_soc": 0.50})
        soc = client.get("/api/v1/vehicle/state").json()["battery_soc_pct"]
        assert abs(soc - 50.0) < 0.01

    def test_reset_invalid_soc_rejected(self, client):
        r = client.post("/api/v1/vehicle/reset", json={"initial_soc": 1.5})
        assert r.status_code == 422

    def test_reset_clears_odometer(self, client):
        for _ in range(50):
            client.post("/api/v1/vehicle/drive", json={"speed_kmh": 80.0})
        client.post("/api/v1/vehicle/reset", json={})
        odo = client.get("/api/v1/vehicle/state").json()["odometer_km"]
        assert odo == 0.0