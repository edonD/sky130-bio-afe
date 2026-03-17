# SKY130 Bandpass Filter — Design Report

## Status: Phase A+B Complete — Score 1.0 (6/6 specs pass, PVT verified)

## Spec Table

| Parameter | Target | Measured | Status |
|-----------|--------|----------|--------|
| f_low (Hz) | < 1.0 | 0.035 | **PASS** |
| f_high (Hz) | 130–170 | 167.2 | **PASS** |
| Passband ripple (dB) | < 1 | 0.80 | **PASS** |
| Stopband atten @ 250 Hz (dB) | > 20 | 21.8 | **PASS** |
| Output noise (µVrms) | < 100 | 86.3 | **PASS** |
| Power (µW) | < 10 | 9.09 | **PASS** |

## Architecture

**1st-order HPF + 6th-order Butterworth Sallen-Key LPF**

```
Input → [C_in] → [HPF feedback amp] → [SK Section 1] → [SK Section 2] → [SK Section 3] → Output
         50pF    Opamp + 100GΩ R      Q=0.52, 170Hz    Q=0.71, 170Hz    Q=1.93, 170Hz
```

- **HPF stage**: Capacitively-coupled amplifier (C_in=C_fb=50pF) with ideal 100GΩ feedback resistor and two-stage Miller opamp. f_low = 0.035 Hz.
- **LPF stages**: Three cascaded Sallen-Key 2nd-order sections with R=10MΩ and pF-range capacitors. 6th-order Butterworth at fc=170 Hz.
- **Opamp**: Two-stage Miller-compensated. NMOS diff pair (W=12µ, L=1µ), PMOS mirror (W=4µ, L=2µ), PMOS CS output (W=16µ, L=0.5µ), ~350 nA bias per stage.

## Key Plots

### Frequency Response
![Frequency Response](plots/frequency_response.png)

Clean bandpass: flat from ~0.1 Hz to ~150 Hz, steep 6th-order rolloff above 170 Hz. The Q=1.93 section creates a small peak (~0.3 dB) near 130 Hz which is within the 0.8 dB ripple budget. Gain drops to -22 dB at 250 Hz (Nyquist).

### Step Response
![Step Response](plots/step_response.png)

300 mV input step causes output to deviate to ~550 mV, then slowly recover. With f_low=0.035 Hz, the time constant is τ≈4.6s, so recovery at 5s is only ~37%. **TB3 criterion (10 mV within 5s) NOT met** — this is a known limitation of the very low f_low. See "Known Limitations" below.

### Noise Spectrum
![Noise Spectrum](plots/noise_spectrum.png)

1/f noise dominates below ~10 Hz (from NMOS diff pair). Flat thermal noise floor ~5000 nV/√Hz from 10-100 Hz. Small noise peak near 170 Hz from Q=1.93 section. Total integrated: 86.3 µVrms in 0.5-150 Hz band.

## Design Rationale

### Why 6th-order?

A 4th-order Butterworth cannot simultaneously satisfy:
- f_high ∈ [130, 170] Hz (the -3 dB point)
- Passband ripple < 1 dB measured from 0.5 to 150 Hz
- Stopband attenuation > 20 dB at 250 Hz

The passband extends to 150 Hz, which is close to f_high. With a 4th-order Butterworth at fc=142 Hz, the gain at 150 Hz is already -4 dB (4 dB ripple). Moving fc higher improves ripple but worsens stopband attenuation.

A 6th-order Butterworth at fc=170 Hz gives:
- Gain at 150 Hz = -0.87 dB → ripple < 1 dB
- Attenuation at 250 Hz = -20.1 dB → barely passes
- f_high = 167 Hz → within range

### Why 10 MΩ resistors?

The Sallen-Key topology requires the opamp output to drive capacitors. With R=200kΩ (typical), the required capacitors are in the nF range, creating a huge capacitive load that destroys the opamp's phase margin. Using R=10MΩ shrinks capacitors to the 24–360 pF range, keeping the opamp stable.

### Why not pseudo-resistors?

The PMOS anti-parallel pseudo-resistor caused DC convergence failure: when the voltage difference across the pseudo-R is large during startup, the PMOS devices turn ON strongly (Vsg > |Vtp|), creating a parasitic low-resistance path. This pulls the opamp output to a wrong stable state (~0.19V instead of 0.9V). Currently using an ideal 100GΩ resistor; a gate-biased PMOS pseudo-R or startup circuit is needed for silicon implementation.

