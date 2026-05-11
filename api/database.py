"""
api/database.py

SQLAlchemy setup and table definitions for REEV Stack.

Tables:
  - trips       : one row per driving session
  - telemetry   : one row per second while driving (raw sensor/sim data)
"""

from datetime import datetime, timezone
from sqlalchemy import (
    create_engine, Column, Integer, Float, String,
    Boolean, DateTime, ForeignKey, text
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

DATABASE_URL = "postgresql+psycopg2://reev:reev@localhost:5432/reevdb"

engine = create_engine(DATABASE_URL, echo=False)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
Base = declarative_base()


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class Trip(Base):
    """One driving session — created when driving starts, closed when it stops."""
    __tablename__ = "trips"

    id                  = Column(Integer, primary_key=True, index=True)
    start_time          = Column(DateTime(timezone=True), nullable=False)
    end_time            = Column(DateTime(timezone=True), nullable=True)   # null = in progress
    distance_km         = Column(Float, default=0.0)
    energy_used_kwh     = Column(Float, default=0.0)
    ev_distance_km      = Column(Float, default=0.0)
    hybrid_distance_km  = Column(Float, default=0.0)
    start_soc_pct       = Column(Float, nullable=False)
    end_soc_pct         = Column(Float, nullable=True)
    avg_speed_kmh       = Column(Float, default=0.0)

    telemetry = relationship("Telemetry", back_populates="trip", cascade="all, delete")

    @property
    def duration_minutes(self) -> float:
        if not self.end_time:
            return 0.0
        return (self.end_time - self.start_time).total_seconds() / 60

    @property
    def efficiency_wh_per_km(self) -> float:
        if not self.distance_km or self.distance_km == 0:
            return 0.0
        return (self.energy_used_kwh * 1000) / self.distance_km

    def to_dict(self) -> dict:
        return {
            "id":                   self.id,
            "start_time":           self.start_time.isoformat() if self.start_time else None,
            "end_time":             self.end_time.isoformat() if self.end_time else None,
            "duration_minutes":     round(self.duration_minutes, 1),
            "distance_km":          round(self.distance_km, 2),
            "energy_used_kwh":      round(self.energy_used_kwh, 3),
            "ev_distance_km":       round(self.ev_distance_km, 2),
            "hybrid_distance_km":   round(self.hybrid_distance_km, 2),
            "start_soc_pct":        round(self.start_soc_pct, 1),
            "end_soc_pct":          round(self.end_soc_pct, 1) if self.end_soc_pct else None,
            "avg_speed_kmh":        round(self.avg_speed_kmh, 1),
            "efficiency_wh_per_km": round(self.efficiency_wh_per_km, 1),
            "in_progress":          self.end_time is None,
        }


class Telemetry(Base):
    """One row per simulation tick — raw time-series data."""
    __tablename__ = "telemetry"

    id              = Column(Integer, primary_key=True, index=True)
    trip_id         = Column(Integer, ForeignKey("trips.id"), nullable=False, index=True)
    timestamp       = Column(DateTime(timezone=True), nullable=False)
    battery_soc_pct = Column(Float, nullable=False)
    speed_kmh       = Column(Float, nullable=False)
    motor_power_kw  = Column(Float, nullable=False)
    rex_active      = Column(Boolean, default=False)
    rex_power_kw    = Column(Float, default=0.0)
    odometer_km     = Column(Float, nullable=False)
    mode            = Column(String(16), nullable=False)

    trip = relationship("Trip", back_populates="telemetry")

    def to_dict(self) -> dict:
        return {
            "id":               self.id,
            "trip_id":          self.trip_id,
            "timestamp":        self.timestamp.isoformat(),
            "battery_soc_pct":  round(self.battery_soc_pct, 2),
            "speed_kmh":        round(self.speed_kmh, 1),
            "motor_power_kw":   round(self.motor_power_kw, 3),
            "rex_active":       self.rex_active,
            "rex_power_kw":     round(self.rex_power_kw, 3),
            "odometer_km":      round(self.odometer_km, 3),
            "mode":             self.mode,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def init_db():
    """Create all tables if they don't exist. Called at server startup."""
    Base.metadata.create_all(bind=engine)


def get_db():
    """FastAPI dependency — yields a DB session, closes it after request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()