# Bandgap Voltage Reference — Design Program

## What This Block Does

Generates a process- and temperature-independent reference voltage (~1.2 V) and bias current (~1 µA) from the 1.8 V supply. Every other analog block in the bio-AFE depends on this reference for accuracy and stability.

## System Context

This is the foundational block. Its output voltage and current references are consumed by:
- **Instrumentation amplifier** — bias currents set the input stage operating point
- **PGA** — gain accuracy depends on reference stability
- **Filter** — tuning accuracy depends on bias current matching
- **ADC** — conversion accuracy directly proportional to V_REF stability

A 1% drift in V_REF causes a 1% gain error in the ADC, which for a 12-bit converter is ~40 LSBs. Temperature coefficient and supply rejection are critical.

## Evaluation Criteria

### TB1: DC Operating Point
- Simulate at nominal (TT, 27°C, 1.8V)
- Measure V_REF and total supply current
- **Pass:** V_REF between 1.15V and 1.25V, power < 20 µW
- **Plot:** `plots/dc_operating_point.png`

### TB2: Temperature Sweep
- Sweep temperature from -40°C to 125°C at nominal supply
- Measure V_REF vs temperature
- Compute TC = (V_max - V_min) / (V_nom × ΔT) in ppm/°C
- **Pass:** TC < 50 ppm/°C
- **Plot:** `plots/vref_vs_temperature.png` — must show the characteristic bandgap "bow" shape

### TB3: Supply Sweep (Line Regulation)
- Sweep VDD from 1.62V to 1.98V at nominal temperature
- Measure V_REF vs VDD
- Compute line regulation = ΔV_REF / ΔVDD in mV/V
- **Pass:** Line regulation < 5 mV/V, PSRR > 60 dB
- **Plot:** `plots/vref_vs_supply.png`

### TB4: Startup Transient
- Apply VDD as a ramp (0 → 1.8V in 10 µs)
- Monitor V_REF settling
- **Pass:** V_REF within 1% of final value in < 100 µs
- Must start reliably — no metastable states
- **Plot:** `plots/startup_transient.png`

### TB5: PVT Corner Analysis
- Run TB1+TB2 across all 5 process corners × 3 temperatures × 3 supplies = 45 corners
- **Pass:** V_REF stays within 1.15–1.25V at ALL corners
- **Plot:** `plots/pvt_corners.png` — overlay of V_REF(T) for all corners

### TB6: Monte Carlo Mismatch
- Run 200 Monte Carlo samples at nominal conditions (if mismatch models available)
- Report mean, std, worst-case V_REF
- **Pass:** 3σ spread < 30 mV
- **Plot:** `plots/monte_carlo_histogram.png`

## Interface

**Inputs:** `vdd`, `vss`
**Outputs:** `vref` (~1.2V), `ibias` (~1 µA)
**Startup:** Must self-start from zero — no external enable signal needed

## Design Constraints

- Single 1.8V supply only — no negative rails
- Must use SKY130 1.8V core devices (pfet_01v8, nfet_01v8)
- Parasitic PNP BJTs available in SKY130 (sky130_fd_pr__pnp_05v5_W3p40L3p40)
- Target area: minimize, but correctness over area
- Startup circuit required — the degenerate zero-current state must be avoided

## Parameters

The design will have tunable transistor sizes and resistor values. Define these in `parameters.csv` with reasonable min/max bounds. The optimizer is free to explore the space.

## Files

| File | Purpose |
|------|---------|
| `specs.json` | Target specifications (DO NOT MODIFY) |
| `program.md` | This file — evaluation requirements |
| `CLAUDE.md` | Agent instructions |
| `design.cir` | SPICE netlist (parametric) |
| `parameters.csv` | Parameter ranges |
| `evaluate.py` | Simulation runner and scorer |
| `measurements.json` | Final measured results |
| `best_parameters.csv` | Optimized parameter values |
| `README.md` | Design documentation with plots |
