# Programmable Gain Amplifier (PGA) — SKY130

## Status: Phase B Complete (Score 1.00, 7/7 specs met, PVT PASS)

## Architecture

Inverting amplifier with two-stage Miller-compensated CMOS opamp (NMOS input differential pair). Gain is set by the ratio Rf/Rin with Rf fixed at 10 MΩ and Rin switched for each gain setting.

**Opamp topology:**
- NMOS input diff pair (W=8u L=4u, 1µA/side) — chosen for 0.9V CM compatibility with 1.8V supply
- PMOS active load current mirror (W=4u L=8u) — long L for high DC gain
- PMOS common-source second stage (W=8u L=8u)
- NMOS current source load (W=2u L=8u, 2µA)
- Miller compensation: ~1.6 pF MIM cap + 1.5kΩ nulling resistor
- Ideal 1µA bias current source (to be replaced with bandgap reference)

**PGA configuration:**
- V+ of opamp tied to VCM = 0.9V
- Rf = 10 MΩ (fixed)
- Rin = Rf/G (switched for each gain: 10M, 5M, 2.5M, 1.25M, 625k, 312.5k, 156.25k, 78.125k)
- Output DC = VCM = 0.9V (independent of gain setting)

## Measured vs Target

| Parameter | Measured | Target | Margin | Status |
|-----------|----------|--------|--------|--------|
| Gain settings | 8 (all pass) | >= 7 | +1 | PASS |
| Gain error | 0.65% (worst, G=128) | < 1% | 35% | PASS |
| Bandwidth (G=128) | 14.8 kHz | > 10 kHz | 48% | PASS |
| Output noise (G=1) | 25.8 µVrms | < 50 µVrms | 48% | PASS |
| THD (10 Hz, 1 Vpp) | 0.0017% (hi-fi) | < 0.1% | 98% | PASS |
| Power | 9.3 µW | < 10 µW | 7% | PASS |
| Settling time | 78.2 µs | < 100 µs | 22% | PASS |

## Gain Error at Each Setting

| Gain | Measured | Error |
|------|----------|-------|
| 1 | 1.000 | 0.01% |
| 2 | 2.000 | 0.02% |
| 4 | 3.999 | 0.03% |
| 8 | 7.996 | 0.05% |
| 16 | 15.986 | 0.09% |
| 32 | 31.947 | 0.17% |
| 64 | 63.791 | 0.33% |
| 128 | 127.164 | 0.65% |

## Key Plots

### Gain Accuracy (TB1)
![Gain Accuracy](plots/gain_accuracy.png)
All 8 gain settings match ideal within 1%. Error increases with gain due to finite opamp DC gain (expected).

### AC Response (TB2)
![AC Response](plots/ac_response.png)
All gain settings show proper Bode response. GBW ≈ 850 kHz. BW at G=128 is 15.5 kHz, comfortably above 10 kHz target. Minor peaking at G=1/G=2 around 800 kHz (phase margin concern at low gain — not an issue for biosignal bandwidth).

### Noise Spectrum (TB3)
![Noise](plots/noise_spectrum.png)
1/f dominated noise spectrum (expected for NMOS input at these frequencies). Integrated 0.5-150 Hz: 25.6 µVrms output-referred at gain=1.

### THD Analysis (TB4)
![THD](plots/thd_analysis.png)
Clean 10 Hz sinusoid, 1 Vpp output (0.4V to 1.4V). Harmonics >60 dB below fundamental. THD = 0.089%.

### Step Response (TB5)
![Settling](plots/gain_switching.png)
1 mV step at gain=128. Clean monotonic settling without ringing. Settles to 0.1% within 71.5 µs. No oscillation — good phase margin at high gain.

## Design Rationale

1. **NMOS input diff pair** instead of PMOS: With 0.9V CM input and 1.8V supply, a PMOS diff pair would leave only ~0.005V for the tail current source (measured). NMOS leaves ~0.26V for the tail, ensuring proper current source saturation.

2. **10 MΩ feedback resistor**: High Rf minimizes loading on the opamp output. With Rf=100kΩ (initial attempt), the second stage gain was only ~6x (loaded by Rf). With 10MΩ, the resistive loading is negligible compared to the output impedance.

3. **Long channel lengths** (L=4-8µ): Increase output impedance (rds ∝ L) for high DC gain, at the cost of reduced GBW. The design has enough GBW margin for the 10 kHz bandwidth spec.

4. **Miller compensation with nulling resistor**: 1.6 pF MIM cap provides dominant pole splitting. 1.5kΩ Rz pushes the RHP zero to high frequency.

## Failed Ideas

1. **PMOS input diff pair** (runs 0-4): Tail current source in deep triode at 0.9V CM. Only 200 kHz GBW, poor gain accuracy.

2. **100kΩ Rf** (runs 0-3): Resistive loading of opamp output destroyed second-stage gain. 20% gain error at G=128.

3. **Short channel opamp** (L=0.5-1u): Insufficient DC gain (~400 V/V). Needed >10,000 V/V for <1% error at G=128.

## Known Limitations

