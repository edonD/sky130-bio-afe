# Instrumentation Amplifier

## Purpose

Amplify microvolt-level differential biosignals (ECG/EEG/EMG) while rejecting common-mode interference. This is the most critical block — it sets the noise floor for the entire system. Biosignals arrive as 1 µV to 5 mV differential, riding on 300 mV DC electrode offset and 1-10 mV 50/60 Hz powerline noise.

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

**You CANNOT modify:** `specs.json`, `program.md`, SKY130 PDK model files, `../../interfaces.md`.

**Critical rule:** Never game the process by editing PDK models, fabricating results, or tweaking evaluation to pass artificially.

## Evaluated Parameters

| Parameter | Target | Weight | What It Means |
|-----------|--------|--------|---------------|
| `gain_db` | > 34 dB | 15 | Closed-loop voltage gain (~50 V/V) |
| `input_referred_noise_uvrms` | < 1.5 µVrms | 25 | Total noise in 0.5–150 Hz band |
| `cmrr_60hz_db` | > 100 dB | 20 | Common-mode rejection at powerline frequency |
| `input_offset_uv` | < 50 µV | 15 | Systematic DC offset (referred to input) |
| `bandwidth_hz` | > 10 kHz | 10 | -3 dB bandwidth |
| `power_uw` | < 15 µW | 15 | Total power from 1.8V supply |

## Testbenches

### TB1: DC Gain and Operating Point
- Apply 1 mV differential, V_CM = 0.9V. Measure output, compute gain.
- Verify output stays within 0.2–1.6V (not railed).
- **Plot:** `plots/dc_gain.png`

### TB2: AC Frequency Response
- AC sweep 0.1 Hz to 1 MHz, differential input. Bode plot.
- **Pass:** Flat (±0.5 dB) from 0.5 to 150 Hz, BW > 10 kHz.
- **Plot:** `plots/ac_response.png`

### TB3: Common-Mode Rejection
- Apply 10 mV common-mode, sweep 1 Hz to 1 kHz. Compute CMRR = A_diff/A_cm.
- **Pass:** CMRR > 100 dB at 60 Hz.
- **Plot:** `plots/cmrr_vs_freq.png`

### TB4: Input-Referred Noise
- Noise analysis 0.1 Hz to 1 kHz. Integrate 0.5–150 Hz for total RMS.
- **Pass:** < 1.5 µVrms input-referred.
- **Plot:** `plots/noise_spectral_density.png` (V/√Hz vs frequency — should show 1/f corner and white noise floor)

### TB5: Input Offset
- Zero differential input. Measure output, compute input-referred offset.
- **Plot:** `plots/offset_measurement.png`

### TB6: Electrode Offset Tolerance
- Apply ±300 mV DC common-mode offset + 1 mV differential signal.
- **Pass:** Gain within ±1 dB of nominal. Output not saturated.
- **Plot:** `plots/electrode_offset_tolerance.png`

### TB7: Realistic ECG Transient
- Synthetic ECG (1 mV R-peak, 72 BPM) + 2 mV 60 Hz interference + 300 mV DC offset.
- **Pass:** ECG morphology preserved at output, 60 Hz rejected.
- **Plot:** `plots/ecg_transient.png`

### TB8: PVT Corner Analysis
- TB1 + TB4 across 5 corners × 3 temps = 15 minimum.
- **Pass:** All specs met at all corners.
- **Plot:** `plots/pvt_summary.png`

### TB9: Monte Carlo
- 200 samples if mismatch models available. Report offset and gain spread.
- **Plot:** `plots/monte_carlo.png`

## How to Evaluate Honestly

- **Noise:** Must be integrated over 0.5–150 Hz, not spot noise at one frequency. If you get < 0.1 µVrms, check the simulation — that's world-class for µA bias.
- **CMRR:** > 80 dB needs chopping or very careful matching. > 120 dB is exceptional — verify it's real.
- **Electrode offset:** This is where designs fail in the real world. Test with ±300 mV, not 0V.
- **If the output is railed (stuck at VDD or VSS):** The common-mode input range doesn't cover the electrode offset. Rethink the input stage.
- **If noise is too high:** Increase bias current (noise ∝ 1/√I) or increase input transistor W/L.
- **If CMRR is too low:** Check tail current source impedance, consider chopping, verify symmetry.

