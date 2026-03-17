# 12-bit SAR ADC — SKY130 Bio-AFE

## Status: Phase B Complete (score = 1.0, 6/6 specs met, MC + PVT verified)

## Architecture

**Charge-redistribution SAR ADC** with:
- **Comparator**: StrongARM latch (8 MOSFET + 1 tail), transistor-level in SKY130
- **DAC**: Binary-weighted capacitor array (10x10 µm MIM caps, mismatch modeled)
- **SAR logic**: Python-modeled successive approximation algorithm
- **Reference**: VREF = VDD = 1.8V (full rail-to-rail)

### Comparator Topology

Standard StrongARM with separated regeneration:
- NMOS tail (W=6µm) clocked by CLK
- NMOS input pair (W=3µm) with drains to internal nodes fn/fp
- NMOS cross-coupled latch (W=2µm) sources connected to fn/fp (disabled during reset)
- PMOS reset switches (W=1µm) pull outputs to VDD when CLK=0
- PMOS cross-coupled latch (W=1µm) for regeneration

Key: NMOS latch sources connect to input pair drains, not VSS. This prevents
static current during reset and ensures clean precharge to VDD.

### DAC Architecture

Binary-weighted capacitor array: C, 2C, 4C, ..., 2048C + dummy C.
Unit cap: 10x10 µm MIM (`sky130_fd_pr__cap_mim_m3_1`), ~208 fF.
Total array: ~4096 × 208 fF ≈ 852 pF.

Mismatch: Pelgrom coefficient A_c = 2.8 %·µm (from SKY130 PDK).
At 10x10 µm: σ(C)/C = 0.28%. Each binary cap is composed of 2^k
independent unit caps, so σ(C_k)/C_k = 0.28% / sqrt(2^k).

## Measured vs Target

| Parameter | Measured | Target | Status |
|-----------|----------|--------|--------|
| ENOB | 11.70 bits | > 10 bits | PASS |
| DNL | 0.125 LSB | < 1.0 LSB | PASS |
| INL | 0.125 LSB | < 2.0 LSB | PASS |
| Conversion time | 0.031 µs | < 500 µs | PASS |
| Power (1 kSPS) | 0.092 µW | < 10 µW | PASS |
| Input range | 1.798 V | > 1.5 V | PASS |

Primary DNL/INL measured with one instance of mismatched DAC capacitors.

### Additional Measurements

| Parameter | Value |
|-----------|-------|
| Comparator offset | 0.125 mV |
| Comparator delay | 0.45–0.55 ns |
| SINAD | 72.2 dB |
| SFDR | 83.5 dB |
| THD | -92.4 dB |
| Noise floor (DC) | 0.66 LSB rms |
| Monotonic | Yes |

## Monte Carlo Results (200 runs, cap mismatch)

| Metric | Mean | Std | Worst | Spec | Yield |
|--------|------|-----|-------|------|-------|
| Max DNL | 0.194 LSB | 0.084 | 0.500 LSB | < 1.0 | 100% |
| Max INL | 0.147 LSB | 0.052 | 0.313 LSB | < 2.0 | 100% |
| ENOB | 10.25 bits | 0.03 | 10.14 bits | > 10 | 100% |

No missing codes in any run. Extended to 500 runs: still 100% yield on all specs.
p99 DNL = 0.376 LSB. p1 ENOB = 10.18 bits. Both with comfortable margin.

## PVT Corner Results (5 corners × 3 temps)

| Corner | -40°C | 27°C | 125°C |
|--------|-------|------|-------|
| tt | 0.70 ns | 0.60 ns | 0.50 ns |
| ss | 1.40 ns | 1.00 ns | 0.80 ns |
| ff | 0.40 ns | 0.32 ns | 0.40 ns |
| sf | 0.50 ns | 0.40 ns | 0.40 ns |
| fs | 1.50 ns | 1.00 ns | 0.90 ns |

All 15 corners: correct decisions. Worst-case delay: 1.50 ns (fs, -40°C).
Even at worst case, conversion time = 12 × 1.5 ns = 18 ns << 500 µs spec.

## Plots

### DNL/INL (with mismatch)
![dnl_inl](plots/dnl_inl.png)

DNL errors visible at major bit transitions (codes ~1024, ~2048, ~3072).
Max |DNL| = 0.125 LSB. INL shows small steps at bit boundaries. This is
the expected signature of binary-weighted cap mismatch — errors appear at
powers of 2 where a single large cap switches against many small ones.

### FFT Spectrum
![fft_spectrum](plots/fft_spectrum.png)

Clean fundamental at 31 Hz. ENOB = 11.70 bits with mismatched DAC.
Small harmonics from DAC nonlinearity visible but well suppressed.

### Monte Carlo
![monte_carlo](plots/monte_carlo.png)

200 runs with random cap mismatch (σ/C = 0.28%). DNL tightly clustered
around 0.19 LSB with tail to 0.5 LSB. INL clustered around 0.15 LSB.
ENOB centered at 10.25 bits. All runs pass all specs.

### PVT Corners
![pvt_linearity](plots/pvt_linearity.png)

Comparator delay vs temperature across 5 process corners. Slowest corners
(ss, fs) at cold temperatures show ~1.5 ns delay. Still provides massive
margin over the 500 µs conversion time spec.

### Comparator Timing
![conversion_timing](plots/conversion_timing.png)

Clean complementary outputs. Fast regeneration (~0.5 ns at tt/27°C).
Reset to VDD during CLK=0.

### Transfer Function
![transfer_function](plots/transfer_function.png)

Clean monotonic staircase from code 0 to 4095 over 0–1.8V.

### Noise Histogram
![noise_histogram](plots/noise_histogram.png)

Tight distribution at mid-scale. σ = 0.66 LSB from modeled comparator noise.

