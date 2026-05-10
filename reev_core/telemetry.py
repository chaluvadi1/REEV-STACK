# reev_core/telemetry.py
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
from reev_core.powertrain import DriveMode

@dataclass
class TelemetryRecord:
    """One logged data point — written every N seconds while driving."""
    timestamp: datetime
    battery_soc: float
    speed_kmh: float
    mode: DriveMode
    motor_power_kw: float
    rex_active: bool
    odometer_km: float
    latitude: Optional[float] = None   # None until GPS added (Month 5+)
    longitude: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            "timestamp":      self.timestamp.isoformat(),
            "battery_soc_pct": round(self.battery_soc * 100, 2),
            "speed_kmh":      round(self.speed_kmh, 1),
            "mode":           self.mode.value,
            "motor_power_kw": round(self.motor_power_kw, 3),
            "rex_active":     self.rex_active,
            "odometer_km":    round(self.odometer_km, 3),
        }

@dataclass
class TripSummary:
    """Computed once a trip ends."""
    trip_id: str
    start_time: datetime
    end_time: datetime
    distance_km: float
    energy_used_kwh: float
    ev_distance_km: float          # distance driven in EV_ONLY mode
    hybrid_distance_km: float
    avg_speed_kmh: float

    @property
    def duration_minutes(self) -> float:
        return (self.end_time - self.start_time).total_seconds() / 60

    @property
    def efficiency_wh_per_km(self) -> float:
        if self.distance_km == 0:
            return 0.0
        return (self.energy_used_kwh * 1000) / self.distance_km