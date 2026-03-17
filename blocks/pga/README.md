# Programmable Gain Amplifier (PGA) — SKY130

## Status: Phase B In Progress (Score 1.00, 7/7 specs met, PVT PASS)

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

| Parameter | Measured | Target | Status |
|-----------|----------|--------|--------|
| Gain settings | 8 (all pass) | >= 7 | PASS |
| Gain error | 0.87% (worst, G=128) | < 1% | PASS |
| Bandwidth (G=128) | 15.5 kHz | > 10 kHz | PASS |
| Output noise (G=1) | 25.6 µVrms | < 50 µVrms | PASS |
| THD (10 Hz, 1 Vpp) | 0.089% | < 0.1% | PASS |
| Power | 7.4 µW | < 10 µW | PASS |
| Settling time | 71.5 µs | < 100 µs | PASS |

## Gain Error at Each Setting

| Gain | Measured | Error |
|------|----------|-------|
| 1 | 1.000 | 0.01% |
| 2 | 2.000 | 0.02% |
| 4 | 3.999 | 0.03% |
| 8 | 7.995 | 0.06% |
| 16 | 15.981 | 0.12% |
| 32 | 31.928 | 0.23% |
| 64 | 63.717 | 0.44% |
| 128 | 126.880 | 0.87% |

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
3. **Phase margin at G=1**: AC response shows some peaking near 800 kHz. While outside biosignal BW, this needs investigation in Phase B.
4. **Output swing**: At G=128, max linear output swing is ±5.5 mV around VCM=0.9V. Only suitable for very small signals (EEG: 10-100 µV).
5. **SF corner gain error**: 1.13% at G=128 (exceeds 1% nominal spec, within 2% relaxed PVT spec). Could be improved with higher DC gain margin.
6. **Gain switching**: Current design uses parameterized Rin. Real implementation needs transmission gates with on-resistance << Rin.

## PVT Corner Results (TB6)

![PVT Gain](plots/pvt_gain.png)

Tested gain=128 across 5 corners x 3 temperatures (15 conditions). Relaxed target: gain error < 2%.

| Corner | -40C Error | 27C Error | 125C Error | -40C BW | 27C BW | 125C BW |
|--------|-----------|----------|-----------|---------|--------|---------|
| tt | 0.86% | 0.87% | 0.94% | 18.2 kHz | 15.8 kHz | 12.6 kHz |
| ss | 0.93% | 0.93% | 0.98% | 18.2 kHz | 15.1 kHz | 12.6 kHz |
| ff | 0.82% | 0.84% | 0.90% | 19.1 kHz | 15.8 kHz | 13.2 kHz |
| sf | 1.13% | 1.10% | 1.12% | 19.1 kHz | 15.8 kHz | 13.2 kHz |
| fs | 0.74% | 0.77% | 0.84% | 18.2 kHz | 15.1 kHz | 12.6 kHz |

- **Worst gain error**: 1.13% (SF, -40C) — within 2% PVT limit
- **Worst BW**: 12.6 kHz (tt/ss/fs, 125C) — above 10 kHz target
- **All 15 conditions PASS**

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
