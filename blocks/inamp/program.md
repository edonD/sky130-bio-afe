# Instrumentation Amplifier

## Purpose

Amplify microvolt-level differential biosignals (ECG/EEG/EMG) while rejecting common-mode interference. This is the most critical block — it sets the noise floor for the entire system. Biosignals arrive as 1 µV to 5 mV differential, riding on 300 mV DC electrode offset and 1-10 mV 50/60 Hz powerline noise.

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

**You CANNOT modify:** `specs.json`, `program.md`, SKY130 PDK model files, `../../interfaces.md`.

**Critical rule:** Never game the process by editing PDK models, fabricating results, or tweaking evaluation to pass artificially.

## Evaluated Parameters

| Parameter | Target | Weight | What It Means |
|-----------|--------|--------|---------------|
| `gain_db` | > 34 dB | 15 | Closed-loop voltage gain (~50 V/V) |
| `input_referred_noise_uvrms` | < 1.5 µVrms | 25 | Total noise in 0.5–150 Hz band |
| `cmrr_60hz_db` | > 100 dB | 20 | Common-mode rejection at powerline frequency |
| `input_offset_uv` | < 50 µV | 15 | Systematic DC offset (referred to input) |
| `bandwidth_hz` | > 10 kHz | 10 | -3 dB bandwidth |
| `power_uw` | < 15 µW | 15 | Total power from 1.8V supply |

## Testbenches

### TB1: DC Gain and Operating Point
- Apply 1 mV differential, V_CM = 0.9V. Measure output, compute gain.
- Verify output stays within 0.2–1.6V (not railed).
- **Plot:** `plots/dc_gain.png`

### TB2: AC Frequency Response
- AC sweep 0.1 Hz to 1 MHz, differential input. Bode plot.
- **Pass:** Flat (±0.5 dB) from 0.5 to 150 Hz, BW > 10 kHz.
- **Plot:** `plots/ac_response.png`

### TB3: Common-Mode Rejection
- Apply 10 mV common-mode, sweep 1 Hz to 1 kHz. Compute CMRR = A_diff/A_cm.
- **Pass:** CMRR > 100 dB at 60 Hz.
- **Plot:** `plots/cmrr_vs_freq.png`

### TB4: Input-Referred Noise
- Noise analysis 0.1 Hz to 1 kHz. Integrate 0.5–150 Hz for total RMS.
- **Pass:** < 1.5 µVrms input-referred.
- **Plot:** `plots/noise_spectral_density.png` (V/√Hz vs frequency — should show 1/f corner and white noise floor)

### TB5: Input Offset
- Zero differential input. Measure output, compute input-referred offset.
- **Plot:** `plots/offset_measurement.png`

### TB6: Electrode Offset Tolerance
- Apply ±300 mV DC common-mode offset + 1 mV differential signal.
- **Pass:** Gain within ±1 dB of nominal. Output not saturated.
- **Plot:** `plots/electrode_offset_tolerance.png`

### TB7: Realistic ECG Transient
- Synthetic ECG (1 mV R-peak, 72 BPM) + 2 mV 60 Hz interference + 300 mV DC offset.
- **Pass:** ECG morphology preserved at output, 60 Hz rejected.
- **Plot:** `plots/ecg_transient.png`

### TB8: PVT Corner Analysis
- TB1 + TB4 across 5 corners × 3 temps = 15 minimum.
- **Pass:** All specs met at all corners.
- **Plot:** `plots/pvt_summary.png`

### TB9: Monte Carlo
- 200 samples if mismatch models available. Report offset and gain spread.
- **Plot:** `plots/monte_carlo.png`

## How to Evaluate Honestly

- **Noise:** Must be integrated over 0.5–150 Hz, not spot noise at one frequency. If you get < 0.1 µVrms, check the simulation — that's world-class for µA bias.
- **CMRR:** > 80 dB needs chopping or very careful matching. > 120 dB is exceptional — verify it's real.
- **Electrode offset:** This is where designs fail in the real world. Test with ±300 mV, not 0V.
- **If the output is railed (stuck at VDD or VSS):** The common-mode input range doesn't cover the electrode offset. Rethink the input stage.
- **If noise is too high:** Increase bias current (noise ∝ 1/√I) or increase input transistor W/L.
- **If CMRR is too low:** Check tail current source impedance, consider chopping, verify symmetry.

## Design Freedom

Choose everything:
- **Topology:** 3-opamp, current-feedback, capacitively-coupled, direct differential pair, etc.
- **Techniques:** Chopping, auto-zeroing, correlated double sampling — all fair game.
- **Optimization:** Any algorithm. `pip install` anything.

## README.md — Your Final Deliverable

The only thing I check. Must contain: status banner, spec table, all plots with analysis, circuit description, design rationale, what was tried/rejected, known limitations, experiment history.