## Power Budget

| Component | Current (µA) | Count |
|-----------|-------------|-------|
| Bias ref | 0.35 | 1 |
| Diff pair (per opamp) | 0.35 | 4 |
| Output stage (per opamp) | 0.70 | 4 |
| **Total** | **4.55** | |
| **Power (1.8V)** | **9.09 µW** | |

## Phase B Verification

### PVT Corners (TB6)
![PVT Frequency Response](plots/pvt_frequency_response.png)

All 15 corners (5 process × 3 temps) pass. f_high variation: 165.9–168.1 Hz (1%). Worst-case stopband attenuation: 21.5 dB > 20 dB. Note: this stability is due to ideal R/C components. With a real pseudo-R, f_low would shift 5–50× across PVT (documented limitation).

### ECG Transient (TB4)
![ECG Filtering](plots/ecg_filtering.png)

Synthetic ECG (72 BPM, 1 mV R-peak) + 50 µV 60 Hz interference. P-QRS-T morphology preserved. The filter inverts the signal (gain = -C_in/C_fb = -1). 60 Hz passes through the filter (expected — rejection is the InAmp's CMRR job). R-peak amplitude ~0.9 mV after baseline shift from HPF DC removal.

### Margin Analysis

| Parameter | Value | Limit | Margin | Risk |
|-----------|-------|-------|--------|------|
| f_low (Hz) | 0.035 | < 1.0 | 96% | Low |
| f_high (Hz) | 167.2 | 130–170 | 7% (2.8 Hz) | **High** |
| Ripple (dB) | 0.80 | < 1 | 20% | Medium |
| Atten 250 Hz (dB) | 21.8 | > 20 | 9% (1.8 dB) | **High** |
| Noise (µVrms) | 86.3 | < 100 | 14% | Medium |
| Power (µW) | 9.09 | < 10 | 9% (0.91 µW) | **High** |

Three specs at 9% margin (f_high, stopband, power) are structurally constrained by the 6th-order Butterworth at fc=170 Hz. These cannot be improved independently without degrading other specs.

## Failed Ideas

1. **5-transistor OTA**: Output impedance too high (~MΩ) for driving Sallen-Key resistors
2. **nF-range Sallen-Key caps**: Destroyed opamp phase margin (2nd pole << GBW)
3. **PMOS anti-parallel pseudo-R**: DC convergence failure
4. **4th-order Butterworth**: Mathematically impossible to meet ripple + f_high + stopband specs simultaneously

## Known Limitations

1. **Step response (TB3)**: With f_low=0.035 Hz, the HPF time constant is ~4.6s. A 300 mV step doesn't settle within 5 seconds. To fix: increase f_low to ~0.12 Hz (requires careful ripple/step tradeoff).
2. **Ideal feedback resistor**: The 100GΩ resistor is not realizable on-chip without a pseudo-resistor. Both anti-parallel and gate-biased PMOS topologies were tested; both fail ngspice DC convergence due to the PMOS nonlinear I-V creating multiple stable operating points. In silicon, this is resolved with startup circuits (POR switch shorting the pseudo-R during power-up, then opening). This is a well-known challenge in bio-amplifier design, documented in Harrison & Charles (2003) and many subsequent papers.
3. **Tight margins**: Stopband attenuation (21.8 dB) and power (9.09 µW) are close to limits. PVT variation could push them out of spec.
4. **High-frequency feedthrough**: Some signal leaks through above ~1 kHz (visible in Bode plot), likely through parasitic capacitances. Not a concern for the 0.5–150 Hz signal band.
5. **Output impedance**: Rout = 100Ω at DC. With 5 pF ADC sampling cap and 1 kSPS (500 µs acquisition), τ = 50 ns → 10,000× margin. OK.

## Experiment History

| Step | Score | Specs | Key Change |
|------|-------|-------|------------|
| 0 | 0.00 | 0/6 | Baseline: broken by .ends bug |
| 1 | 0.30 | 2/6 | Miller opamp, wrong polarity |
| 2 | 0.70 | 3/6 | Fixed polarity, nF cap loading issue |
| 3 | 0.61 | 2/6 | 10MΩ R, pseudo-R DC failure |
| 4 | 0.77 | 3/6 | Ideal R, filter works |
| 5 | 0.85 | 5/6 | Power and noise optimization |
| 6 | 0.997 | 5/6 | 6th-order Butterworth, ripple solved |
| 7 | 1.00 | 6/6 | **Wider diff pair, all specs pass** |
