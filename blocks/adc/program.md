# 20-bit Sigma-Delta ADC

## Purpose

Digitize the conditioned biosignal with 20-bit effective resolution at 4 kSPS output rate. This is a complete redesign from the v1 12-bit SAR. The sigma-delta architecture uses oversampling and noise shaping to achieve resolution impossible with a SAR at this speed/power.

## Why Sigma-Delta

A SAR ADC achieves N bits by matching N capacitors. At 20 bits, that's 1M:1 matching — impossible. A sigma-delta instead:
1. Samples at high rate (oversampling ratio OSR, e.g., 256× above Nyquist)
2. Uses a 1-bit (or few-bit) quantizer — no matching needed
3. Shapes quantization noise out of the signal band with a feedback loop
4. A digital decimation filter removes the out-of-band noise

For 20-bit ENOB with a 2nd-order modulator: OSR = 256, output rate = 4 kSPS → modulator clock = 1.024 MHz. This is trivially achievable on 130nm.

## Architecture Overview

```
Vin → [Integrator 1] → [Integrator 2] → [Quantizer (1-bit)] → DOUT
         ↑                    ↑                  |
         └─── DAC1 ───────────└─── DAC2 ─────────┘ (feedback)

Modulator output (1-bit, 1.024 MHz) → [Sinc3 Decimation Filter] → 20-bit @ 4 kSPS
```

Key components:
- **Integrator 1**: Switched-capacitor integrator with high-gain OTA
- **Integrator 2**: Second integrator for 2nd-order noise shaping
- **Quantizer**: Simple comparator (1-bit = just a sign detector)
- **DAC**: 1-bit DAC = just a switch between +Vref and -Vref
- **Decimation filter**: Digital sinc3 filter (can be behavioral in simulation)

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
**You CANNOT modify files in other blocks.**

**Critical rule:** Never game the process. Every number must come from actual simulation.

## Evaluated Parameters

| Parameter | Target | Weight | What It Means |
|-----------|--------|--------|---------------|
| `enob` | > 18 bits | 30 | Effective number of bits from SINAD |
| `snr_db` | > 110 dB | 20 | Signal-to-noise ratio |
| `thd_db` | < -100 dB | 15 | Total harmonic distortion |
| `output_data_rate_sps` | > 4000 SPS | 10 | Decimated output rate |
| `power_uw` | < 100 µW | 15 | Total power |
| `input_range_v` | > 1.2 V | 10 | Differential input range |

**Margin rule:** Every spec must pass with >= 25% margin. A design at exactly 18.0 ENOB is a fail.

## Knowledge for the Design

### Sigma-Delta Fundamentals

For a 2nd-order modulator with OSR = 256:
- Theoretical SNR = 6.02×N + 1.76 + 30×log10(OSR) - 12.9 where N=1 bit
- SNR ≈ 6.02 + 1.76 + 30×2.408 - 12.9 ≈ 67 dB from quantization noise shaping alone
- Wait — that's only 11 bits. You need higher OSR or higher order.

Better formula for Lth-order, 1-bit, OSR:
- SNR ≈ 6.02 + 1.76 + (2L+1)×10×log10(OSR) − 10×log10(π^(2L) / (2L+1))
- For L=2, OSR=256: SNR ≈ 6.02 + 1.76 + 50×2.408 − 10×log10(π^4/5) ≈ 6.02+1.76+120.4-12.9 = 115 dB ≈ 18.8 bits

So 2nd-order, OSR=256 gives ~19 ENOB theoretically. To hit 20 ENOB you need either:
- OSR = 512 (doubles clock to 2 MHz — still fine for 130nm)
- 3rd-order modulator (more complex, stability concerns)
- Multi-bit quantizer (3-5 bits internal, needs DAC matching)

The agent can choose the tradeoff.

### Critical Design Challenges

1. **OTA gain and settling**: The integrator OTA needs >60 dB gain and must settle within half a clock cycle (~500 ns at 1 MHz). This is easy for 130nm.

2. **Capacitor noise**: kT/C noise on the sampling capacitor sets the noise floor. For SNR = 115 dB with 1.8V range: C_sample > kT/(V_range^2 × 10^(-SNR/10)) ≈ 4e-21 / (3.24 × 3e-12) ≈ 0.4 pF. Use 2-5 pF for margin.

3. **Modulator stability**: 2nd-order is unconditionally stable with proper coefficient scaling. 3rd-order needs careful design (clipping, reset logic).

4. **Decimation filter**: A sinc3 filter is standard. Can be implemented in Python (behavioral) for evaluation purposes — the modulator bitstream is what matters in SPICE.

5. **Clock generation**: Need a 1-2 MHz clock with non-overlapping phases for switched-capacitor operation. Can use an on-chip ring oscillator or external clock.

### Skip These Dead Ends

- Flash ADC sub-quantizer — overkill for 1-bit, adds complexity
- Continuous-time sigma-delta — elegant but harder to simulate in ngspice (no switched-cap equivalences)
- 4th+ order modulators — stability issues not worth the marginal OSR reduction

## Testbenches

### TB1: Modulator Output (Bitstream)
- Apply DC input at mid-scale. Run modulator for 4096 clock cycles.
- The bitstream density should be ~50% (equal ones and zeros).
- Apply DC at 3/4 scale — bitstream density should be ~75%.
- **Pass:** Bitstream density tracks input voltage linearly.
- **Plot:** `plots/bitstream.png`

