"""
tests/test_energy_model.py

pytest test suite for the REEV core energy model.
Run: pytest tests/ -v
"""

import math
import pytest
from reev_core.powertrain import DriveMode, PowertrainController, VehicleConfig, VehicleState


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def default_ctrl():
    return PowertrainController(initial_soc=0.80)


@pytest.fixture
def low_soc_ctrl():
    """Controller sitting just below the hybrid threshold (20 %)."""
    ctrl = PowertrainController(initial_soc=0.19)
    return ctrl


@pytest.fixture
def depleted_ctrl():
    """Controller at minimum SOC."""
    ctrl = PowertrainController(initial_soc=0.10)
    return ctrl


# ---------------------------------------------------------------------------
# VehicleState sanity
# ---------------------------------------------------------------------------

class TestVehicleState:
    def test_to_dict_keys(self, default_ctrl):
        state = default_ctrl.state
        d = state.to_dict()
        required_keys = {
            "battery_soc_pct", "battery_kwh", "speed_kmh", "mode",
            "ev_range_km", "total_range_km", "fuel_level_pct", "odometer_km",
        }
        assert required_keys.issubset(d.keys())

    def test_soc_pct_matches_fraction(self, default_ctrl):
        state = default_ctrl.state
        assert abs(state.to_dict()["battery_soc_pct"] - state.battery_soc * 100) < 0.01

    def test_kwh_consistent_with_soc(self, default_ctrl):
        state = default_ctrl.state
        cfg = default_ctrl.cfg
        expected_kwh = state.battery_soc * cfg.battery_capacity_kwh
        assert abs(state.battery_kwh - expected_kwh) < 0.001


# ---------------------------------------------------------------------------
# Battery depletion
# ---------------------------------------------------------------------------

class TestBatteryDepletion:
    def test_battery_decreases_while_driving(self, default_ctrl):
        initial_soc = default_ctrl._soc
        for _ in range(100):
            default_ctrl.simulate_step(speed_kmh=80.0, acceleration_ms2=0.0)
        assert default_ctrl._soc < initial_soc

    def test_battery_never_below_min(self, default_ctrl):
        cfg = default_ctrl.cfg
        for _ in range(10_000):
            default_ctrl.simulate_step(speed_kmh=120.0, acceleration_ms2=0.5)
        assert default_ctrl._soc >= cfg.battery_min_soc - 1e-6

    def test_battery_never_above_max(self, default_ctrl):
        cfg = default_ctrl.cfg
        for _ in range(200):
            default_ctrl.charge(power_kw=22.0, duration_minutes=30)
        assert default_ctrl._soc <= cfg.battery_max_soc + 1e-6

    def test_stationary_no_depletion(self, default_ctrl):
        """Parked car should not consume battery (rolling + aero forces are ~zero at 0 km/h)."""
        initial_soc = default_ctrl._soc
        for _ in range(60):
            default_ctrl.simulate_step(speed_kmh=0.0, acceleration_ms2=0.0)
        # Allow tiny floating point drift
        assert abs(default_ctrl._soc - initial_soc) < 1e-9

    def test_faster_speed_depletes_more(self):
        ctrl_slow = PowertrainController(initial_soc=0.80)
        ctrl_fast = PowertrainController(initial_soc=0.80)
        steps = 300
        for _ in range(steps):
            ctrl_slow.simulate_step(speed_kmh=50.0)
            ctrl_fast.simulate_step(speed_kmh=130.0)
        assert ctrl_fast._soc < ctrl_slow._soc


# ---------------------------------------------------------------------------
# Regen braking
# ---------------------------------------------------------------------------

class TestRegenBraking:
    def test_braking_slows_depletion_vs_constant_accel(self):
        """
        Alternating acceleration/braking should leave more energy than
        continuous acceleration of the same magnitude.
        """
        ctrl_regen = PowertrainController(initial_soc=0.80)
        ctrl_no_regen = PowertrainController(initial_soc=0.80)
        ctrl_no_regen.cfg.regen_fraction = 0.0  # disable regen for comparison

        for i in range(200):
            accel = 1.5 if i % 10 < 5 else -1.5
            ctrl_regen.simulate_step(speed_kmh=50.0, acceleration_ms2=accel)
            ctrl_no_regen.simulate_step(speed_kmh=50.0, acceleration_ms2=accel)

        assert ctrl_regen._soc > ctrl_no_regen._soc

    def test_braking_mode_is_coasting(self, default_ctrl):
        # First get some speed so braking makes sense
        default_ctrl._current_speed_kmh = 80.0
        state = default_ctrl.simulate_step(speed_kmh=80.0, acceleration_ms2=-2.5)
        assert state.mode == DriveMode.COASTING


# ---------------------------------------------------------------------------
# Drive mode state machine
# ---------------------------------------------------------------------------

