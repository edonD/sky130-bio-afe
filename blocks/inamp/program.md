# Instrumentation Amplifier — Design Program

## What This Block Does

Amplifies the microvolt-level differential voltage between two body electrodes while rejecting the common-mode signal (powerline interference, DC electrode offset). This is the most critical block in the signal chain — it sets the noise floor for the entire system.

## System Context

Biosignals arrive as tiny differential voltages (1 µV to 5 mV) riding on top of large common-mode interference (300 mV DC electrode offset + 1-10 mV 50/60 Hz powerline). The instrumentation amplifier must:
- Amplify the differential signal by ~50 V/V (34 dB)
- Reject common-mode by >100 dB
- Add less than 1.5 µVrms of noise in the signal band
- Tolerate up to ±300 mV input DC offset without saturating

The output feeds the PGA, which expects a signal centered at ~0.9V with ±0.7V swing range.

## Evaluation Criteria

### TB1: DC Operating Point and Gain
- Apply a small differential input (1 mV) with V_CM = 0.9V
- Measure output voltage and compute gain
- Verify output stays within 0.2V–1.6V rail
- **Pass:** Gain > 34 dB (50 V/V), output centered near 0.9V
- **Plot:** `plots/dc_gain.png`

### TB2: AC Frequency Response
- AC sweep from 0.1 Hz to 1 MHz (differential input)
- Measure gain magnitude and phase vs frequency
- **Pass:** -3 dB bandwidth > 10 kHz, gain flat (±0.5 dB) from 0.5 to 150 Hz
- **Plot:** `plots/ac_response.png` (Bode plot)

### TB3: Common-Mode Rejection
- Apply 10 mV common-mode signal, sweep frequency 1 Hz to 1 kHz
- Measure output amplitude, compute CMRR = 20·log10(A_diff/A_cm)
- **Pass:** CMRR > 100 dB at 60 Hz
- **Plot:** `plots/cmrr_vs_freq.png`

### TB4: Input-Referred Noise
- Run noise analysis from 0.1 Hz to 1 kHz
- Integrate noise spectral density from 0.5 Hz to 150 Hz to get total RMS noise
- **Pass:** Input-referred noise < 1.5 µVrms
- **Plot:** `plots/noise_spectral_density.png` (V/√Hz vs frequency)

### TB5: Input Offset
- Measure output with zero differential input, extract input-referred offset
- If chopping is used, verify residual offset after chopping
- **Pass:** Input-referred offset < 50 µV
- **Plot:** `plots/offset_measurement.png`

### TB6: Large Signal / Electrode Offset Tolerance
- Apply ±300 mV DC offset on both inputs (common-mode)
- Simultaneously apply 1 mV differential signal
- Verify the amplifier still functions (gain, linearity)
- **Pass:** Gain within ±1 dB of nominal with 300 mV CM offset
- **Plot:** `plots/electrode_offset_tolerance.png`

### TB7: Transient with Realistic ECG
- Apply a synthetic ECG waveform (R-peak ~1 mV, 1 Hz rate) plus 60 Hz interference
- Verify clean amplified output
- **Pass:** ECG morphology preserved, 60 Hz rejected
- **Plot:** `plots/ecg_transient.png`

### TB8: PVT Corner Analysis
- Run TB1 + TB4 across 5 corners × 3 temperatures = 15 combinations minimum
- **Pass:** All specs met at ALL corners
- **Plot:** `plots/pvt_summary.png`

## Interface

**Inputs:** `inp` (positive electrode), `inn` (negative electrode), `vref` (from bandgap, ~1.2V), `ibias` (from bandgap, ~1 µA)
**Outputs:** `vout` (amplified signal, centered at ~0.9V)
**Common-mode input range:** 0.5V to 1.3V (with ±300 mV electrode offset from 0.9V midpoint)

## Design Constraints

- Single 1.8V supply — no negative rail available
- Must handle rail-to-rail input common-mode is NOT required, but ±300 mV around mid-supply is
- Chopping is recommended for offset and 1/f noise reduction, but not mandated
- SKY130 1.8V core devices only (pfet_01v8, nfet_01v8)
- Feedback resistors: use poly resistors (sky130_fd_pr__res_*) or MOSFET-based

## Parameters

Define transistor W/L values, bias currents, chopping frequency (if used), and feedback resistor values in `parameters.csv`.
