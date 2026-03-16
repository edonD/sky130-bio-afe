# Programmable Gain Amplifier

## Purpose

Provide digitally-selectable gain from 1x to 128x in binary steps (1, 2, 4, 8, 16, 32, 64, 128). Combined with the InAmp's fixed ~50x, the total system gain ranges from 50x to 6400x — mapping µV biosignals to the ADC's 0-1.8V input range.

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
| `gain_settings` | >= 7 | 15 | Number of discrete gain steps |
| `gain_error_pct` | < 1% | 20 | Worst-case gain error across all settings |
| `bandwidth_hz` | > 10 kHz | 15 | -3 dB BW at maximum gain (128x) |
| `output_noise_uvrms` | < 50 µVrms | 15 | Output noise at gain=1, 0.5-150 Hz |
| `thd_pct` | < 0.1% | 15 | THD at 10 Hz, 1 Vpp output |
| `power_uw` | < 10 µW | 10 | Total power |
| `settling_time_us` | < 100 µs | 10 | Settling after gain change |

## Testbenches

### TB1: Gain Accuracy at All Settings
- Set each gain (1, 2, 4, 8, 16, 32, 64, 128). Apply 10 mV input at 10 Hz. Measure output.
- **Pass:** Gain error < 1% at every setting.
- **Plot:** `plots/gain_accuracy.png` (ideal vs measured at each step)

### TB2: Frequency Response
- AC sweep at gain=1 and gain=128.
- **Pass:** BW > 10 kHz at gain=128.
- **Plot:** `plots/ac_response.png` (overlay all gain settings)

### TB3: Noise
- Noise analysis at gain=1, integrate 0.5–150 Hz.
- **Plot:** `plots/noise_spectrum.png`

### TB4: Linearity (THD)
- 10 Hz sine, 1 Vpp output. FFT of transient.
- **Pass:** THD < 0.1%.
- **Plot:** `plots/thd_analysis.png`

### TB5: Gain Switching Transient
- Switch gain from 1x to 128x mid-simulation.
- **Pass:** Settles within 0.1% in < 100 µs.
- **Plot:** `plots/gain_switching.png`

### TB6: PVT + Monte Carlo
- TB1 across 5 corners × 3 temps. Gain error < 2% at all corners (relaxed).
- 200 MC samples if available.
- **Plots:** `plots/pvt_gain.png`, `plots/monte_carlo.png`

## How to Evaluate Honestly

- **Test ALL 8 gain settings**, not just one. A PGA that works at gain=1 but fails at gain=128 is broken.
- **THD requires a proper FFT** of a transient simulation, not AC analysis.
- **At gain=128 with 10 kHz BW**, the opamp needs GBW > 1.28 MHz. If BW is failing, the opamp is too slow.
- **Input signals are centered at 0.9V** (from InAmp output), not ground-referenced. Test with realistic bias.
- **If gain error > 5%**, the feedback network or topology is probably wrong, not just a sizing issue.

## Design Freedom

Choose: resistive feedback, capacitive feedback, T-network, R-2R, current steering, any opamp topology. Any optimization method.

## README.md — Your Final Deliverable

Must contain: status, spec table, all plots with analysis, circuit description, rationale, tried/rejected, limitations, experiment history.

## The Experiment Loop

LOOP FOREVER:

1. **Think.** Which gain settings fail? Which spec is the bottleneck?
2. **Modify.** Change `design.cir`, `parameters.csv`, or `evaluate.py`.
3. **Commit.** `git add -A && git commit -m 'pga: <what you changed>'`
4. **Run.** `python evaluate.py > run.log 2>&1`
5. **Read results.** `grep "score\|PASS\|FAIL\|Error" run.log | head -20`
6. **Study the plots.** See "Plot Analysis" below. Mandatory before keep/discard.
7. **Log.** Append to `results.tsv`.
8. **Keep or discard.**
   - Score improved AND all 8 gain settings look correct in the plots → **keep**. Update README. Push.
   - Score improved BUT some gain settings show clipping or oscillation → **investigate**.
   - Score equal or worse → `git reset --hard HEAD~1`.
9. **Repeat.** Never stop.

Phase B after score=1.0: PVT (TB6), all gain settings across corners, settling transient, THD analysis. Keep looping.

## Logging

`results.tsv` — tab-separated, NOT committed:

```
step	commit	score	specs_met	description
0	a1b2c3d	0.30	2/7	resistive feedback PGA — gain error 8% at gain=128
1	b2c3d4e	0.60	4/7	switched to R-2R ladder — error < 1% at all gains
2	c3d4e5f	0.85	6/7	bandwidth fails at gain=128 (only 3kHz)
3	d4e5f6g	1.00	7/7	increased opamp bias — BW 15kHz at gain=128
```

## Plot Analysis

**`plots/gain_accuracy.png`** — Bar chart of ideal vs measured gain at all 8 settings. Each bar pair should match within 1%. If gain=128 is off by 10% but gain=1 is perfect, the feedback network has a systematic error at high gains. If ALL gains are off by the same %, it's a reference or opamp gain error.

**`plots/ac_response.png`** — Overlay of all 8 gain settings on one Bode plot. Higher gain curves should be higher on the magnitude axis but roll off at lower frequencies (GBW is constant, so BW = GBW/gain). If gain=128 rolls off at 3 kHz but you need 10 kHz, the opamp needs more GBW. If any gain setting shows peaking (> 3 dB bump before rolloff), there's a stability issue.

**`plots/gain_switching.png`** — Transient showing the moment gain switches from 1x to 128x. There should be a brief glitch followed by clean settling. If it oscillates, the compensation is wrong. If it takes > 100 µs, the opamp slew rate is too low. The settled value should match the expected gain.

**`plots/thd_analysis.png`** — FFT of a 10 Hz sine at 1 Vpp output. The fundamental should dominate. Harmonics (2nd, 3rd) should be > 60 dB below fundamental for < 0.1% THD. If THD is high, the opamp is clipping or operating in a nonlinear region.

**System-level check:** "At gain=128, the PGA output with a 50 mV input from InAmp = 6.4V. Wait — that exceeds the 1.8V supply! The signal chain gain partitioning must ensure the PGA output stays within 0.2–1.6V. With InAmp=50x on a 1 mV ECG = 50 mV at PGA input, PGA=8x gives 400 mV. That's fine. But PGA=128x gives 6.4V — only valid for µV-level EEG signals." Document this in README.
