"""
api/main.py

REEV Stack — FastAPI REST server.
Wraps the PowertrainController in an HTTP API.

Run:
    uvicorn api.main:app --reload --port 8000

Test:
    curl http://localhost:8000/api/v1/vehicle/state
    curl http://localhost:8000/api/v1/config
    curl -X POST http://localhost:8000/api/v1/vehicle/drive \
         -H "Content-Type: application/json" \
         -d '{"speed_kmh": 80, "acceleration_ms2": 0.5}'
    curl -X POST http://localhost:8000/api/v1/vehicle/charge \
         -H "Content-Type: application/json" \
         -d '{"power_kw": 7.4, "duration_minutes": 30}'
    curl -X POST http://localhost:8000/api/v1/vehicle/reset
    curl -X POST http://localhost:8000/api/v1/trips/start
    curl http://localhost:8000/api/v1/trips
    curl -X POST http://localhost:8000/api/v1/trips/stop
"""

from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from reev_core.powertrain import PowertrainController, VehicleConfig, DriveMode
from api.database import init_db, get_db, Trip, Telemetry


# ---------------------------------------------------------------------------
# App lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    print("✅  Database tables ready")
    app.state.controller = PowertrainController(
        config=VehicleConfig(),
        initial_soc=0.80,
        initial_fuel_pct=1.00,
    )
    app.state.active_trip_id = None
    print("✅  PowertrainController initialised — SOC: 80%")
    yield
    print("👋  Server shutting down")


