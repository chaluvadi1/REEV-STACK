#!/usr/bin/env python3
"""
examples/quickstart.py
Run: python examples/quickstart.py

Shows the full simulator in action with no setup beyond:
    pip install -e .
"""
from reev_core.powertrain import PowertrainController, VehicleConfig
from reev_core.simulator import city_cycle, highway_cycle

def main():
    print("REEV Stack — Quickstart Demo\n")
    
    cfg  = VehicleConfig()
    ctrl = PowertrainController(cfg, initial_soc=0.80)
    
    print(f"{'Step':>5}  {'SOC':>6}  {'Mode':<10}  {'Range':>8}")
    print("─" * 40)
    
    # 5 minutes city, 5 minutes highway
    cycles = list(city_cycle(300)) + list(highway_cycle(300))
    for i, (spd, acc) in enumerate(cycles, 1):
        state = ctrl.simulate_step(speed_kmh=spd, acceleration_ms2=acc)
        if i % 60 == 0:
            print(f"{i:>5}  {state.battery_soc*100:>5.1f}%  "
                  f"{state.mode.value:<10}  {state.ev_range_km:>5.1f} km")
    
    print(f"\nFinal: {state.to_dict()}")

if __name__ == "__main__":
    main()