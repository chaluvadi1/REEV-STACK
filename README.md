# REEV Stack

Open-source powertrain simulator for Range-Extended Electric Vehicles (REEVs).
Build dashboards, run simulations, contribute vehicle data.

> ⚠️ Early development — Month 1 of 6. Simulator works; API and UI coming.

## Quick Start

```bash
git clone https://github.com/chaluvadi1/REEV-STACK
cd REEV-STACK
python -m venv venv && source venv/bin/activate
pip install -e ".[dev]"

# Run the simulator
python -m reev_core.simulator

# Run tests
pytest tests/ -v
```

## What Works Now
- Physics-based energy model (rolling resistance + aero drag + grade force)
- Drive mode state machine: EV → COASTING (regen) → HYBRID
- Range extender (ICE generator) engagement at configurable SOC threshold
- Three drive cycle scenarios: city, highway, mixed
- 28 unit tests

## Roadmap
| Month | Milestone |
|-------|-----------|
| 1 ✅ | Core energy model + simulator |
| 2 🔨 | FastAPI REST server |
| 3    | React tablet dashboard |
| 4    | PostgreSQL trip logging |
| 5    | React Native mobile app |
| 6    | Docs + launch |

## License
MIT