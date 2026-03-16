# Instrumentation Amplifier Agent

Autonomous analog IC designer working on the instrumentation amplifier — the most critical block in a biomedical AFE.

Follow the experiment loop defined in `../../CLAUDE.md`.

## Setup

Read these files before starting:
1. `program.md` — evaluation criteria and testbench requirements
2. `specs.json` — target specifications (the only constraints)
3. `../../interfaces.md` — interface contracts and biosignal characteristics
4. `../../master_spec.json` — system-level context

## Freedom

You can modify ANY file except `specs.json`. You choose:
- The topology (3-opamp, current-feedback, capacitively-coupled, direct, etc.)
- Whether to use chopping, auto-zeroing, or neither
- Transistor sizes, bias currents, feedback network
- The optimization method
- Any Python packages you need

## Quality Requirements

### Anti-Benchmaxxing
1. Noise must be measured with proper integration (0.5–150 Hz), not spot noise at one frequency
2. CMRR must be measured at 60 Hz specifically (the powerline frequency that matters)
3. Gain must be measured with realistic signal levels (µV to mV), not large signals that mask nonlinearity
4. If using chopping, verify that chopper ripple at the output is filtered or acceptably small
5. Test with realistic electrode offset (±300 mV) — many designs work perfectly with zero offset but saturate with real electrodes

### Sanity Checks
- Noise floor for a µA-bias OTA in 130nm should be 0.5–5 µVrms in the ECG band — if you get 0.01 µV, check the simulation
- CMRR > 80 dB requires careful matching or chopping — >120 dB is world-class, verify carefully
- Power should be 5–50 µW for bio applications — if it's >100 µW, the bias is too high
- The output should be centered near mid-supply (0.9V), not railed

## Tools

- ngspice for SPICE simulation
- Python (numpy, scipy, matplotlib) for analysis and optimization
- SKY130 PDK models
- Web search for researching instrumentation amplifier topologies for biomedical
