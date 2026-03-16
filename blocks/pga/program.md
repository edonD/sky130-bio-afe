# Programmable Gain Amplifier

## Purpose

Provide digitally-selectable gain from 1x to 128x in binary steps (1, 2, 4, 8, 16, 32, 64, 128). Combined with the InAmp's fixed ~50x, the total system gain ranges from 50x to 6400x — mapping µV biosignals to the ADC's 0-1.8V input range.

## Files

| File | Editable? | Purpose |
|------|-----------|---------|
| `specs.json` | **NO** | Pass/fail targets. Never modify. |
| `program.md` | **NO** | This file. |
| `design.cir` | YES | Your SPICE netlist. |
| `parameters.csv` | YES | Parameter ranges for optimizer. |
| `evaluate.py` | YES | Simulation runner and scoring. |
| `best_parameters.csv` | YES | Current best values. |
| `measurements.json` | YES | Output measurements. |
| `README.md` | YES | **Your final deliverable.** |
| `plots/` | YES | All generated plots. |

**You CANNOT modify:** `specs.json`, `program.md`, SKY130 PDK model files.

**Critical rule:** Never game the process by editing PDK models or fabricating results.

## Evaluated Parameters

| Parameter | Target | Weight | What It Means |
|-----------|--------|--------|---------------|
| `gain_settings` | >= 7 | 15 | Number of discrete gain steps |
| `gain_error_pct` | < 1% | 20 | Worst-case gain error across all settings |
| `bandwidth_hz` | > 10 kHz | 15 | -3 dB BW at maximum gain (128x) |
| `output_noise_uvrms` | < 50 µVrms | 15 | Output noise at gain=1, 0.5-150 Hz |
| `thd_pct` | < 0.1% | 15 | THD at 10 Hz, 1 Vpp output |
| `power_uw` | < 10 µW | 10 | Total power |
| `settling_time_us` | < 100 µs | 10 | Settling after gain change |

## Testbenches

### TB1: Gain Accuracy at All Settings
- Set each gain (1, 2, 4, 8, 16, 32, 64, 128). Apply 10 mV input at 10 Hz. Measure output.
- **Pass:** Gain error < 1% at every setting.
- **Plot:** `plots/gain_accuracy.png` (ideal vs measured at each step)

### TB2: Frequency Response
- AC sweep at gain=1 and gain=128.
- **Pass:** BW > 10 kHz at gain=128.
- **Plot:** `plots/ac_response.png` (overlay all gain settings)

### TB3: Noise
- Noise analysis at gain=1, integrate 0.5–150 Hz.
- **Plot:** `plots/noise_spectrum.png`

### TB4: Linearity (THD)
- 10 Hz sine, 1 Vpp output. FFT of transient.
- **Pass:** THD < 0.1%.
- **Plot:** `plots/thd_analysis.png`

### TB5: Gain Switching Transient
- Switch gain from 1x to 128x mid-simulation.
- **Pass:** Settles within 0.1% in < 100 µs.
- **Plot:** `plots/gain_switching.png`

### TB6: PVT + Monte Carlo
- TB1 across 5 corners × 3 temps. Gain error < 2% at all corners (relaxed).
- 200 MC samples if available.
- **Plots:** `plots/pvt_gain.png`, `plots/monte_carlo.png`

## How to Evaluate Honestly

- **Test ALL 8 gain settings**, not just one. A PGA that works at gain=1 but fails at gain=128 is broken.
- **THD requires a proper FFT** of a transient simulation, not AC analysis.
- **At gain=128 with 10 kHz BW**, the opamp needs GBW > 1.28 MHz. If BW is failing, the opamp is too slow.
- **Input signals are centered at 0.9V** (from InAmp output), not ground-referenced. Test with realistic bias.
- **If gain error > 5%**, the feedback network or topology is probably wrong, not just a sizing issue.

## Design Freedom

Choose: resistive feedback, capacitive feedback, T-network, R-2R, current steering, any opamp topology. Any optimization method.

## README.md — Your Final Deliverable

Must contain: status, spec table, all plots with analysis, circuit description, rationale, tried/rejected, limitations, experiment history.
