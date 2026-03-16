# Programmable Gain Amplifier — Design Program

## What This Block Does

Provides digitally-selectable voltage gain from 1x to 128x in binary steps (1, 2, 4, 8, 16, 32, 64, 128). Allows the system to adapt to different biosignal types (ECG: moderate gain, EEG: maximum gain) and electrode conditions.

## System Context

The PGA sits between the instrumentation amplifier (fixed ~50x gain) and the bandpass filter. Together, the InAmp + PGA provide total gain from 50x to 6400x, mapping microvolt biosignals into the ADC's 0-1.8V input range.

At maximum total gain (6400x), a 100 µV EEG signal becomes 640 mV — well within the ADC's range. At minimum gain (50x), a 5 mV ECG signal becomes 250 mV.

## Evaluation Criteria

### TB1: Gain Accuracy at All Settings
- Set each gain step (1, 2, 4, 8, 16, 32, 64, 128)
- Apply 10 mV differential input at 10 Hz
- Measure output amplitude, compute actual gain vs ideal
- **Pass:** Gain error < 1% at every setting
- **Plot:** `plots/gain_accuracy.png` (bar chart: ideal vs measured at each step)

### TB2: Frequency Response at Min/Max Gain
- AC sweep 0.1 Hz to 1 MHz at gain=1 and gain=128
- **Pass:** -3 dB bandwidth > 10 kHz at gain=128
- **Plot:** `plots/ac_response.png` (overlay of all gain settings)

### TB3: Noise
- Noise simulation at gain=1 (worst case for input-referred)
- Integrate from 0.5 Hz to 150 Hz
- **Pass:** Output-referred noise < 50 µVrms at gain=1
- **Plot:** `plots/noise_spectrum.png`

### TB4: Linearity (THD)
- Apply 10 Hz sine, amplitude set for 1 Vpp output, at gain=1 and gain=128
- Measure THD from FFT of transient output
- **Pass:** THD < 0.1%
- **Plot:** `plots/thd_analysis.png`

### TB5: Gain Switching Transient
- Switch gain from 1x to 128x during simulation
- Measure settling time to 0.1% of final value
- **Pass:** Settling time < 100 µs
- **Plot:** `plots/gain_switching.png`

### TB6: PVT Corner Analysis
- Run TB1 at all 5 corners × 3 temperatures
- **Pass:** Gain error < 2% at ALL corners (relaxed from 1% nominal)
- **Plot:** `plots/pvt_gain_accuracy.png`

## Interface

**Inputs:** `vin` (from InAmp output, ~0.9V ± signal), `vref` (~1.2V from bandgap), `ibias` (~1 µA), `gain[2:0]` (3-bit digital gain select)
**Outputs:** `vout` (amplified signal, centered at ~0.9V)

## Design Constraints

- Single 1.8V supply
- Gain selection via 3-bit digital input (CMOS logic levels)
- Resistor-based or capacitor-based gain setting — agent's choice
- Must not introduce significant DC offset (< 5 mV output offset)
- SKY130 1.8V devices, poly resistors, MIM capacitors available
