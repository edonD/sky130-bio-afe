# Bandpass Filter

## Purpose

Bandpass filter with passband 0.5 Hz to 150 Hz. The high-pass removes electrode DC offset and motion artifacts. The low-pass anti-aliases for the ADC. The 0.5 Hz high-pass is the main design challenge — it requires either GΩ pseudo-resistors or very low transconductance.

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

**Critical rule:** Never game the process by editing PDK models or fabricating results.

## Evaluated Parameters

| Parameter | Target | Weight | What It Means |
|-----------|--------|--------|---------------|
| `f_low_hz` | < 1.0 Hz | 20 | Lower -3 dB cutoff (high-pass) |
| `f_high_hz` | 130–170 Hz | 20 | Upper -3 dB cutoff (low-pass) |
| `passband_ripple_db` | < 1 dB | 15 | Max gain variation in 0.5–150 Hz |
| `stopband_atten_250hz_db` | > 20 dB | 15 | Attenuation at Nyquist |
| `output_noise_uvrms` | < 100 µVrms | 15 | Output noise in passband |
| `power_uw` | < 10 µW | 15 | Total power |

## Testbenches

### TB1: Frequency Response
- AC sweep 0.01 Hz to 100 kHz. Extract f_low, f_high, passband ripple.
- **Pass:** f_low < 1.0 Hz, f_high in 130–170 Hz, ripple < 1 dB.
- **Plot:** `plots/frequency_response.png` (Bode plot, log frequency axis)

### TB2: Stopband Attenuation
- Measure gain at 250 Hz, 500 Hz, 1 kHz.
- **Pass:** > 20 dB at 250 Hz.
- Annotate attenuation markers on the Bode plot.

### TB3: Step Response (DC Rejection)
- Apply 300 mV DC step (simulating electrode placement). Monitor output.
- **Pass:** Output returns within 10 mV of baseline within 5 seconds.
- **Plot:** `plots/step_response.png` — this proves the high-pass actually rejects DC.

### TB4: ECG Transient
- Synthetic ECG + 60 Hz interference at input.
- **Pass:** ECG R-peak within ±5% of expected amplitude.
- **Plot:** `plots/ecg_filtering.png` (input vs output overlay)

### TB5: Noise
- Noise analysis, integrate in passband.
- **Pass:** < 100 µVrms.
- **Plot:** `plots/noise_spectrum.png`

### TB6: PVT + Monte Carlo
- TB1 across 5 corners × 3 temps. Cutoffs within 2x of nominal at all corners.
- **Important:** If using pseudo-resistors, the high-pass corner WILL shift >5x across PVT. Document this honestly.
- **Plots:** `plots/pvt_frequency_response.png`, `plots/monte_carlo.png`

## How to Evaluate Honestly

- **The 0.5 Hz corner must be verified with a slow simulation** (AC starting at 0.01 Hz, or a transient step response). If the AC sweep starts at 1 Hz, you're not measuring f_low.
- **A 2nd-order filter gives ~12 dB at 250 Hz** (1.7× the 150 Hz corner). If you need > 20 dB, you may need 3rd or 4th order. Be honest about this — don't claim 20 dB from a 2nd-order.
- **Pseudo-resistor PVT variation** is the #1 known weakness. A 30 GΩ resistor at room temp might be 3 GΩ at 125°C (shifting f_low from 0.5 Hz to 5 Hz). Document the actual PVT spread.
- **If the step response doesn't recover to baseline**, the DC is not being rejected — the high-pass isn't working.
- **Passband ripple** in Chebyshev filters trades off with stopband attenuation. If you pick Butterworth, ripple is zero but rolloff is slower.

## Design Freedom

Choose: Gm-C, active-RC with pseudo-resistors, switched-capacitor, biquad, Sallen-Key, state-variable, any filter type (Butterworth, Chebyshev, Bessel). Any optimization method.

## README.md — Your Final Deliverable

Must contain: status, spec table, all plots with analysis, circuit description, rationale, tried/rejected, limitations (especially PVT sensitivity of the high-pass corner), experiment history.

## The Experiment Loop

