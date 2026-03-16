# System Integration — Design Program

## What This Block Does

Connects all upstream blocks (bandgap, instrumentation amplifier, PGA, bandpass filter, ADC) into a complete single-channel biosignal acquisition path, then validates the full signal chain end-to-end. Also models the 4-channel system (shared bandgap, 4 independent analog chains).

## System Context

This is the final validation stage. Individual blocks have been designed and characterized in isolation. Integration must verify that:
1. Interface voltages are compatible (no saturation at block boundaries)
2. Noise from all blocks combines correctly (RSS of uncorrelated sources)
3. The full signal chain can acquire a real ECG/EEG/EMG signal
4. Total power budget is met
5. PVT robustness holds at the system level

## Evaluation Criteria

### TB1: DC Signal Chain Verification
- Connect bandgap → inamp → PGA → filter → ADC in SPICE
- Apply a known DC differential input to the InAmp
- Verify the signal propagates through each stage with correct gain
- Check voltage levels at each node stay within 0.2V–1.6V (linear region)
- **Pass:** End-to-end gain within ±5% of expected (InAmp gain × PGA gain)
- **Plot:** `plots/dc_signal_chain.png` (voltage at each node)

### TB2: Full-Chain Frequency Response
- AC analysis from 0.01 Hz to 1 MHz through the entire chain
- **Pass:** Passband matches 0.5–150 Hz, total gain matches InAmp × PGA setting
- **Plot:** `plots/system_frequency_response.png`

### TB3: System Noise
- Noise simulation of full chain (InAmp → PGA → Filter → ADC)
- Integrate input-referred noise from 0.5 to 150 Hz
- **Pass:** Total input-referred noise < 1.0 µVrms
- Compare to RSS of individual block contributions
- **Plot:** `plots/system_noise.png` (spectral density + cumulative RMS)

### TB4: System CMRR
- Apply 10 mV common-mode at 60 Hz to InAmp inputs
- Measure signal at ADC output (digital codes)
- Compute system CMRR
- **Pass:** CMRR > 100 dB at 60 Hz
- **Plot:** `plots/system_cmrr.png`

### TB5: ECG Acquisition
- Apply realistic synthetic ECG waveform (1 mV amplitude, 72 BPM, with P-QRS-T morphology)
- Add 300 mV electrode DC offset + 2 mV 60 Hz interference + baseline wander
- Set gains: InAmp=50x, PGA=8x (total 400x → 400 mV signal at ADC)
- Run transient for 5 seconds, digitize with ADC model
- Reconstruct signal from ADC codes
- **Pass:** R-peaks clearly visible, SNR > 40 dB, 60 Hz interference rejected
- **Plot:** `plots/ecg_acquisition.png` (input signal, output at each stage, reconstructed digital)

### TB6: EEG Acquisition
- Apply 50 µV EEG-like signal (alpha rhythm, 10 Hz)
- Set gains: InAmp=50x, PGA=128x (total 6400x → 320 mV at ADC)
- **Pass:** 10 Hz oscillation visible in ADC output, not buried in noise
- **Plot:** `plots/eeg_acquisition.png`

### TB7: Power Budget
- Sum power from all blocks at nominal operation
- **Pass:** Total < 50 µW per channel (bandgap shared across 4 channels, counted once at 1/4)
- **Plot:** `plots/power_breakdown.png` (pie chart or bar chart)

### TB8: PVT System Validation
- Run TB5 (ECG acquisition) at worst-case corners (ss_-40C_1.62V, ff_125C_1.98V)
- **Pass:** ECG still clearly acquired, SNR > 30 dB (relaxed)
- **Plot:** `plots/pvt_ecg.png`

### TB9: Dynamic Range
- Sweep input signal from 1 µV to 10 mV (at optimal PGA setting for each level)
- Compute SNR vs input level
- **Pass:** Dynamic range > 60 dB
- **Plot:** `plots/dynamic_range.png`

## Approach

Integration can use:
1. **Full SPICE**: Connect all subcircuits, run transient. Accurate but slow.
2. **Behavioral + SPICE**: Use measured transfer functions from upstream blocks, with small-scale SPICE for critical interfaces. Like the CIM project.
3. **Mixed**: SPICE for TB1-TB4 (short simulations), behavioral for TB5-TB9 (long transients).

The agent chooses the approach. What matters is that the results are physically credible.

## Interface to Upstream Blocks

Read `measurements.json` from each upstream block:
- `../bandgap/measurements.json` → V_REF, TC, PSRR, power
- `../inamp/measurements.json` → gain, noise, CMRR, offset, BW, power
- `../pga/measurements.json` → gain accuracy, noise, THD, BW, power
- `../filter/measurements.json` → cutoff frequencies, noise, power
- `../adc/measurements.json` → ENOB, DNL, INL, power, conversion time

## Files

| File | Purpose |
|------|---------|
| `specs.json` | System-level specs (DO NOT MODIFY) |
| `program.md` | This file |
| `CLAUDE.md` | Agent instructions |
| `evaluate.py` | System simulation and scoring |
| `measurements.json` | Final system measurements |
| `README.md` | System integration report |
