# Bandpass Filter — Design Program

## What This Block Does

Implements a bandpass filter with passband 0.5 Hz to 150 Hz. The high-pass removes electrode DC offset and motion artifacts. The low-pass acts as an anti-aliasing filter for the ADC.

## System Context

The filter sits between the PGA output and the ADC input. It must:
- Remove the DC component (electrode offset passed through from InAmp)
- Reject out-of-band noise to prevent aliasing in the ADC
- Add minimal noise of its own
- Present a low-impedance output to drive the ADC sampling capacitor

The 0.5 Hz high-pass corner is critical — it must be low enough to pass the ECG P-wave (which has energy down to ~0.5 Hz) without distortion. The 150 Hz low-pass is set by the ECG diagnostic bandwidth standard.

## Challenge: Very Low Frequencies

The 0.5 Hz high-pass is the main design challenge. In a continuous-time Gm-C filter, this requires either:
- Very large capacitors (hundreds of pF to nF)
- Very low transconductance (nA/V range, using subthreshold MOSFETs)
- Pseudo-resistors (subthreshold MOSFET resistors in the GΩ range)

In a switched-capacitor filter, the clock frequency must be much higher than the signal band (e.g., 10 kHz clock for 150 Hz bandwidth).

## Evaluation Criteria

### TB1: Frequency Response
- AC sweep from 0.01 Hz to 100 kHz
- Measure gain vs frequency
- Extract -3 dB corners (f_low, f_high)
- **Pass:** f_low < 1.0 Hz, f_high between 130 and 170 Hz, passband ripple < 1 dB
- **Plot:** `plots/frequency_response.png` (Bode plot, log frequency axis)

### TB2: Stopband Attenuation
- Measure gain at 250 Hz, 500 Hz, 1 kHz
- **Pass:** Attenuation > 20 dB at 250 Hz
- **Plot:** Same as TB1 with attenuation markers annotated

### TB3: Step Response (DC Offset Rejection)
- Apply a 300 mV DC step (simulating electrode placement)
- Verify output settles back to baseline
- Measure settling time
- **Pass:** Output returns within 10 mV of baseline within 5 seconds
- **Plot:** `plots/step_response.png` (show the high-pass transient recovery)

### TB4: Transient with ECG Signal
- Apply synthetic ECG + 60 Hz interference at the input
- Verify ECG shape preserved, 60 Hz attenuated
- **Pass:** ECG R-peak amplitude within ±5% of expected
- **Plot:** `plots/ecg_filtering.png` (input vs output overlay)

### TB5: Noise
- Noise analysis, integrate in passband
- **Pass:** Output noise < 100 µVrms
- **Plot:** `plots/noise_spectrum.png`

### TB6: PVT Corner Analysis
- Run TB1 across corners: verify f_low and f_high stay within spec
- **Pass:** Cutoff frequencies within 2x of nominal at all corners
- **Plot:** `plots/pvt_frequency_response.png`

## Interface

**Inputs:** `vin` (from PGA, centered at 0.9V), `vref` (1.2V from bandgap), `ibias` (1 µA)
**Outputs:** `vout` (filtered signal, centered at 0.9V)

## Design Constraints

- Single 1.8V supply
- SKY130 1.8V devices, poly resistors, MIM capacitors
- If using pseudo-resistors, the subthreshold MOSFET resistance will vary >10x over PVT — account for this
- If using switched-capacitor, the clock generation is part of this block
- Output must be able to drive 5 pF ADC sampling capacitor
