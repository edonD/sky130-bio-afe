# 12-bit SAR ADC

## Purpose

Digitize the conditioned biosignal into 12-bit words at 1 kSPS per channel. 12-bit resolution gives 0.44 mV/LSB over 1.8V. With the front-end gain, this maps to 0.069–8.8 µV/LSB input-referred — adequate for both ECG and EEG.

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

**Critical rule:** Never game the process by editing PDK models or fabricating results. If DNL is perfect (< 0.01 LSB) without mismatch models, that's a simulation artifact, not a real result.

## Evaluated Parameters

| Parameter | Target | Weight | What It Means |
|-----------|--------|--------|---------------|
| `enob` | > 10 bits | 25 | Effective number of bits (from SINAD) |
| `dnl_lsb` | < 1.0 LSB | 20 | Worst-case differential nonlinearity (no missing codes) |
| `inl_lsb` | < 2.0 LSB | 15 | Worst-case integral nonlinearity |
| `conversion_time_us` | < 500 µs | 10 | Time for one 12-bit conversion |
| `power_uw` | < 10 µW | 15 | Power at 1 kSPS |
| `input_range_v` | > 1.5 V | 15 | Usable analog input range |

## Testbenches

### TB1: Static Linearity (DNL/INL)
- Ramp or histogram test: slow ramp across full input range, collect all 4096 codes.
- Compute DNL and INL for every code.
- **Pass:** DNL < 1.0 LSB (no missing codes), INL < 2.0 LSB.
- **Plot:** `plots/dnl_inl.png` (DNL and INL vs code — full 4096 codes, not a subset)

### TB2: Dynamic Performance (ENOB)
- Sinusoidal input near Nyquist/4 (~125 Hz). 4096-point FFT of output codes.
- Compute SINAD, ENOB, SFDR, THD.
- **Pass:** ENOB > 10 bits.
- **Plot:** `plots/fft_spectrum.png` (output spectrum with ENOB, SFDR annotated)

### TB3: Conversion Timing
- Measure total time from sample to valid digital output.
- **Pass:** < 500 µs.
- **Plot:** `plots/conversion_timing.png` (show comparator decisions, SAR logic, bit-by-bit approximation)

### TB4: Power
- Average supply current at 1 kSPS.
- **Pass:** < 10 µW.
- **Plot:** `plots/power_vs_sample_rate.png`

### TB5: Transfer Function
- DC sweep 0V to 1.8V. Plot output code vs input voltage.
- **Pass:** Usable range > 1.5V, monotonic.
- **Plot:** `plots/transfer_function.png`

### TB6: Noise Floor
- DC input at mid-scale, collect 1000 samples. Compute RMS code noise.
- **Pass:** < 1.5 LSB rms.
- **Plot:** `plots/noise_histogram.png`

### TB7: PVT + Monte Carlo
- DNL/INL across 5 corners × 3 temps. DNL < 1.5 LSB at all corners.
- 200 MC samples: report ENOB spread.
- **Plots:** `plots/pvt_linearity.png`, `plots/monte_carlo.png`

## How to Evaluate Honestly

- **DNL/INL must cover the FULL 4096 codes.** Measuring 100 codes and extrapolating is not valid.
- **ENOB from FFT requires coherent sampling.** Choose input frequency so an integer number of cycles fits in the FFT window, or use windowing.
- **At 12 bits, capacitor mismatch dominates.** If DNL is suspiciously perfect (< 0.01 LSB), mismatch is probably not being modeled. Document this.
- **At 1 kSPS, conversion time should be << 1 ms.** An async SAR with 12 bits at ~50 ns/bit = 600 ns total. There's massive timing margin — don't over-design for speed.
- **Power at 1 kSPS should be very low.** If > 50 µW, the comparator is burning static current or the clock is pointlessly fast.
- **Check that V_REF is stable during conversion** (charge sharing between DAC capacitors and reference can cause V_REF droop).
- **The SAR approximation waveform should show clean bit-by-bit convergence.** If bits are flipping back and forth, the comparator is too slow or the DAC isn't settling.

## Design Freedom

Choose: binary-weighted cap DAC, split-cap, C-2C, segmented. StrongARM comparator, double-tail, any other. Synchronous or asynchronous SAR logic. Any optimization method. The JKU open-source 12-bit SAR (SKY130_SAR-ADC1) exists as reference but you can design from scratch.

## README.md — Your Final Deliverable

Must contain: status, spec table, all plots with analysis, circuit description (comparator topology, DAC architecture, SAR logic), rationale, tried/rejected, limitations (especially mismatch sensitivity), experiment history.
