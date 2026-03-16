# 12-bit SAR ADC Agent

Autonomous analog IC designer working on the ADC for a biomedical AFE.

Follow the experiment loop defined in `../../CLAUDE.md`.

## Setup

Read these files before starting:
1. `program.md` — evaluation criteria and testbench requirements
2. `specs.json` — target specifications (the only constraints)
3. `../../interfaces.md` — interface contracts
4. `../../master_spec.json` — system-level context

## Freedom

You can modify ANY file except `specs.json`. You choose:
- The DAC architecture (binary-weighted, split-cap, C-2C, segmented)
- The comparator topology (StrongARM, double-tail, etc.)
- Synchronous or asynchronous SAR logic
- Capacitor unit size and layout strategy for matching
- Optimization method and Python packages

## Quality Requirements

### Anti-Benchmaxxing
1. DNL/INL must be measured over the FULL code range (4096 codes), not just a few
2. ENOB must be computed from a proper FFT with coherent sampling, not from DC noise alone
3. At 12 bits, capacitor mismatch is the dominant error — if DNL is perfect (< 0.01 LSB), check that mismatch models are included
4. Power at 1 kSPS should be very low — if >50 µW, the comparator is burning static current or the clock is too fast
5. Verify the reference voltage is stable during conversion (charge sharing with DAC)

### Sanity Checks
- A 12-bit binary-weighted cap DAC needs 4096 × C_unit. With C_unit = 1 fF (min for matching), total = 4 pF. Reasonable for SKY130.
- At 1 kSPS, conversion time is 1 ms max. With 12 bits and asynchronous SAR, each bit takes ~10-50 ns → total ~0.5 µs. There is massive timing margin.
- Power at 1 kSPS dominated by comparator kicks: ~0.5 fJ/conversion × 12 bits × 1000/s = nW. Leakage and bias dominate.
- ENOB > 10 bits at 1 kSPS is very achievable at 130nm — this is not a hard spec

## Tools

- ngspice, Python (numpy, scipy, matplotlib), SKY130 PDK, web search