1. **Bias current**: Uses ideal current source. Needs bandgap/current mirror in integration.
2. **Resistor values**: 10 MΩ poly resistors require ~5000 squares — very large area. Real implementation might use T-network or capacitive feedback to reduce resistor values.
3. **Phase margin at G=1**: Step response shows 69.6% overshoot at noise gain=2 (gain=1 inverting). This indicates ~20° phase margin. The ringing settles in 2.6 µs, which is irrelevant for biosignal bandwidth (150 Hz). Cause: M6 gate capacitance (W=16u L=8u ≈ 853 fF) comparable to Cc (1.6 pF), creating a parasitic pole. Tradeoff: reducing M6 W improves PM but worsens THD and DC gain. Could be improved with higher Cc at the cost of BW margin.
4. **Output swing**: At G=128, max linear output swing is ±5.5 mV around VCM=0.9V. Only suitable for very small signals (EEG: 10-100 µV).
5. **Power margin**: 12% margin at nominal (8.8 µW). Acceptable but not generous.
6. **Gain switching**: Current design uses parameterized Rin. Real implementation needs transmission gates with on-resistance << Rin.

## PVT Corner Results (TB6)

![PVT Gain](plots/pvt_gain.png)

Tested gain=128 across 5 corners x 3 temperatures (15 conditions). Relaxed target: gain error < 2%.

| Corner | -40C Error | 27C Error | 125C Error | -40C BW | 27C BW | 125C BW |
|--------|-----------|----------|-----------|---------|--------|---------|
| tt | 0.67% | 0.65% | 0.67% | 16.6 kHz | 14.5 kHz | 11.5 kHz |
| ss | 0.72% | 0.69% | 0.69% | 16.6 kHz | 13.8 kHz | 11.5 kHz |
| ff | 0.64% | 0.63% | 0.65% | 17.4 kHz | 14.5 kHz | 12.0 kHz |
| sf | 0.87% | 0.82% | 0.79% | 17.4 kHz | 14.5 kHz | 12.0 kHz |
| fs | 0.58% | 0.57% | 0.60% | 16.6 kHz | 13.8 kHz | 11.5 kHz |

- **Worst gain error**: 0.87% (SF, -40C) — within both 1% nominal and 2% PVT limits
- **Worst BW**: 11.5 kHz (tt/ss/fs, 125C) — 15% margin above 10 kHz target
- **All 15 conditions PASS**

## Phase B Additional Verification

### Output Swing
Tested at gain=1 with 0.7V amplitude input: output 0.200V to 1.600V (1.40 Vpp). Matches the 0.2-1.6V interface spec exactly.

### THD vs Amplitude
| Output Vpp | THD |
|-----------|------|
| 0.6V | 0.021% |
| 0.8V | 0.021% |
| 1.0V | 0.021% |
| 1.2V | 0.021% |

THD is flat across amplitudes (0.021% from quick FFT). A high-fidelity measurement (10 cycles, 10µs step, 100k points) reveals the true THD is **0.0017%** — the 0.021% was the FFT noise floor. Individual harmonics: H2=-103dB, H3=-109dB, H4=-112dB. This represents 60x margin over the 0.1% spec.

### Realistic EEG Signal
50 µV input at G=128: output Vpp = 12.72 mV (expected 12.8 mV). Clean, no clipping, centered at VCM.

### Source Impedance Sensitivity
With 1kΩ InAmp source impedance in series at G=128: gain drops from 127.2 to 125.6 (1.3% reduction). Predictable and calibratable — the source impedance adds to Rin.

### Output Impedance
| Frequency | Zout |
|-----------|------|
| 1 Hz | 428 Ω |
| 10 kHz | 804 Ω |

Well within the <10 kΩ interface requirement for driving the filter block.

### Power Supply Rejection (PSRR)
At gain=128: PSRR = -24.7 dB (DC through 60 Hz). This is limited by the ideal current source which has zero supply rejection. In the integrated system, the bandgap reference (target >60 dB PSRR) would dominate, making system PSRR much better. For standalone PGA testing, VDD should be clean or well-decoupled.

## Experiment History

| Step | Score | Specs | Key Change |
|------|-------|-------|------------|
| 0 | 0.00 | 0/7 | PMOS input opamp, wrong bias polarity |
| 1 | 0.00 | 0/7 | Fixed bias, fixed mirror polarity |
| 2 | 0.35 | 3/7 | NMOS input opamp, working OP |
| 3 | 0.50 | 4/7 | Longer L for DC gain |
| 4 | 0.65 | 5/7 | Rf=500k reduces loading |
| 5 | 0.80 | 6/7 | Rf=4M, L=8u load |
| 6 | 0.90 | 6/7 | Rf=8M, L=8u diff pair (settling fail) |
| 7 | 1.00 | 7/7 | W=8u L=4u diff pair, Rf=10M, Cc=1.6pF |
| 8 | 1.00 | 7/7 | Wider 2nd stage (W=16u) → 0.65% err, 0.021% THD, PVT all pass |
| 9 | 1.00 | 7/7 | 0.9uA bias → 8.8uW power (12% margin), PVT all pass, all margins healthy |
| 10 | 1.00 | 7/7 | Phase B complete: PVT, output swing, THD sweep, Zout, EEG signal verified |
