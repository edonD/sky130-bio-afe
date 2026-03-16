# Bandgap Reference Agent

Autonomous analog IC designer working on a bandgap voltage reference for a biomedical AFE chip.

Follow the experiment loop defined in `../../CLAUDE.md`.

## Setup

Read these files before starting:
1. `program.md` — evaluation criteria and testbench requirements
2. `specs.json` — target specifications (the only constraints)
3. `../../interfaces.md` — interface contracts and technology constants
4. `../../master_spec.json` — system-level context

## Freedom

You can modify ANY file except `specs.json`. You choose:
- The circuit topology (Brokaw, Banba, sub-1V, self-biased, etc.)
- Transistor sizes, resistor values, current levels
- The optimization method (sweep, Bayesian, differential evolution, etc.)
- Any Python packages you need: `pip install` anything
- Whether to use BJTs, MOSFET-only, or hybrid approaches

## Quality Requirements

### Physical Realism
- All simulations must use the SKY130 PDK models (`.lib` statements)
- Transient simulations must run long enough for settling (especially startup)
- Temperature sweeps must cover the full -40°C to 125°C range
- Supply sweeps must cover ±10% (1.62V to 1.98V)

### Anti-Benchmaxxing
1. Never report V_REF without checking it across temperature — a fixed voltage source is not a bandgap
2. The startup circuit must work — simulate from VDD=0 and verify no stuck states
3. Report BOTH nominal AND worst-case PVT numbers
4. If TC looks suspiciously good (<5 ppm), verify with finer temperature steps
5. Check that the bias point is stable (operating point analysis, not just transient)

### Sanity Checks
- V_REF should be near 1.2V (silicon bandgap voltage) — if it's 0.6V or 1.8V, something is wrong
- Power should be µW range, not mW — this is a reference, not a power amplifier
- TC curve should show the classic "bow" shape — flat in the middle, rising at extremes
- PSRR should improve with cascode or regulation — bare mirrors give ~30-40 dB

## Tools

- ngspice for SPICE simulation
- Python (numpy, scipy, matplotlib) for analysis and optimization
- SKY130 PDK models in `sky130_models/` or via `.lib` include path
- Web search for researching bandgap topologies and design techniques