LOOP FOREVER:

1. **Think.** Is f_low actually < 1 Hz? Does the step response show real DC rejection? What does the Bode plot look like?
2. **Modify.** Change `design.cir`, `parameters.csv`, or `evaluate.py`.
3. **Commit.** `git add -A && git commit -m 'filter: <what you changed>'`
4. **Run.** `python evaluate.py > run.log 2>&1`
5. **Read results.** `grep "score\|PASS\|FAIL\|Error" run.log | head -20`
6. **Study the plots.** See "Plot Analysis" below. Mandatory before keep/discard.
7. **Log.** Append to `results.tsv`.
8. **Keep or discard.**
   - Score improved AND the Bode plot shows clean bandpass AND the step response recovers → **keep**. Update README. Push.
   - Score improved BUT the step response doesn't actually reject DC → **investigate**. The high-pass isn't working.
   - Score equal or worse → `git reset --hard HEAD~1`.
9. **Repeat.** Never stop.

Phase B after score=1.0: PVT (TB6 — especially pseudo-resistor variation), ECG transient (TB4), noise, margin improvement. Keep looping.

## Logging

`results.tsv` — tab-separated, NOT committed:

```
step	commit	score	specs_met	description
0	a1b2c3d	0.30	1/6	Gm-C biquad — f_low = 15 Hz (too high)
1	b2c3d4e	0.45	2/6	added pseudo-resistor HPF — f_low = 0.8 Hz
2	c3d4e5f	0.65	3/6	stopband only 14 dB at 250 Hz — need higher order
3	d4e5f6g	0.80	4/6	added 2nd-order LPF stage — 22 dB at 250 Hz
4	e5f6g7h	1.00	6/6	all pass nominal. PVT: f_low shifts to 5 Hz at 125°C
5	f6g7h8i	1.00	6/6	biased pseudo-R gate — PVT spread < 3x
```

## Plot Analysis

**`plots/frequency_response.png`** — The Bode plot is the most important plot for the filter. It should show a clear bandpass: gain rising from low frequencies (high-pass), flat in the passband (0.5–150 Hz), then rolling off (low-pass). Mark f_low and f_high with vertical lines. If f_low is at 10 Hz instead of 0.5 Hz, the high-pass time constant is 20x too short — increase the pseudo-resistor value or the coupling capacitor. If f_high is at 50 Hz, the low-pass is too aggressive. The AC sweep must start at 0.01 Hz to actually measure the 0.5 Hz corner — if it starts at 1 Hz, you're not seeing f_low.

**`plots/step_response.png`** — This is the acid test for the high-pass. Apply a 300 mV step (simulating electrode placement) and watch the output. It should spike and then decay back to baseline within 1–5 seconds. If it stays at 300 mV × gain, the DC is not being blocked. If it recovers in 0.1 seconds, f_low is too high (around 1.6 Hz, not 0.5 Hz). The recovery time constant ≈ 1/(2π × f_low) — for f_low = 0.5 Hz, that's ~320 ms to reach 37% of initial.

**`plots/ecg_filtering.png`** — Input vs output overlay. The ECG P-QRS-T morphology should be preserved. The P-wave (which has energy down to 0.5 Hz) should be visible — if it's attenuated, f_low is too high. The 60 Hz component (if present in the input) should be visible in the passband (this filter doesn't reject 60 Hz — that's the InAmp's job via CMRR).

**`plots/pvt_frequency_response.png`** — Overlay the Bode plot for all PVT corners. The low-pass corner (f_high) should be relatively stable (set by capacitor ratios). The high-pass corner (f_low) will shift significantly if using pseudo-resistors — document the actual range. If f_low goes from 0.3 Hz to 5 Hz across PVT, that's a 17x variation. Be honest about it.

**System-level check:** "The filter output feeds the ADC. Is the output impedance low enough to drive the ADC sampling capacitor (~5 pF) without droop? At 1 kSPS, the acquisition time is ~500 µs. With Rout = 10 kΩ and C_sample = 5 pF, τ = 50 ns — 10,000× margin. OK." Document in README.
