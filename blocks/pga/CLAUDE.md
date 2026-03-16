# Programmable Gain Amplifier Agent

Autonomous analog IC designer working on the PGA for a biomedical AFE.

Follow the experiment loop defined in `../../CLAUDE.md`.

## Setup

Read these files before starting:
1. `program.md` — evaluation criteria and testbench requirements
2. `specs.json` — target specifications (the only constraints)
3. `../../interfaces.md` — interface contracts
4. `../../master_spec.json` — system-level context

## Freedom

You can modify ANY file except `specs.json`. You choose:
- The topology (resistive feedback, capacitive feedback, T-network, R-2R, etc.)
- The opamp architecture (single-stage, two-stage, folded cascode, etc.)
- How gain selection is implemented (switched resistors, switched caps, current steering)
- The optimization method and any Python packages

## Quality Requirements

### Anti-Benchmaxxing
1. Gain accuracy must be tested at ALL gain settings, not just one
2. THD measurement requires a proper FFT of a transient simulation, not just AC analysis
3. Verify that gain switching glitches settle — don't just measure static gain
4. Check that the design works with realistic input signals (centered at 0.9V, not ground-referenced)

### Sanity Checks
- Binary gain steps (1/2/4/.../128) are easiest with R-2R or binary-weighted feedback — if gain error > 5%, the topology may be wrong
- A 128x amplifier with 10 kHz bandwidth needs GBW > 1.28 MHz — check the opamp is fast enough
- Power should be low (< 10 µW) — this is a low-frequency bio application, no need for speed

## Tools

- ngspice, Python (numpy, scipy, matplotlib), SKY130 PDK, web search
