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

## The Experiment Loop

LOOP FOREVER:

1. **Think.** Is DNL clean across all 4096 codes? Does the FFT show clean ENOB? Are there missing codes?
2. **Modify.** Change `design.cir`, `parameters.csv`, or `evaluate.py`.
3. **Commit.** `git add -A && git commit -m 'adc: <what you changed>'`
4. **Run.** `python evaluate.py > run.log 2>&1`
5. **Read results.** `grep "score\|PASS\|FAIL\|Error" run.log | head -20`
6. **Study the plots.** See "Plot Analysis" below. Mandatory before keep/discard.
7. **Log.** Append to `results.tsv`.
8. **Keep or discard.**
   - Score improved AND DNL/INL plot is clean across ALL codes AND SAR waveform shows proper convergence → **keep**. Update README. Push.
   - Score improved BUT DNL is suspiciously perfect (< 0.001 LSB everywhere) → **investigate**. Mismatch is probably not modeled.
   - Score equal or worse → `git reset --hard HEAD~1`.
9. **Repeat.** Never stop.

Phase B after score=1.0: PVT (TB7), Monte Carlo for cap mismatch, noise floor measurement, ENOB across input range. Keep looping.

## Logging

`results.tsv` — tab-separated, NOT committed:

```
step	commit	score	specs_met	description
0	a1b2c3d	0.00	0/6	initial SAR — ngspice convergence error in comparator
1	b2c3d4e	0.40	2/6	StrongARM latch works — DNL 3.2 LSB (cap sizing wrong)
2	c3d4e5f	0.65	4/6	doubled unit cap to 2fF — DNL 0.8 LSB
3	d4e5f6g	0.85	5/6	ENOB 9.5 (need >10) — comparator offset limiting
4	e5f6g7h	1.00	6/6	added pre-amp stage — ENOB 10.3. All pass.
```

## Plot Analysis

**`plots/dnl_inl.png`** — Two subplots showing DNL and INL vs all 4096 codes. DNL should be a noisy band between -0.5 and +0.5 LSB for a well-matched DAC. If there are periodic spikes (e.g., every 256 codes), it's a major bit transition error — the MSB capacitor is mismatched. If DNL reaches +1.0, you have a missing code at that transition. INL should be a smooth bow, typically < 2 LSB peak-to-peak. If INL is a random walk, the cap matching is poor.

**`plots/fft_spectrum.png`** — Output spectrum from a near-Nyquist sine test. The fundamental should be a clean peak. The noise floor should be flat (no spurs). Harmonics (2nd, 3rd) determine THD. SFDR = distance from fundamental to largest spur. ENOB = (SINAD - 1.76) / 6.02. If there are large spurs at non-harmonic frequencies, the SAR logic or clock is leaking.

**`plots/transfer_function.png`** — Output code vs input voltage, full 0–1.8V sweep. Should be a clean staircase. If there's a discontinuity or flat region, there's a missing code. If the curve saturates before 1.8V, the input range is limited. The staircase should be monotonic — code never decreases as input increases.

**`plots/conversion_timing.png`** — Show the SAR approximation for one conversion: comparator output, DAC voltage, bit decisions. Each bit should cleanly resolve before the next comparison starts. If bits are flipping back-and-forth, the comparator is too slow or the DAC hasn't settled. The total conversion should finish well within 500 µs.

**`plots/noise_histogram.png`** — Histogram of 1000 samples at a fixed DC input. Should be a tight Gaussian centered on the expected code. Width = RMS noise in LSBs. If it's bimodal (two peaks), the input is right at a code transition. If the spread is > 2 LSB, the noise floor is too high.

**System-level check:** "This ADC receives a signal from the filter, centered at ~0.9V with amplitude set by the gain chain. A 1 mV ECG at 400x total gain = 400 mV, so the ADC sees 0.7V to 1.1V — well within the 0–1.8V range. At 0.44 mV/LSB, that's ~900 codes of dynamic range. ENOB > 10 means the quantization noise won't limit the system." Document in README.
