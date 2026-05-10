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
"""

from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from reev_core.powertrain import PowertrainController, VehicleConfig


# ---------------------------------------------------------------------------
# App lifespan — controller lives here, shared across all requests
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create the controller once at startup; tear down on shutdown."""
    app.state.controller = PowertrainController(
        config=VehicleConfig(),
        initial_soc=0.80,
        initial_fuel_pct=1.00,
    )
    print("✅  PowertrainController initialised — SOC: 80%")
    yield
    print("👋  Server shutting down")


app = FastAPI(
    title="REEV Stack API",
    description="Open-source REEV powertrain simulator REST API",
    version="0.1.0",
    lifespan=lifespan,
)

# Allow the React tablet dashboard (localhost:5173) to call us
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # tighten in production
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class DriveRequest(BaseModel):
    speed_kmh: float = Field(..., ge=0, le=250, description="Current speed in km/h")
    acceleration_ms2: float = Field(0.0, ge=-10.0, le=10.0, description="Longitudinal acceleration m/s²")
    grade_pct: float = Field(0.0, ge=-30.0, le=30.0, description="Road grade percent (+uphill)")


class ChargeRequest(BaseModel):
    power_kw: float = Field(7.4, ge=1.0, le=350.0, description="Charger power in kW")
    duration_minutes: float = Field(60.0, ge=1.0, le=720.0, description="Charge duration in minutes")


class ResetRequest(BaseModel):
    initial_soc: float = Field(0.80, ge=0.10, le=1.00)
    initial_fuel_pct: float = Field(1.00, ge=0.0, le=1.00)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/")
def root():
    return {
        "project": "REEV Stack",
        "version": "0.1.0",
        "docs": "/docs",
        "status": "ok",
    }


@app.get("/api/v1/vehicle/state")
def get_vehicle_state():
    """
    Return the current vehicle state snapshot.
    Polls this endpoint every second from the tablet dashboard.
    """
    ctrl: PowertrainController = app.state.controller
    return ctrl.state.to_dict()


@app.get("/api/v1/config")
def get_config():
    """Return the active vehicle configuration."""
    ctrl: PowertrainController = app.state.controller
    cfg = ctrl.cfg
    return {
        "name":                   cfg.name,
        "mass_kg":                cfg.mass_kg,
        "battery_capacity_kwh":   cfg.battery_capacity_kwh,
        "battery_min_soc_pct":    cfg.battery_min_soc * 100,
        "battery_max_soc_pct":    cfg.battery_max_soc * 100,
        "motor_peak_kw":          cfg.motor_peak_kw,
        "motor_efficiency":       cfg.motor_efficiency,
        "rex_output_kw":          cfg.rex_output_kw,
        "rex_efficiency":         cfg.rex_efficiency,
        "drag_coefficient":       cfg.drag_coefficient,
        "frontal_area_m2":        cfg.frontal_area_m2,
        "rolling_resistance":     cfg.rolling_resistance,
        "regen_fraction":         cfg.regen_fraction,
        "hybrid_threshold_soc_pct": cfg.hybrid_threshold_soc * 100,
    }


@app.post("/api/v1/vehicle/drive")
def drive(req: DriveRequest):
    """
    Advance the simulation by one timestep (dt = 1 second).
    Call this in a loop from the dashboard to animate the vehicle state.
    Returns the new state after the step.
    """
    ctrl: PowertrainController = app.state.controller
    state = ctrl.simulate_step(
        speed_kmh=req.speed_kmh,
        acceleration_ms2=req.acceleration_ms2,
        grade_pct=req.grade_pct,
    )
    return state.to_dict()


@app.post("/api/v1/vehicle/charge")
def charge(req: ChargeRequest):
    """
    Simulate a charging session (stationary).
    Returns state after charging completes.
    """
    ctrl: PowertrainController = app.state.controller
    state = ctrl.charge(
        power_kw=req.power_kw,
        duration_minutes=req.duration_minutes,
    )
    return state.to_dict()


@app.post("/api/v1/vehicle/reset")
def reset(req: ResetRequest = ResetRequest()):
    """
    Reset the controller to a known state.
    Useful for starting a new simulation run without restarting the server.
    """
    ctrl: PowertrainController = app.state.controller
    ctrl.reset(
        initial_soc=req.initial_soc,
        initial_fuel_pct=req.initial_fuel_pct,
    )
    return {"ok": True, "initial_soc_pct": req.initial_soc * 100}