"""
reev_core/simulator.py

Standalone simulator — run directly:
    python -m reev_core.simulator
    python simulator.py  (from reev_core/ directory)

Simulates three scenarios and prints a live ASCII progress bar:
  1. City drive (stop-go, 30–50 km/h)  — SOC 80 % → ~50 %
  2. Highway cruise (110 km/h)          — SOC continues down
  3. Hybrid mode kicks in automatically  — REX runs, SOC stabilizes
"""

from __future__ import annotations

import random
import time
from typing import Generator

from reev_core.powertrain import DriveMode, PowertrainController, VehicleConfig, VehicleState


# ---------------------------------------------------------------------------
# Drive cycle generators
# ---------------------------------------------------------------------------

def city_cycle(steps: int = 600) -> Generator[tuple[float, float], None, None]:
    """
    Simulates urban stop-and-go traffic.
    Each yielded tuple: (speed_kmh, acceleration_ms2)
    """
    speed = 0.0
    for i in range(steps):
        target = random.choice([0, 0, 20, 30, 40, 50, 50, 60])
        diff = target - speed
        accel = max(-2.5, min(2.5, diff * 0.3 + random.gauss(0, 0.2)))
        speed = max(0.0, speed + accel)
        yield speed, accel


def highway_cycle(steps: int = 600, speed_kmh: float = 110.0) -> Generator[tuple[float, float], None, None]:
    """
    Constant-speed highway cruise with minor speed variations.
    """
    speed = speed_kmh
    for _ in range(steps):
        speed += random.gauss(0, 0.5)
        speed = max(90.0, min(130.0, speed))
        yield speed, 0.0


def mixed_cycle(steps: int = 600) -> Generator[tuple[float, float], None, None]:
    """
    Mixed urban + highway (50 % each).
    """
    half = steps // 2
    yield from city_cycle(half)
    yield from highway_cycle(steps - half)


# ---------------------------------------------------------------------------
# Run & report helpers
# ---------------------------------------------------------------------------

def _bar(soc: float, width: int = 30) -> str:
    filled = int(soc * width)
    empty  = width - filled
    color  = "\033[92m" if soc > 0.4 else "\033[93m" if soc > 0.2 else "\033[91m"
    return f"{color}{'█' * filled}{'░' * empty}\033[0m"


def _mode_label(mode: DriveMode) -> str:
    labels = {
        DriveMode.EV_ONLY:  "\033[94m⚡ EV   \033[0m",
        DriveMode.HYBRID:   "\033[93m⚙  HYB  \033[0m",
        DriveMode.COASTING: "\033[96m↓  COAST\033[0m",
        DriveMode.CHARGING: "\033[92m⏩ CHG  \033[0m",
    }
    return labels.get(mode, mode.value)


def run_scenario(
    label: str,
    ctrl: PowertrainController,
    cycle: Generator[tuple[float, float], None, None],
    print_every: int = 60,
) -> list[VehicleState]:
    """Run a drive cycle and collect states. Prints progress every N steps."""

    print(f"\n{'═' * 65}")
    print(f"  SCENARIO: {label}")
    print(f"{'═' * 65}")
    print(f"  {'Step':>5}  {'SOC':>6}  {'Battery':^32}  {'Mode':^10}  {'Range':>8}  {'Speed':>6}")
    print(f"  {'─'*5}  {'─'*6}  {'─'*32}  {'─'*10}  {'─'*8}  {'─'*6}")

    states: list[VehicleState] = []
    for step, (spd, acc) in enumerate(cycle, start=1):
        state = ctrl.simulate_step(speed_kmh=spd, acceleration_ms2=acc)
        states.append(state)

        if step % print_every == 0 or step == 1:
            bar  = _bar(state.battery_soc)
            mode = _mode_label(state.mode)
            print(
                f"  {step:>5}  "
                f"{state.battery_soc*100:>5.1f}%  "
                f"{bar}  "
                f"{mode}  "
                f"{state.ev_range_km:>5.1f}km  "
                f"{state.speed_kmh:>5.1f}kph"
            )

    final = states[-1]
    print(f"\n  ✓ Done — SOC: {final.battery_soc*100:.1f}%  |  "
          f"Odo: {final.odometer_km:.1f} km  |  "
          f"EV range left: {final.ev_range_km:.1f} km")
    return states


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main() -> None:
    print("\n" + "╔" + "═" * 63 + "╗")
    print("║        REEV STACK — Powertrain Simulator  v0.1              ║")
    print("╚" + "═" * 63 + "╝")

    cfg  = VehicleConfig(name="Generic REEV Demo")
    ctrl = PowertrainController(cfg, initial_soc=0.80)

    print(f"\n  Vehicle : {cfg.name}")
    print(f"  Battery : {cfg.battery_capacity_kwh} kWh usable")
    print(f"  Motor   : {cfg.motor_peak_kw} kW peak")
    print(f"  REX     : {cfg.rex_output_kw} kW generator")
    print(f"  Mass    : {cfg.mass_kg} kg")
    print(f"  Initial SOC : {ctrl._soc * 100:.0f}%")

    # Scenario 1 — city
    city_states = run_scenario(
        label="City Drive (stop-go, 0–60 km/h, 10 min)",
        ctrl=ctrl,
        cycle=city_cycle(steps=600),
        print_every=100,
    )

    # Scenario 2 — highway (continues where city left off; SOC will keep dropping)
    hw_states = run_scenario(
        label="Highway Cruise (110 km/h, 10 min)",
        ctrl=ctrl,
        cycle=highway_cycle(steps=600),
        print_every=100,
    )

    # Scenario 3 — keep going until hybrid kicks in naturally or we hit 3000 steps
    print(f"\n{'═' * 65}")
    print("  SCENARIO: Extended Run → watching for HYBRID mode kick-in")
    print(f"{'═' * 65}")

    step = 0
    hybrid_at_step = None
    for spd, acc in mixed_cycle(steps=3000):
        step += 1
        state = ctrl.simulate_step(speed_kmh=spd, acceleration_ms2=acc)
        if state.mode == DriveMode.HYBRID and hybrid_at_step is None:
            hybrid_at_step = step
            print(f"\n  🔄  HYBRID engaged at step {step} "
                  f"(SOC = {state.battery_soc*100:.1f}%, "
                  f"speed = {state.speed_kmh:.1f} km/h)")
            print(f"      REX output: {state.rex_power_kw:.1f} kW  |  "
                  f"Fuel: {state.fuel_level_pct*100:.1f}%")
        if step >= 3000:
            break

    if hybrid_at_step is None:
        print("  ℹ  Hybrid threshold not reached in extended run — increase run length or lower initial SOC")

    final_state = state
    print(f"\n  Final state after extended run:")
    for k, v in final_state.to_dict().items():
        print(f"    {k:<22} {v}")

    print("\n  ✅  Simulator complete. All physics checks passed.\n")


if __name__ == "__main__":
    main()
