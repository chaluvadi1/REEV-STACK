# REEV Stack

Open-source powertrain simulator for Range-Extended Electric Vehicles (REEVs).
Physics-based energy model, REST API, React dashboard, and trip logging.

> Early development — Month 4 of 6. Core stack working end-to-end.

## What Works Now
- Physics-based energy model (rolling resistance + aero drag + grade force)
- Drive mode state machine: EV → COASTING (regen) → HYBRID
- Range extender (ICE generator) engagement at configurable SOC threshold
- FastAPI REST server with 9 endpoints
- React tablet dashboard with live API polling
- PostgreSQL trip logging with telemetry time-series
- 53 unit and API tests

## Stack
- **Powertrain core:** Python + SQLAlchemy
- **API:** FastAPI + uvicorn
- **Dashboard:** React + Vite + Tailwind
- **Database:** PostgreSQL 16 (Docker)

## Quick Start

### 1. Clone and install
```bash
git clone https://github.com/chaluvadi1/REEV-STACK
cd REEV-STACK
python -m venv venv && source venv/bin/activate
pip install -e ".[dev]"
```

### 2. Start PostgreSQL
```bash
docker run -d \
  --name reev-postgres \
  -e POSTGRES_PASSWORD=reev \
  -e POSTGRES_DB=reevdb \
  -e POSTGRES_USER=reev \
  -p 5432:5432 \
  postgres:16
```

### 3. Start the API
```bash
uvicorn api.main:app --reload --port 8000
# Tables are created automatically on first run
# Open http://localhost:8000/docs for Swagger UI
```

### 4. Start the dashboard
```bash
cd ui_tablet
npm install
npm run dev
# Open http://localhost:5173
```

### 5. Run the simulator standalone
```bash
python -m reev_core.simulator
```

### 6. Run tests
```bash
pytest tests/ -v
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/vehicle/state` | Current battery, range, mode |
| GET | `/api/v1/config` | Vehicle configuration |
| POST | `/api/v1/vehicle/drive` | Advance simulation one tick |
| POST | `/api/v1/vehicle/charge` | Simulate charging session |
| POST | `/api/v1/vehicle/reset` | Reset to known state |
| POST | `/api/v1/trips/start` | Start a new trip |
| POST | `/api/v1/trips/stop` | End the active trip |
| GET | `/api/v1/trips` | Last 10 trips |
| GET | `/api/v1/trips/summary/stats` | Aggregate efficiency stats |

## Note for Apple Silicon (M1/M2/M3) Mac
Docker Desktop does not work reliably on M1. Use Colima instead:
```bash
brew install colima docker docker-compose
colima start --arch aarch64 --vm-type vz --vz-rosetta
```
Run `colima start` after each Mac restart before using Docker.

## Roadmap
| Month | Milestone |
|-------|-----------|
| 1 ✅ | Core energy model + simulator |
| 2 ✅ | FastAPI REST server |
| 3 ✅ | React tablet dashboard |
| 4 ✅ | PostgreSQL trip logging |
| 5 🔨 | React Native mobile app |
| 6    | Docs, docker-compose, launch |

## License
MIT