### TB2: SNR and ENOB (THE KEY TEST)
- Apply sinusoidal input near signal-band edge (~100 Hz for 4 kSPS output).
- Run for enough cycles to get 8192+ output samples after decimation.
- FFT of decimated output. Compute SNR, SINAD, ENOB.
- **Pass:** ENOB > 18 bits (with 25% margin → target 22.5+ ENOB, but 18 is the hard floor).
- **Plot:** `plots/fft_spectrum.png` (output spectrum showing noise shaping — should see noise rising at higher frequencies)

### TB3: THD
- Full-scale sine input. Measure harmonics in FFT.
- **Pass:** THD < -100 dB.
- **Plot:** Same as TB2, annotate harmonics.

### TB4: Noise Floor
- Short input (0V differential). Run and decimate.
- The output code spread gives the noise floor.
- **Pass:** RMS noise < 1 LSB at 20-bit (< 1.7 µV for 1.8V range).
- **Plot:** `plots/noise_floor.png`

### TB5: Transfer Function (Linearity)
- Slow ramp input, decimate output codes.
- **Pass:** Monotonic, no missing codes, INL < 5 LSB at 20-bit.
- **Plot:** `plots/transfer_function.png`

### TB6: Power
- Measure average supply current during active conversion.
- **Pass:** < 100 µW total.
- **Plot:** `plots/power_breakdown.png`

### TB7: PVT
- TB2 across 5 corners × 3 temps.
- **Pass:** ENOB > 16 at all corners (relaxed for PVT).
- **Plot:** `plots/pvt_enob.png`

## How to Evaluate Honestly

- **ENOB must come from a proper FFT** of the decimated output, not from DC noise. Use coherent sampling or windowing.
- **The decimation filter matters.** A sinc3 at OSR=256 has specific passband droop and stopband rejection. Implement it correctly (not just averaging).
- **Modulator simulation is long.** For 4 kSPS with OSR=256, you need 256 clock cycles per output sample, and 8192+ samples for a good FFT. That's 2M clock cycles. At 1 MHz clock = 2 seconds of simulation time. With 0.1 ns timestep = 20 billion points. **Use behavioral elements where possible** — the OTA can be a VCVS with finite gain and bandwidth, the comparator can be ideal. Only use full transistor-level for the critical path.
- **If ENOB > 20, be suspicious.** That means < -120 dB noise floor. Verify the simulation has enough points and the FFT is windowed correctly.
- **Switched-cap common-mode issues**: Each integrator output must stay within the OTA's linear range. If it rails, the modulator is overloaded.

## Design Freedom

Choose everything:
- **Modulator order:** 2nd (safe) or 3rd (more resolution per OSR)
- **Quantizer bits:** 1-bit (simplest, no DAC matching) or multi-bit (more resolution but needs DEM or calibration)
- **OSR:** 128, 256, or 512
- **OTA topology:** Telescopic, folded cascode, two-stage
- **Implementation:** Full transistor-level or behavioral modulator + transistor-level critical blocks
- **Decimation:** Python-based sinc3 filter is fine for evaluation
- `pip install` anything

Research: search for "sigma-delta ADC SKY130", "2nd order sigma-delta modulator CMOS", "switched-capacitor integrator design". Murmann's ADC survey is a good reference for state-of-the-art FOM.

## README.md — Your Final Deliverable

Must contain: status, spec table, ALL testbench plots, modulator architecture, OTA design, noise budget, coefficient selection rationale, decimation filter design, comparison to Murmann ADC survey FOM, known limitations, experiment history.

## The Experiment Loop

LOOP FOREVER:

1. **Think.** Is the modulator stable? Does the bitstream look right? What does the FFT show?
2. **Modify.** Change `design.cir`, `evaluate.py`, or optimization scripts. ONLY this block.
3. **Commit.** `git add -A && git commit -m 'adc: <what you changed>'`
4. **Run.** `python evaluate.py > run.log 2>&1`
5. **Read results.** `grep "score\|PASS\|FAIL\|ENOB\|SNR" run.log | head -20`
6. **Study the plots.** Does the FFT show noise shaping (rising noise at high freq)? Is the bitstream density tracking the input?
7. **Log.** Append to `results.tsv`.
8. **Keep or discard.** Score improved AND noise shaping visible in FFT → keep. Otherwise investigate or revert.
9. **Repeat.** Never stop. Never touch other blocks.

## Plot Analysis

**`plots/fft_spectrum.png`** — THE critical plot. Must show the 2nd-order noise shaping: flat noise floor in-band, then rising at +40 dB/decade out of band. The signal peak should be clean. Harmonics should be > 100 dB below signal. If the noise floor is flat (no shaping), the feedback loop isn't working.

**`plots/bitstream.png`** — Modulator output for DC inputs. Should show pulse-density modulation — more 1s for higher input. If all 1s or all 0s, the modulator is overloaded. If random noise with no density change, the input isn't being sampled.

**System-level check:** "With 20-bit resolution over 1.8V range, 1 LSB = 1.7 µV. The InAmp output noise is ~0.5 µVrms × gain = ~40 µV at the ADC input. That's ~24 LSBs of noise — the ADC resolution is not wasted, but also not the bottleneck. The system noise is dominated by the analog front-end, not the ADC quantization. This is the correct design balance."
