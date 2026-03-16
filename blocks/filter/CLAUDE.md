# Bandpass Filter Agent

Autonomous analog IC designer working on the bandpass filter for a biomedical AFE.

Follow the experiment loop defined in `../../CLAUDE.md`.

## Setup

Read these files before starting:
1. `program.md` — evaluation criteria and testbench requirements
2. `specs.json` — target specifications (the only constraints)
3. `../../interfaces.md` — interface contracts
4. `../../master_spec.json` — system-level context

## Freedom

You can modify ANY file except `specs.json`. You choose:
- The topology (Gm-C, active-RC with pseudo-resistors, switched-capacitor, biquad, Sallen-Key, etc.)
- Filter order and type (Butterworth, Chebyshev, Bessel)
- How to implement the 0.5 Hz high-pass (pseudo-resistors, very low Gm, SC, AC-coupled with feedback)
- Optimization method and Python packages

## Quality Requirements

### Anti-Benchmaxxing
1. The 0.5 Hz corner must actually be measured with a slow enough simulation — use transient or very low AC start frequency (0.01 Hz)
2. Verify with a step response that DC is actually rejected, not just attenuated by 3 dB
3. If using pseudo-resistors, check that the corner frequency doesn't shift >5x across PVT — this is the known weakness
4. Test with a realistic ECG waveform, not just sinusoids

### Sanity Checks
- A 2nd-order filter gives 40 dB/decade rolloff — at 250 Hz (1.7x the 150 Hz corner), expect ~10-15 dB attenuation, not 40 dB. If you need >20 dB at 250 Hz you may need higher order.
- The 0.5 Hz high-pass with a pseudo-resistor and ~10 pF cap gives R ~ 1/(2π × 0.5 × 10e-12) ~ 30 GΩ — that's feasible with subthreshold MOSFETs
- Filter power should be very low (< 10 µW) — the signal bandwidth is only 150 Hz

## Tools

- ngspice, Python (numpy, scipy, matplotlib), SKY130 PDK, web search