app = FastAPI(
    title="REEV Stack API",
    description="Open-source REEV powertrain simulator REST API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class DriveRequest(BaseModel):
    speed_kmh: float = Field(..., ge=0, le=250)
    acceleration_ms2: float = Field(0.0, ge=-10.0, le=10.0)
    grade_pct: float = Field(0.0, ge=-30.0, le=30.0)


class ChargeRequest(BaseModel):
    power_kw: float = Field(7.4, ge=1.0, le=350.0)
    duration_minutes: float = Field(60.0, ge=1.0, le=720.0)


class ResetRequest(BaseModel):
    initial_soc: float = Field(0.80, ge=0.10, le=1.00)
    initial_fuel_pct: float = Field(1.00, ge=0.0, le=1.00)


# ---------------------------------------------------------------------------
# Vehicle routes
# ---------------------------------------------------------------------------

@app.get("/")
def root():
    return {"project": "REEV Stack", "version": "0.1.0", "docs": "/docs", "status": "ok"}


@app.get("/api/v1/vehicle/state")
def get_vehicle_state():
    ctrl: PowertrainController = app.state.controller
    return ctrl.state.to_dict()


@app.get("/api/v1/config")
def get_config():
    cfg = app.state.controller.cfg
    return {
        "name":                     cfg.name,
        "mass_kg":                  cfg.mass_kg,
        "battery_capacity_kwh":     cfg.battery_capacity_kwh,
        "battery_min_soc_pct":      cfg.battery_min_soc * 100,
        "battery_max_soc_pct":      cfg.battery_max_soc * 100,
        "motor_peak_kw":            cfg.motor_peak_kw,
        "motor_efficiency":         cfg.motor_efficiency,
        "rex_output_kw":            cfg.rex_output_kw,
        "rex_efficiency":           cfg.rex_efficiency,
        "drag_coefficient":         cfg.drag_coefficient,
        "frontal_area_m2":          cfg.frontal_area_m2,
        "rolling_resistance":       cfg.rolling_resistance,
        "regen_fraction":           cfg.regen_fraction,
        "hybrid_threshold_soc_pct": cfg.hybrid_threshold_soc * 100,
    }


@app.post("/api/v1/vehicle/drive")
def drive(req: DriveRequest, db: Session = Depends(get_db)):
    ctrl: PowertrainController = app.state.controller
    soc_before = ctrl._soc
    state = ctrl.simulate_step(
        speed_kmh=req.speed_kmh,
        acceleration_ms2=req.acceleration_ms2,
        grade_pct=req.grade_pct,
    )

    # Log to DB if a trip is active
    trip_id = app.state.active_trip_id
    if trip_id:
        energy_delta  = (soc_before - ctrl._soc) * ctrl.cfg.battery_capacity_kwh
        dt_h          = ctrl.cfg.dt_seconds / 3600.0
        distance_step = req.speed_kmh * dt_h

        trip = db.query(Trip).filter(Trip.id == trip_id).first()
        if trip:
            trip.distance_km     += distance_step
            trip.energy_used_kwh += max(0.0, energy_delta)
            if state.mode == DriveMode.EV_ONLY:
                trip.ev_distance_km     += distance_step
            elif state.mode == DriveMode.HYBRID:
                trip.hybrid_distance_km += distance_step
            trip.end_soc_pct = state.battery_soc * 100

            tick = db.query(Telemetry).filter(Telemetry.trip_id == trip_id).count()
            trip.avg_speed_kmh = (trip.avg_speed_kmh * tick + req.speed_kmh) / (tick + 1)

        db.add(Telemetry(
            trip_id=trip_id,
            timestamp=state.timestamp,
            battery_soc_pct=state.battery_soc * 100,
            speed_kmh=state.speed_kmh,
            motor_power_kw=state.motor_power_kw,
            rex_active=state.rex_active,
            rex_power_kw=state.rex_power_kw,
            odometer_km=state.odometer_km,
            mode=state.mode.value,
        ))
        db.commit()

    return state.to_dict()


@app.post("/api/v1/vehicle/charge")
def charge(req: ChargeRequest):
    ctrl: PowertrainController = app.state.controller
    state = ctrl.charge(power_kw=req.power_kw, duration_minutes=req.duration_minutes)
    return state.to_dict()


@app.post("/api/v1/vehicle/reset")
def reset(req: ResetRequest = ResetRequest()):
    app.state.controller.reset(
        initial_soc=req.initial_soc,
        initial_fuel_pct=req.initial_fuel_pct,
    )
    app.state.active_trip_id = None
    return {"ok": True, "initial_soc_pct": req.initial_soc * 100}


# ---------------------------------------------------------------------------
# Trip routes
# ---------------------------------------------------------------------------

@app.post("/api/v1/trips/start")
def start_trip(db: Session = Depends(get_db)):
    """Start a new trip. Fails if one is already in progress."""
    if app.state.active_trip_id:
        raise HTTPException(
            status_code=409,
            detail="A trip is already in progress. POST /api/v1/trips/stop first."
        )
    ctrl: PowertrainController = app.state.controller
    trip = Trip(
        start_time=datetime.now(timezone.utc),
        start_soc_pct=ctrl._soc * 100,
    )
    db.add(trip)
    db.commit()
    db.refresh(trip)
    app.state.active_trip_id = trip.id
    return {"ok": True, "trip_id": trip.id, "start_soc_pct": trip.start_soc_pct}


@app.post("/api/v1/trips/stop")
def stop_trip(db: Session = Depends(get_db)):
    """Close the active trip."""
    trip_id = app.state.active_trip_id
    if not trip_id:
        raise HTTPException(status_code=409, detail="No trip in progress.")

    trip = db.query(Trip).filter(Trip.id == trip_id).first()
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found.")

    trip.end_time = datetime.now(timezone.utc)
    db.commit()
    db.refresh(trip)
    app.state.active_trip_id = None
    return trip.to_dict()


@app.get("/api/v1/trips")
def list_trips(limit: int = 10, db: Session = Depends(get_db)):
    """Return the last N trips, most recent first."""
    trips = (
        db.query(Trip)
        .order_by(Trip.start_time.desc())
        .limit(limit)
        .all()
    )
    return [t.to_dict() for t in trips]


@app.get("/api/v1/trips/summary/stats")
def trip_summary(db: Session = Depends(get_db)):
    """Aggregate stats across all completed trips."""
    trips = db.query(Trip).filter(Trip.end_time.isnot(None)).all()
    if not trips:
        return {"message": "No completed trips yet."}

    total_distance    = sum(t.distance_km for t in trips)
    total_energy      = sum(t.energy_used_kwh for t in trips)
    total_ev_dist     = sum(t.ev_distance_km for t in trips)
    total_hybrid_dist = sum(t.hybrid_distance_km for t in trips)

    return {
        "total_trips":              len(trips),
        "total_distance_km":        round(total_distance, 2),
        "total_energy_kwh":         round(total_energy, 3),
        "ev_distance_km":           round(total_ev_dist, 2),
        "hybrid_distance_km":       round(total_hybrid_dist, 2),
        "ev_ratio_pct":             round((total_ev_dist / total_distance * 100) if total_distance else 0, 1),
        "avg_efficiency_wh_per_km": round((total_energy * 1000 / total_distance) if total_distance else 0, 1),
    }


@app.get("/api/v1/trips/{trip_id}")
def get_trip(trip_id: int, db: Session = Depends(get_db)):
    """Return a single trip with full telemetry."""
    trip = db.query(Trip).filter(Trip.id == trip_id).first()
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found.")
    result = trip.to_dict()
    result["telemetry"] = [t.to_dict() for t in trip.telemetry]
    return result