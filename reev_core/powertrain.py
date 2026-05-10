"""
reev_core/powertrain.py

Core energy model for the REEV Stack.
Defines the drive mode state machine, vehicle state, and powertrain controller.

Physics basis:
  - Energy consumption: P = (F_roll + F_aero + F_grade) * v
  - F_roll  = Crr * m * g
  - F_aero  = 0.5 * rho * Cd * A * v²
  - F_grade = m * g * sin(grade_angle)  [grade=0 for flat road]
  - Regen braking captures a fraction of kinetic energy on deceleration

All units: SI internally (m/s, kg, Watts, Wh), km/h at the API surface.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Drive Mode
# ---------------------------------------------------------------------------

class DriveMode(str, Enum):
    """Operating mode of the powertrain."""
    EV_ONLY  = "EV_ONLY"    # Pure electric; ICE off
    HYBRID   = "HYBRID"     # ICE + motor; ICE charges battery while driving
    CHARGING = "CHARGING"   # Stationary charge (AC/DC)
    COASTING = "COASTING"   # Foot off accelerator; regen active


# ---------------------------------------------------------------------------
# Vehicle Configuration
# ---------------------------------------------------------------------------

@dataclass
class VehicleConfig:
    """
    Physical parameters for a generic REEV.
    Defaults approximate a ~1700 kg C-segment PHEV/REEV
    (think: BMW i3 Rex, Nissan e-Power, generic OEM prototype).
    """
    # Identity
    name: str = "Generic REEV"

    # Mass
    mass_kg: float = 1750.0           # Curb weight + 75 kg driver

    # Battery
    battery_capacity_kwh: float = 18.0   # Usable capacity
    battery_min_soc: float = 0.10        # Don't discharge below 10 %
    battery_max_soc: float = 1.00        # Full charge

    # Electric motor
    motor_peak_kw: float = 100.0         # Peak power output
    motor_efficiency: float = 0.92       # Motor + inverter combined

    # Range extender (ICE / generator)
    rex_output_kw: float = 28.0          # Generator output at cruise
    rex_efficiency: float = 0.30         # Thermal → electrical

    # Aerodynamics
    drag_coefficient: float = 0.29       # Cd
    frontal_area_m2: float = 2.4         # A (m²)
    rolling_resistance: float = 0.010    # Crr (good tires on asphalt)

    # Regen
    regen_fraction: float = 0.65         # Fraction of braking energy recovered

    # Hybrid kick-in threshold
    hybrid_threshold_soc: float = 0.20   # ICE starts when SOC drops below this

    # Simulation timestep
    dt_seconds: float = 1.0              # 1-second ticks


# ---------------------------------------------------------------------------
# Vehicle State  (snapshot at a single timestep)
# ---------------------------------------------------------------------------

@dataclass
class VehicleState:
    """
    Immutable snapshot of the vehicle at one point in time.
    The controller produces a new VehicleState each tick — nothing mutates in place.
    """
    # Battery
    battery_soc: float          # 0.0 – 1.0  (fraction)
    battery_kwh: float          # Absolute energy remaining (kWh)

    # Motion
    speed_kmh: float            # Current speed
    acceleration_ms2: float     # Current acceleration (m/s²)

    # Powertrain
    mode: DriveMode
    motor_power_kw: float       # Positive = consuming; negative = regenerating
    rex_active: bool            # Is range extender running?
    rex_power_kw: float         # Power delivered by rex this tick

    # Derived range estimates
    ev_range_km: float          # Remaining pure-EV range (km)
    total_range_km: float       # EV range + estimated REX range

    # Fuel (range extender tank)
    fuel_level_pct: float       # 0.0 – 1.0

    # Metadata
    odometer_km: float
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        return {
            "battery_soc_pct": round(self.battery_soc * 100, 2),
            "battery_kwh":     round(self.battery_kwh, 3),
            "speed_kmh":       round(self.speed_kmh, 1),
            "acceleration_ms2":round(self.acceleration_ms2, 3),
            "mode":            self.mode.value,
            "motor_power_kw":  round(self.motor_power_kw, 3),
            "rex_active":      self.rex_active,
            "rex_power_kw":    round(self.rex_power_kw, 3),
            "ev_range_km":     round(self.ev_range_km, 1),
            "total_range_km":  round(self.total_range_km, 1),
            "fuel_level_pct":  round(self.fuel_level_pct * 100, 1),
            "odometer_km":     round(self.odometer_km, 3),
            "timestamp":       self.timestamp.isoformat(),
        }


# ---------------------------------------------------------------------------
# Powertrain Controller
# ---------------------------------------------------------------------------

class PowertrainController:
    """
    Stateful controller that advances the vehicle simulation one timestep at a time.

    Usage:
        cfg = VehicleConfig()
        ctrl = PowertrainController(cfg, initial_soc=0.80)
        state = ctrl.simulate_step(speed_kmh=80.0, acceleration_ms2=0.0)
        print(state.battery_soc)
    """

    # Air density at sea level, 20 °C (kg/m³)
    AIR_DENSITY = 1.204

    # Gravitational acceleration (m/s²)
    GRAVITY = 9.81

    # Assumed average consumption for range estimate (Wh/km) at 80 km/h cruise
    # Used only for range projection; gets overwritten with rolling average in Phase 2
    _BASELINE_CONSUMPTION_WH_PER_KM = 160.0

    # REX fuel tank (litres, ~30 L is typical for a REEV)
    _FUEL_TANK_L = 30.0
    _FUEL_ENERGY_DENSITY_KWH_PER_L = 8.8   # Petrol

    def __init__(
        self,
        config: Optional[VehicleConfig] = None,
        initial_soc: float = 0.80,
        initial_fuel_pct: float = 1.00,
    ):
        self.cfg = config or VehicleConfig()
        self._soc = max(self.cfg.battery_min_soc,
                        min(self.cfg.battery_max_soc, initial_soc))
        self._fuel_pct = initial_fuel_pct
        self._odometer_km = 0.0
        self._current_speed_kmh = 0.0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def state(self) -> VehicleState:
        """Return current state without advancing the simulation."""
        return self._build_state(
            speed_kmh=self._current_speed_kmh,
            acceleration_ms2=0.0,
            motor_kw=0.0,
            rex_active=False,
            rex_kw=0.0,
        )

    def simulate_step(
        self,
        speed_kmh: float,
        acceleration_ms2: float = 0.0,
        grade_pct: float = 0.0,
    ) -> VehicleState:
        """
        Advance simulation by one dt_seconds tick.

        Args:
            speed_kmh:        Target/current speed in km/h.
            acceleration_ms2: Longitudinal acceleration (positive = speeding up,
                              negative = braking).
            grade_pct:        Road grade in percent (positive = uphill).

        Returns:
            VehicleState snapshot after this tick.
        """
        dt = self.cfg.dt_seconds
        speed_ms = speed_kmh / 3.6

        # 1. Traction force needed
        F_roll  = self._rolling_force()
        F_aero  = self._aero_force(speed_ms)
        F_grade = self._grade_force(grade_pct)
        F_accel = self.cfg.mass_kg * acceleration_ms2

        F_total_N = F_roll + F_aero + F_grade + F_accel

        # 2. Mechanical power at the wheel (W)
        P_wheel_W = F_total_N * speed_ms  # can be negative (regen)

        # 3. Electrical power accounting for motor efficiency
        if P_wheel_W >= 0:
            # Driving: motor draws MORE from battery than what reaches wheel
            P_electrical_W = P_wheel_W / self.cfg.motor_efficiency
        else:
            # Braking / coasting: recover LESS than wheel power (regen losses)
            P_electrical_W = P_wheel_W * self.cfg.regen_fraction * self.cfg.motor_efficiency

        # 4. Determine drive mode
        mode = self._decide_mode(speed_kmh, acceleration_ms2, P_electrical_W)

        # 5. Range extender contribution
        rex_active, rex_kw, fuel_consumed_kwh = self._rex_contribution(mode)

        # 6. Net energy drawn from battery this tick
        P_motor_kw = P_electrical_W / 1000.0
        net_battery_kw = P_motor_kw - rex_kw  # rex offsets draw

        energy_delta_kwh = net_battery_kw * (dt / 3600.0)  # kW × h
        new_kwh = self.cfg.battery_capacity_kwh * self._soc - energy_delta_kwh
        new_kwh = max(
            self.cfg.battery_min_soc * self.cfg.battery_capacity_kwh,
            min(self.cfg.battery_max_soc * self.cfg.battery_capacity_kwh, new_kwh),
        )

        # 7. Update internal state
        self._soc = new_kwh / self.cfg.battery_capacity_kwh
        self._fuel_pct = max(0.0, self._fuel_pct - fuel_consumed_kwh / (
            self._FUEL_TANK_L * self._FUEL_ENERGY_DENSITY_KWH_PER_L
        ))
        distance_km = speed_kmh * (dt / 3600.0)
        self._odometer_km += distance_km
        self._current_speed_kmh = speed_kmh

        return self._build_state(
            speed_kmh=speed_kmh,
            acceleration_ms2=acceleration_ms2,
            motor_kw=P_motor_kw,
            rex_active=rex_active,
            rex_kw=rex_kw,
            mode_override=mode,
        )

    def charge(self, power_kw: float = 7.4, duration_minutes: float = 60.0) -> VehicleState:
        """
        Simulate AC charging session (no driving).

        Args:
            power_kw:          Charger output (kW). Default: 7.4 kW (Type 2 AC).
            duration_minutes:  How long to charge.
        """
        charger_efficiency = 0.92
        energy_added_kwh = power_kw * charger_efficiency * (duration_minutes / 60.0)
        current_kwh = self.cfg.battery_capacity_kwh * self._soc
        new_kwh = min(
            self.cfg.battery_max_soc * self.cfg.battery_capacity_kwh,
            current_kwh + energy_added_kwh,
        )
        self._soc = new_kwh / self.cfg.battery_capacity_kwh
        return self._build_state(
            speed_kmh=0.0,
            acceleration_ms2=0.0,
            motor_kw=0.0,
            rex_active=False,
            rex_kw=0.0,
            mode_override=DriveMode.CHARGING,
        )

    def reset(self, initial_soc: float = 0.80, initial_fuel_pct: float = 1.00) -> None:
        """Reset controller to initial conditions (useful for test runs)."""
        self._soc = initial_soc
        self._fuel_pct = initial_fuel_pct
        self._odometer_km = 0.0
        self._current_speed_kmh = 0.0

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _rolling_force(self) -> float:
        return self.cfg.rolling_resistance * self.cfg.mass_kg * self.GRAVITY

    def _aero_force(self, speed_ms: float) -> float:
        return 0.5 * self.AIR_DENSITY * self.cfg.drag_coefficient \
               * self.cfg.frontal_area_m2 * (speed_ms ** 2)

    def _grade_force(self, grade_pct: float) -> float:
        angle_rad = math.atan(grade_pct / 100.0)
        return self.cfg.mass_kg * self.GRAVITY * math.sin(angle_rad)

    def _decide_mode(self, speed_kmh: float, acceleration_ms2: float, P_electrical_W: float) -> DriveMode:
        # SOC-based rule takes highest priority — REX must run regardless of speed
        if self._soc < self.cfg.hybrid_threshold_soc:
            return DriveMode.HYBRID

        if speed_kmh == 0.0 and acceleration_ms2 == 0.0:
            return DriveMode.EV_ONLY  # parked / stationary

        if acceleration_ms2 < -0.1 and P_electrical_W < 0:
            return DriveMode.COASTING  # braking, regen active

        return DriveMode.EV_ONLY

    def _rex_contribution(self, mode: DriveMode) -> tuple[bool, float, float]:
        """
        Returns (rex_active, rex_output_kw, fuel_consumed_kwh_this_tick).
        REX runs at ~60 % output in HYBRID mode to extend range without
        hammering fuel consumption.
        """
        if mode != DriveMode.HYBRID or self._fuel_pct <= 0.0:
            return False, 0.0, 0.0

        dt = self.cfg.dt_seconds
        rex_kw = self.cfg.rex_output_kw * 0.60   # partial load
        # Fuel energy consumed = electrical output / thermal efficiency
        fuel_energy_kwh = rex_kw * (dt / 3600.0) / self.cfg.rex_efficiency
        return True, rex_kw, fuel_energy_kwh

    def _ev_range_km(self) -> float:
        usable_kwh = (self._soc - self.cfg.battery_min_soc) \
                     * self.cfg.battery_capacity_kwh
        if usable_kwh <= 0:
            return 0.0
        return (usable_kwh * 1000.0) / self._BASELINE_CONSUMPTION_WH_PER_KM

    def _total_range_km(self) -> float:
        fuel_kwh = self._fuel_pct * self._FUEL_TANK_L \
                   * self._FUEL_ENERGY_DENSITY_KWH_PER_L
        rex_range_km = (fuel_kwh * self.cfg.rex_efficiency * 1000.0) \
                       / self._BASELINE_CONSUMPTION_WH_PER_KM
        return self._ev_range_km() + rex_range_km

    def _build_state(
        self,
        speed_kmh: float,
        acceleration_ms2: float,
        motor_kw: float,
        rex_active: bool,
        rex_kw: float,
        mode_override: Optional[DriveMode] = None,
    ) -> VehicleState:
        mode = mode_override or self._decide_mode(speed_kmh, acceleration_ms2, motor_kw * 1000.0)
        return VehicleState(
            battery_soc=self._soc,
            battery_kwh=self._soc * self.cfg.battery_capacity_kwh,
            speed_kmh=speed_kmh,
            acceleration_ms2=acceleration_ms2,
            mode=mode,
            motor_power_kw=motor_kw,
            rex_active=rex_active,
            rex_power_kw=rex_kw,
            ev_range_km=self._ev_range_km(),
            total_range_km=self._total_range_km(),
            fuel_level_pct=self._fuel_pct,
            odometer_km=self._odometer_km,
        )