class TestDriveModes:
    def test_starts_in_ev_mode(self, default_ctrl):
        state = default_ctrl.simulate_step(speed_kmh=60.0)
        assert state.mode == DriveMode.EV_ONLY

    def test_hybrid_mode_below_threshold(self, low_soc_ctrl):
        state = low_soc_ctrl.simulate_step(speed_kmh=60.0)
        assert state.mode == DriveMode.HYBRID

    def test_rex_active_in_hybrid_mode(self, low_soc_ctrl):
        state = low_soc_ctrl.simulate_step(speed_kmh=60.0)
        assert state.rex_active is True
        assert state.rex_power_kw > 0.0

    def test_rex_inactive_in_ev_mode(self, default_ctrl):
        state = default_ctrl.simulate_step(speed_kmh=60.0)
        assert state.rex_active is False
        assert state.rex_power_kw == 0.0

    def test_charging_mode(self, default_ctrl):
        initial_soc = default_ctrl._soc
        state = default_ctrl.charge(power_kw=7.4, duration_minutes=60)
        assert state.mode == DriveMode.CHARGING
        assert default_ctrl._soc > initial_soc

    def test_ev_to_hybrid_transition_happens(self):
        """Run until hybrid kicks in — should happen before min SOC."""
        ctrl = PowertrainController(initial_soc=0.25)
        found_hybrid = False
        for _ in range(5000):
            state = ctrl.simulate_step(speed_kmh=80.0, acceleration_ms2=0.0)
            if state.mode == DriveMode.HYBRID:
                found_hybrid = True
                break
        assert found_hybrid, "Hybrid mode never engaged — check threshold logic"


# ---------------------------------------------------------------------------
# Range estimates
# ---------------------------------------------------------------------------

class TestRangeEstimates:
    def test_ev_range_positive(self, default_ctrl):
        state = default_ctrl.state
        assert state.ev_range_km > 0.0

    def test_total_range_geq_ev_range(self, default_ctrl):
        state = default_ctrl.state
        assert state.total_range_km >= state.ev_range_km

    def test_ev_range_zero_at_min_soc(self, depleted_ctrl):
        state = depleted_ctrl.state
        assert state.ev_range_km == 0.0

    def test_range_decreases_as_battery_depletes(self, default_ctrl):
        initial_range = default_ctrl.state.ev_range_km
        for _ in range(500):
            default_ctrl.simulate_step(speed_kmh=100.0)
        assert default_ctrl.state.ev_range_km < initial_range


# ---------------------------------------------------------------------------
# Physics checks
# ---------------------------------------------------------------------------

class TestPhysics:
    def test_aero_drag_increases_with_speed(self):
        ctrl = PowertrainController()
        # Compare energy consumed at low vs high speed (same number of steps)
        ctrl_low = PowertrainController(initial_soc=0.80)
        ctrl_high = PowertrainController(initial_soc=0.80)
        for _ in range(300):
            ctrl_low.simulate_step(speed_kmh=40.0)
            ctrl_high.simulate_step(speed_kmh=120.0)
        assert ctrl_high._soc < ctrl_low._soc

    def test_uphill_consumes_more(self):
        ctrl_flat  = PowertrainController(initial_soc=0.80)
        ctrl_uphill = PowertrainController(initial_soc=0.80)
        for _ in range(300):
            ctrl_flat.simulate_step(speed_kmh=60.0, grade_pct=0.0)
            ctrl_uphill.simulate_step(speed_kmh=60.0, grade_pct=8.0)
        assert ctrl_uphill._soc < ctrl_flat._soc

    def test_odometer_increments_correctly(self, default_ctrl):
        speed_kmh = 90.0
        dt_h = default_ctrl.cfg.dt_seconds / 3600.0
        expected_km_per_step = speed_kmh * dt_h
        for _ in range(10):
            default_ctrl.simulate_step(speed_kmh=speed_kmh)
        assert abs(default_ctrl._odometer_km - expected_km_per_step * 10) < 0.001


# ---------------------------------------------------------------------------
# Fuel / REX
# ---------------------------------------------------------------------------

class TestFuelAndRex:
    def test_fuel_decreases_in_hybrid_mode(self, low_soc_ctrl):
        initial_fuel = low_soc_ctrl._fuel_pct
        for _ in range(300):
            low_soc_ctrl.simulate_step(speed_kmh=80.0)
        assert low_soc_ctrl._fuel_pct < initial_fuel

    def test_fuel_not_consumed_in_ev_mode(self, default_ctrl):
        initial_fuel = default_ctrl._fuel_pct
        for _ in range(300):
            default_ctrl.simulate_step(speed_kmh=60.0)
        assert default_ctrl._fuel_pct == initial_fuel

    def test_fuel_never_negative(self, low_soc_ctrl):
        for _ in range(100_000):
            low_soc_ctrl.simulate_step(speed_kmh=80.0)
        assert low_soc_ctrl._fuel_pct >= 0.0


# ---------------------------------------------------------------------------
# Reset / reproducibility
# ---------------------------------------------------------------------------

class TestReset:
    def test_reset_restores_initial_state(self, default_ctrl):
        for _ in range(500):
            default_ctrl.simulate_step(speed_kmh=80.0)
        assert default_ctrl._soc < 0.78

        default_ctrl.reset(initial_soc=0.80)
        assert abs(default_ctrl._soc - 0.80) < 1e-9
        assert default_ctrl._odometer_km == 0.0

    def test_same_inputs_same_outputs(self):
        """Deterministic physics — no randomness in the model itself."""
        ctrl_a = PowertrainController(initial_soc=0.70)
        ctrl_b = PowertrainController(initial_soc=0.70)
        for _ in range(200):
            sa = ctrl_a.simulate_step(speed_kmh=75.0, acceleration_ms2=0.3)
            sb = ctrl_b.simulate_step(speed_kmh=75.0, acceleration_ms2=0.3)
        assert abs(sa.battery_soc - sb.battery_soc) < 1e-12