## Design Freedom

Choose everything:
- **Topology:** 3-opamp, current-feedback, capacitively-coupled, direct differential pair, etc.
- **Techniques:** Chopping, auto-zeroing, correlated double sampling — all fair game.
- **Optimization:** Any algorithm. `pip install` anything.

## README.md — Your Final Deliverable

The only thing I check. Must contain: status banner, spec table, all plots with analysis, circuit description, design rationale, what was tried/rejected, known limitations, experiment history.

## The Experiment Loop

LOOP FOREVER:

1. **Think.** Which specs fail? What do the plots show? What's the weakest point?
2. **Modify.** Change `design.cir`, `parameters.csv`, or `evaluate.py`.
3. **Commit.** `git add -A && git commit -m 'inamp: <what you changed>'`
4. **Run.** `python evaluate.py > run.log 2>&1`
5. **Read results.** `grep "score\|PASS\|FAIL\|Error" run.log | head -20`
6. **Study the plots.** See "Plot Analysis" below. Mandatory before keep/discard.
7. **Log.** Append to `results.tsv`.
8. **Keep or discard.**
   - Score improved AND plots are physically correct → **keep**. Update README.md. Push.
   - Score improved BUT waveforms look wrong (output railed, noise unrealistically low, CMRR too good to be true) → **investigate**.
   - Score equal or worse → `git reset --hard HEAD~1`.
9. **Repeat.** Never stop.

Phase B after score=1.0: PVT (TB8), Monte Carlo (TB9), realistic ECG transient (TB7), margin improvement. Keep looping.

## Logging

`results.tsv` — tab-separated, NOT committed:

```
step	commit	score	specs_met	description
0	a1b2c3d	0.25	1/6	3-opamp topology — output railed with 300mV offset
1	b2c3d4e	0.40	2/6	switched to capacitively-coupled — gain OK but CMRR only 60dB
2	c3d4e5f	0.75	4/6	added chopping at 10kHz — CMRR >100dB now
3	d4e5f6g	0.85	5/6	increased input pair W/L — noise down to 1.8 µVrms (still >1.5)
4	e5f6g7h	1.00	6/6	bias current 2µA → 4µA — noise 1.2 µVrms. All pass.
```

## Plot Analysis

After EVERY run, study these critically:

**`plots/noise_spectral_density.png`** — Should show 1/f noise rising at low frequencies and a white noise floor at higher frequencies. The 1/f corner should be somewhere between 10 Hz and 10 kHz depending on the topology. If the spectrum is flat down to 0.1 Hz, either chopping is working perfectly (good) or the noise simulation is wrong (bad — check). If the integrated noise is < 0.1 µVrms, that's world-class — verify by checking gm and bias current: noise ≈ √(4kT × 2/(gm) × BW). Does it add up?

**`plots/cmrr_vs_freq.png`** — CMRR should be high (> 100 dB) at low frequencies and roll off with frequency. If CMRR is > 120 dB everywhere, verify — that requires near-perfect matching or chopping. If CMRR drops below 80 dB at 60 Hz, the powerline interference won't be rejected enough.

**`plots/ecg_transient.png`** — The output should show a clean, amplified ECG waveform. The R-peak should be clearly visible and properly scaled (1 mV × gain). The 60 Hz interference should be visibly attenuated. If the output is clipped (flat at VDD or VSS), the common-mode input range doesn't accommodate the electrode offset. If the ECG shape is distorted, the bandwidth is too narrow.

**`plots/electrode_offset_tolerance.png`** — Apply ±300 mV DC offset on the inputs. The output must NOT saturate. If it does, the design fails in the real world regardless of what the gain spec says at 0V offset.

**System-level check:** "The InAmp output feeds the PGA. Is the output centered near 0.9V? Is the swing within 0.2–1.6V so the PGA doesn't clip? With a 1 mV ECG × 50 gain = 50 mV swing around 0.9V — that's 0.85V to 0.95V. Comfortable." Report this in README.
