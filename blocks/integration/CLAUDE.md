# System Integration Agent

Autonomous system integration engineer combining all bio-AFE sub-blocks into a working acquisition system.

Follow the experiment loop defined in `../../CLAUDE.md`.

## Setup

Read these files before starting:
1. `program.md` — integration plan and validation methodology
2. `specs.json` — target specifications (the only constraints)
3. `../../interfaces.md` — interface contracts between all blocks
4. `../../master_spec.json` — top-level system requirements
5. **Read measurements.json from ALL upstream blocks:**
   - `../bandgap/measurements.json` — V_REF, TC, PSRR, power
   - `../inamp/measurements.json` — gain, noise, CMRR, offset, bandwidth, power
   - `../pga/measurements.json` — gain accuracy, noise, THD, bandwidth, power
   - `../filter/measurements.json` — cutoff frequencies, noise, power
   - `../adc/measurements.json` — ENOB, DNL, INL, conversion time, power
6. Import `design.cir` from upstream blocks as needed for SPICE validation

## Freedom

You can modify ANY file except `specs.json`. You choose:
- The system simulation approach (full SPICE, behavioral, mixed)
- The ECG/EEG signal generation method
- How to model the 4-channel system
- Any Python packages you need

## Quality Requirements

### Signal Chain Integrity
- Verify voltage compatibility at every block boundary
- The InAmp output must be within the PGA input range
- The PGA output must be within the filter input range
- The filter output must be within the ADC input range
- At NO gain setting should any stage saturate with a realistic biosignal

### Anti-Benchmaxxing
1. System noise must account for ALL blocks, not just the dominant one
2. ECG test must use realistic morphology (P-QRS-T, not just a sine wave)
3. Include electrode DC offset in ECG test — this is the #1 cause of real-world failure
4. CMRR must be measured end-to-end, not just at the InAmp
5. Power must include ALL blocks (bandgap prorated across 4 channels)

### Sanity Checks
- System noise should be dominated by InAmp (first stage) — if PGA or filter dominate, gains are wrong
- CMRR should be close to InAmp CMRR (other stages add/subtract a few dB, not tens)
- Total power = bandgap/4 + inamp + pga + filter + adc ≈ 5 + 15 + 10 + 10 + 10 = ~50 µW
- A 1 mV ECG with 400x gain = 400 mV at ADC. With 12-bit ADC (0.44 mV/LSB), that's ~900 codes of swing. SNR should be ~40-50 dB.

## Tools

- ngspice for SPICE simulation
- Python (numpy, scipy, matplotlib) for behavioral modeling
- SKY130 PDK models
- Web search
