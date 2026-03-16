# Interface Contracts — SKY130 Bio-AFE

## Signal Naming Convention

All signals use lowercase with underscores. Buses use bracket notation.

## Global Signals

| Signal | Description | Nominal |
|--------|-------------|---------|
| `vdd` | Positive supply | 1.8 V |
| `vss` | Ground | 0 V |
| `vref` | Bandgap reference voltage | ~1.2 V |
| `ibias` | Reference bias current | ~1 µA |

## Technology Constants (SKY130)

| Parameter | Value |
|-----------|-------|
| VDD | 1.8 V |
| nfet Vth (typical) | ~0.4 V |
| pfet Vth (typical) | ~-0.4 V |
| Min L (1.8V devices) | 0.15 µm |
| Min W | 0.42 µm |
| Temperature range | -40 to 125 °C |
| Supply tolerance | ±10% (1.62 V to 1.98 V) |
| Process corners | tt, ss, ff, sf, fs |

## Block-to-Block Interfaces

### Bandgap → All Blocks

The bandgap provides voltage and current references consumed by every analog block.

| Parameter | Symbol | Nominal | Tolerance | Unit |
|-----------|--------|---------|-----------|------|
| Reference voltage | V_REF | 1.20 | ±1% over PVT | V |
| Bias current | I_BIAS | 1.0 | ±5% over PVT | µA |
| PSRR at DC | PSRR_DC | >60 | - | dB |
| Output impedance | R_OUT | <1 | - | kΩ |
| Temperature coefficient | TC | <50 | - | ppm/°C |

### Instrumentation Amplifier → PGA

| Parameter | Symbol | Nominal | Unit |
|-----------|--------|---------|------|
| Output voltage range | V_OUT | 0.2 to 1.6 | V |
| Output impedance | R_OUT | <1 | kΩ |
| DC bias point | V_CM_OUT | 0.9 | V |
| Gain | A_V | 10 to 100 (programmable) | V/V |
| Signal bandwidth | BW | DC to 10 kHz (min) | Hz |

### PGA → Filter

| Parameter | Symbol | Nominal | Unit |
|-----------|--------|---------|------|
| Output voltage range | V_OUT | 0.2 to 1.6 | V |
| Output impedance | R_OUT | <10 | kΩ |
| DC bias point | V_CM_OUT | 0.9 | V |
| Gain | A_V | 1 to 128 (programmable) | V/V |

### Filter → ADC

| Parameter | Symbol | Nominal | Unit |
|-----------|--------|---------|------|
| Output voltage range | V_OUT | 0.0 to 1.8 | V |
| Output impedance | R_OUT | <1 | kΩ |
| Signal bandwidth | BW | 0.5 to 150 | Hz |
| Attenuation at 250 Hz | ATTEN | >20 | dB |
| DC bias point | V_CM | 0.9 | V |

### ADC → Digital Output

| Parameter | Symbol | Value | Unit |
|-----------|--------|-------|------|
| Resolution | N_BITS | 12 | bits |
| Sample rate | F_S | 1000 | SPS |
| Input range | V_IN | 0 to 1.8 | V |
| Digital output | D_OUT | 12-bit unsigned | - |

## Biosignal Characteristics (Design Context)

These are the signals the system must handle. Each block should be validated
against these realistic input conditions.

| Signal | Amplitude | Bandwidth | Electrode offset |
|--------|-----------|-----------|-----------------|
| ECG | 0.5 - 5 mV | 0.5 - 150 Hz | ±300 mV |
| EEG | 10 - 100 µV | 0.5 - 50 Hz | ±300 mV |
| EMG | 0.1 - 5 mV | 10 - 500 Hz | ±300 mV |

Key challenges:
- Electrode DC offset (up to ±300 mV) must not saturate the signal chain
- 50/60 Hz powerline interference must be rejected (CMRR >100 dB)
- Motion artifacts appear as large low-frequency transients
