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

**You CANNOT modify files in other blocks.** The bandgap, pga, filter, and adc are already designed and merged. Do not touch them.

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

## Knowledge From Previous Design Attempt

A previous agent spent 16 iterations on this block. Use this knowledge to go faster.

### Use a Capacitively-Coupled IA (CCIA)

This is the right topology for biomedical:
- Gain = Cin/Cfb (e.g., 51pF/1pF ≈ 34 dB). Process-independent.
- Capacitive coupling naturally rejects ±300 mV electrode DC offset.
- Fully-differential folded-cascode OTA gives high gain and bandwidth.
- PMOS LVT input pair gives ~2× lower 1/f noise than standard PMOS.
- Large Cin (50-62 pF) is critical: it dilutes the input pair Cgs parasitic, reducing noise gain from ~2.7× to ~1.4×.

### CMRR Requires Chopping — This Is Non-Negotiable

**With perfect matching, simulation gives CMRR = 258 dB. This is meaningless.** In real silicon with 0.1% capacitor mismatch, CMRR drops to ~77 dB — failing the >100 dB spec.

The solution is system-level chopping at ~10 kHz. This moves the mismatch-induced CM error from 60 Hz to f_chop ± 60 Hz (outside the signal band). The previous agent achieved 113 dB CMRR with this approach.

**Your evaluate.py MUST test CMRR with deliberate 0.1% Cin mismatch.** This is the only honest measurement. Never report CMRR from an ideal-matching AC analysis.

### Skip These Dead Ends

- Simple 5T OTA — not enough open-loop gain
- Single-ended output — CMRR limited to ~34 dB
- Small Cin (< 30 pF) — parasitic Cgs dominates, noise explodes
- NMOS loads without noise mitigation — NMOS 1/f noise ruins everything
- Positive feedback (Cfb on wrong OTA input)

## Testbenches

### TB1: DC Gain and Operating Point
- Apply 1 mV differential, V_CM = 0.9V. Measure output, compute gain.
- Verify output stays within 0.2–1.6V (not railed).
- **Plot:** `plots/dc_gain.png`

### TB2: AC Frequency Response
- AC sweep 0.1 Hz to 1 MHz, differential input. Bode plot.
- **Pass:** Flat (±0.5 dB) from 0.5 to 150 Hz, BW > 10 kHz.
- **Plot:** `plots/ac_response.png`

### TB3: Common-Mode Rejection (WITH MISMATCH)
- **DO NOT use AC analysis with ideal matching.** That gives fake 200+ dB results.
- Deliberately mismatch Cin+ by 0.1% from Cin-.
- Apply 10 mV common-mode at 60 Hz via transient simulation.
- Measure differential output at 60 Hz via FFT.
- **Pass:** CMRR > 100 dB with 0.1% Cin mismatch and chopping enabled.
- **Plot:** `plots/cmrr_vs_freq.png`

### TB4: Input-Referred Noise
- Noise analysis 0.1 Hz to 1 kHz. Integrate 0.5–150 Hz for total RMS.
- **Pass:** < 1.5 µVrms input-referred.
- **Plot:** `plots/noise_spectral_density.png`

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

### TB9: Monte Carlo / Mismatch Sweep
- Sweep Cin mismatch from 0.01% to 1% and plot CMRR degradation.
- Show that chopping keeps CMRR > 100 dB across the mismatch range.
- **Plot:** `plots/monte_carlo.png`

## How to Evaluate Honestly

- **CMRR is the spec most likely to be faked.** Always test with 0.1% Cin mismatch. If your CMRR is > 150 dB, you're not testing with mismatch.
- **Noise:** Must be integrated over 0.5–150 Hz. If you get < 0.1 µVrms at µA bias, the simulation is wrong.
- **Electrode offset:** Test with ±300 mV, not 0V. This is where designs fail in the real world.
- **If the output is railed:** The common-mode input range doesn't cover the electrode offset.
- **If noise is too high:** Increase bias current or input transistor W/L.
- **If CMRR is too low even with chopping:** Increase f_chop or reduce mismatch with larger capacitors.

## Design Freedom

Choose everything:
- **Topology:** CCIA recommended, but you can try others.
- **Chopping:** Required for honest CMRR. Transmission gates, bootstrapped switches, or behavioral (document which).
- **OTA:** Folded-cascode, telescopic, two-stage — your choice.
- **Optimization:** Any algorithm. `pip install` anything.

Research freely: search for "CCIA biomedical SKY130", "chopper instrumentation amplifier", ISSCC papers on bio-AFE.

## README.md — Your Final Deliverable

The only thing I check. Must contain: status banner, spec table, ALL 9 testbench plots with analysis, circuit description, design rationale, known limitations, experiment history.

## The Experiment Loop

LOOP FOREVER:

1. **Think.** Which specs fail? What do the plots show? What's the weakest point?
2. **Modify.** Change `design.cir`, `parameters.csv`, or `evaluate.py`. ONLY files in this block.
3. **Commit.** `git add -A && git commit -m 'inamp: <what you changed>'`
4. **Run.** `python evaluate.py > run.log 2>&1`
5. **Read results.** `grep "score\|PASS\|FAIL\|Error" run.log | head -20`
6. **Study the plots.** See "Plot Analysis" below. Mandatory before keep/discard.
7. **Log.** Append to `results.tsv`.
8. **Keep or discard.**
   - Score improved AND plots are physically correct → **keep**. Update README.md. Push.
   - Score improved BUT CMRR > 150 dB → **that's fake**, investigate.
   - Score equal or worse → `git reset --hard HEAD~1`.
9. **Repeat.** Never stop. Never touch other blocks. Keep going until ALL specs pass honestly with ALL testbenches complete.

## Logging

`results.tsv` — tab-separated, NOT committed:

```
step	commit	score	specs_met	description
0	a1b2c3d	0.40	2/6	CCIA baseline — gain OK but CMRR 77dB with mismatch
1	b2c3d4e	0.75	4/6	added chopping — CMRR 113dB with mismatch
2	c3d4e5f	0.85	5/6	PMOS LVT + Cin=62pF — noise 1.8 µVrms (still >1.5)
3	d4e5f6g	1.00	6/6	bias 5µA — noise 0.96 µVrms. All pass honestly.
```

## Plot Analysis

**`plots/cmrr_vs_freq.png`** — THE critical plot. Must show CMRR measured with 0.1% Cin mismatch. With chopping it should be > 100 dB at 60 Hz. If you see > 200 dB, the mismatch is not in the simulation.

**`plots/noise_spectral_density.png`** — Should show 1/f noise rising at low frequencies and white noise floor at higher frequencies. Verify: noise ≈ √(4kT × 2/(gm) × BW). Does it add up?

**`plots/ecg_transient.png`** — Clean amplified ECG with 60 Hz rejected. If clipped, the CM range is too narrow.

**`plots/electrode_offset_tolerance.png`** — Output must NOT saturate with ±300 mV DC offset.

**System-level check:** "Output centered near 0.9V? Swing within 0.2–1.6V for the PGA? With 1 mV ECG × 50 gain = 50 mV swing around 0.9V — comfortable." Report in README.
