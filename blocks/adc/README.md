# 12-bit SAR ADC — SKY130 Bio-AFE

## Status: Phase A Complete (score = 1.0, 6/6 specs met)

## Architecture

**Charge-redistribution SAR ADC** with:
- **Comparator**: StrongARM latch (8 MOSFET + 1 tail), transistor-level in SKY130
- **DAC**: Binary-weighted capacitor array (ideal — no mismatch modeled yet)
- **SAR logic**: Python-modeled successive approximation algorithm
- **Reference**: VREF = VDD = 1.8V (full rail-to-rail)

### Comparator Topology

Standard StrongARM with separated regeneration:
- NMOS tail (W=4µm) clocked by CLK
- NMOS input pair (W=2µm) with drains to internal nodes fn/fp
- NMOS cross-coupled latch (W=1µm) sources connected to fn/fp (disabled during reset)
- PMOS reset switches (W=1µm) pull outputs to VDD when CLK=0
- PMOS cross-coupled latch (W=1µm) for regeneration

Key: NMOS latch sources connect to input pair drains, not VSS. This prevents
static current during reset and ensures clean precharge to VDD.

## Measured vs Target

| Parameter | Measured | Target | Status |
|-----------|----------|--------|--------|
| ENOB | 11.70 bits | > 10 bits | PASS |
| DNL | 0.000 LSB | < 1.0 LSB | PASS * |
| INL | 0.000 LSB | < 2.0 LSB | PASS * |
| Conversion time | 0.031 µs | < 500 µs | PASS |
| Power (1 kSPS) | 0.092 µW | < 10 µW | PASS |
| Input range | 1.798 V | > 1.5 V | PASS |

\* DNL/INL = 0 is a simulation artifact from ideal capacitor DAC. Real silicon
would have capacitor mismatch dominating DNL/INL. See Known Limitations.

### Additional Measurements

| Parameter | Value |
|-----------|-------|
| Comparator offset | 0.125 mV |
| Comparator delay | 0.45–0.55 ns |
| SINAD | 72.2 dB |
| SFDR | 83.4 dB |
| THD | -96.2 dB |
| Noise floor (DC) | 0.64 LSB rms |
| Monotonic | Yes |

## Plots

### Comparator Timing
![conversion_timing](plots/conversion_timing.png)

Clean complementary outputs. outp falls to 0V when vinp > vinn (inverted polarity).
Fast regeneration (~0.5 ns). Reset to VDD during CLK=0.

### DNL/INL
![dnl_inl](plots/dnl_inl.png)

Perfectly flat — expected with ideal DAC. No missing codes. This is an artifact
of the ideal capacitor model. With mismatch, DNL would show a noisy band and
periodic spikes at major bit transitions (every 256, 512, 1024, 2048 codes).

### FFT Spectrum
![fft_spectrum](plots/fft_spectrum.png)

Clean fundamental at 31 Hz. Noise floor at ~-105 dBFS. Small harmonics visible
but well suppressed (THD = -96 dB). ENOB = 11.70 bits, limited by quantization
noise only (no comparator noise in this measurement).

### Transfer Function
![transfer_function](plots/transfer_function.png)

Clean monotonic staircase from code 0 to 4095 over 0–1.8V. Full rail-to-rail
operation with VREF = VDD.

### Noise Histogram
![noise_histogram](plots/noise_histogram.png)

Tight distribution centered at code 2047 (mid-scale). σ = 0.64 LSB from
modeled comparator noise (0.3 mV rms). Spread across 4 codes is reasonable.

### Power vs Sample Rate
![power_vs_sample_rate](plots/power_vs_sample_rate.png)

StrongARM draws no static current — power scales linearly with sample rate.
At 1 kSPS, total power is 0.092 µW (comparator + DAC switching), well below
the 10 µW spec. Even at 10 kSPS, power stays under 1 µW.

## System-Level Context

This ADC receives signals from the filter block, centered at ~0.9V with amplitude
set by the gain chain. A 1 mV ECG at 400× total gain = 400 mV, so the ADC sees
0.7V to 1.1V — well within the 0–1.8V range. At 0.44 mV/LSB, that maps to ~900
codes of dynamic range. ENOB > 10 means quantization noise won't limit the system.

## Design Rationale

1. **StrongARM comparator**: Zero static power, fast regeneration, well-suited for
   SAR ADC at low sample rates. Dynamic power only during comparison.
2. **Full rail-to-rail input**: VREF = VDD = 1.8V maximizes dynamic range and
   simplifies the reference design.
3. **Asynchronous SAR**: At 1 kSPS with 0.5 ns comparator, the conversion takes
   ~6 ns for all 12 bits. Massive timing margin (1 ms available).

## Known Limitations

1. **Ideal DAC**: The capacitor DAC uses ideal (Python-modeled) capacitors with
   no mismatch. In real silicon, capacitor mismatch would cause DNL errors,
   especially at major bit transitions. The DNL = 0 result is NOT realistic.
   Phase B will add capacitor mismatch modeling.

2. **No SPICE-level DAC simulation**: The charge redistribution is modeled
   analytically in Python. This misses charge injection from switches, clock
   feedthrough, finite switch resistance, and capacitor nonlinearity.

3. **Comparator noise model is simplified**: Using a fixed 0.3 mV rms Gaussian
   noise model instead of full SPICE noise simulation. Real noise would include
   flicker noise and would vary with input common-mode.

4. **No reference droop**: The reference voltage is assumed ideal. In practice,
   charge sharing between DAC capacitors and reference source causes VREF droop
   during conversion, degrading linearity.

## Phase B Plan

- [ ] Add capacitor mismatch (Monte Carlo with realistic SKY130 cap σ)
- [ ] PVT corners (ss/ff/sf/fs at -40/27/125°C)
- [ ] Full SPICE DAC simulation with MOSFET switches
- [ ] Reference droop analysis
- [ ] Noise floor from SPICE AC noise simulation

## Experiment History

| Step | Score | Specs | Description |
|------|-------|-------|-------------|
| 0 | 0.90 | 5/6 | Initial baseline — wrong topology (NMOS latch to VSS), broken timing measurement |
| 1 | 1.00 | 6/6 | Fixed StrongARM topology (NMOS latch to fn/fp), fixed wrdata parser and delay measurement |