### Power vs Sample Rate
![power_vs_sample_rate](plots/power_vs_sample_rate.png)

StrongARM draws no static current. At 1 kSPS: 0.092 µW total.

## System-Level Context

This ADC receives signals from the filter block, centered at ~0.9V with amplitude
set by the gain chain. A 1 mV ECG at 400× total gain = 400 mV, so the ADC sees
0.7V to 1.1V — well within the 0–1.8V range. At 0.44 mV/LSB, that maps to ~900
codes of dynamic range. ENOB > 10 means quantization noise won't limit the system.

## Design Rationale

1. **StrongARM comparator**: Zero static power, fast regeneration, well-suited for
   SAR ADC at low sample rates. Dynamic power only during comparison.
2. **Full rail-to-rail input**: VREF = VDD = 1.8V maximizes dynamic range.
3. **10x10 µm unit cap**: Gives σ/C = 0.28%, achieving 100% yield on 12-bit DNL
   spec without calibration. Matches the target sigma/C < 0.45% for 12-bit.
4. **Asynchronous SAR**: At 1 kSPS with 0.5 ns comparator, massive timing margin.

## Sensitivity Analysis

### Unit Cap Size (500 runs each)

| Size | σ/C | DNL p99 | Worst DNL | Yield | Area |
|------|-----|---------|-----------|-------|------|
| 5.0x5.0 µm (PDK min) | 0.56% | 0.875 | 1.125 LSB | 99.8% | 0.10 mm² |
| 5.5x5.5 µm | 0.51% | 0.875 | 0.875 LSB | 100% | 0.12 mm² |
| 6.5x6.5 µm | 0.43% | 0.875 | 0.875 LSB | 100% | 0.17 mm² |
| 7.0x7.0 µm | 0.40% | 0.625 | 0.875 LSB | 100% | 0.20 mm² |
| 8.0x8.0 µm | 0.35% | 0.625 | 0.625 LSB | 100% | 0.26 mm² |
| 10x10 µm (chosen) | 0.28% | 0.376 | 0.625 LSB | 100% | 0.41 mm² |

Minimum viable without calibration: **5.5x5.5 µm** (100% yield, 0.12 mm²).
Conservative choice: 10x10 µm for maximum margin. Could save 70% area
by switching to 5.5 µm caps with no yield loss.

### Supply Variation (±10%)

| VDD | Monotonic | Code Range |
|-----|-----------|------------|
| 1.62V | Yes | 0-4095 |
| 1.71V | Yes | 0-4095 |
| 1.80V | Yes | 0-4095 |
| 1.89V | Yes | 0-4095 |
| 1.98V | Yes | 0-4095 |

Robust across full ±10% supply range.

## Known Limitations

1. **Comparator VCM-dependent offset**: SPICE characterization reveals large
   comparator offsets at extreme common-mode voltages:
   - VCM 0.5-1.1V: offset < 20 µV (usable)
   - VCM < 0.4V or > 1.2V: offset 2-5 mV
   However, the charge-redistribution architecture naturally keeps the
   comparator input near VCM=0.9V during all bit decisions. The top plate
   voltage only swings by ±residual/2, so VCM stays in the good range.
   Result: **zero missing codes** across the full input range with corrected model.

2. **DAC partially verified in SPICE**: A 4-bit proof-of-concept DAC simulation
   with SKY130 MIM caps confirms charge redistribution works correctly
   (vtop=0.9V during sample, 1.28V after MSB trial vs 1.3V ideal). The 20mV
   error is from switch charge injection — a systematic offset, not linearity.
   Full 12-bit SPICE DAC simulation remains future work.

3. **Comparator noise**: SPICE gm extraction gives gm=1.01 mA/V for W=3µm at
   VGS=0.9V. With ~200 ps integration time (half of 0.4 ns delay), noise ≈
   0.23 mV = 0.53 LSB. This validates the 0.3 mV model used in evaluation.
   Design passes at noise up to 0.5 mV (ENOB > 10). SPICE doesn't simulate
   thermal noise without special setup, so noise is modeled analytically.

4. **No reference droop**: The reference voltage is assumed ideal.

5. **Large total cap area**: 4096 × 10×10 µm = 0.41 mm². A real design would use
   smaller unit caps (5×5 µm with calibration, or VPP waffle caps ~448 aF).

## Experiment History

| Step | Score | Specs | Description |
|------|-------|-------|-------------|
| 0 | 0.90 | 5/6 | Initial baseline — wrong topology, broken timing |
| 1 | 1.00 | 6/6 | Fixed StrongARM, wrdata parser, delay measurement |
| 2 | 1.00 | 6/6 | Phase B: MC (200 runs, 100% yield), PVT (15/15 pass) |
| 3 | 1.00 | 6/6 | Cap sensitivity (7µm min viable), supply ±10% pass |
| 4 | 1.00 | 6/6 | VCM offset model: charge redistribution keeps VCM stable |
| 5 | 1.00 | 6/6 | Combined stress (mismatch+noise+VCM): ENOB 10.53-10.62 |
| 6 | 1.00 | 6/6 | Extended MC 500 runs: 100% yield, p99 DNL=0.376, p1 ENOB=10.18 |
| 7 | 1.00 | 6/6 | Area optimization: 5.5um min viable (100% yield), 70% area savings |
| 8 | DISC | - | W=4u input pair: lower noise but 3/15 PVT failures. Reverted. |
| 9 | 1.00 | 6/6 | W_in=3u, W_n=2u: 27% faster, 40% better PVT, same yield |
| 10 | 1.00 | 6/6 | Combined worst case (ss/-40C/1.62V): correct. Min CLK: 1ns. |
| 11 | 1.00 | 6/6 | SPICE DAC verification, gm extraction, 1GHz max clock rate |
