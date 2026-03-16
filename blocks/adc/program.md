# 12-bit SAR ADC — Design Program

## What This Block Does

Digitizes the conditioned analog biosignal into 12-bit digital words at 1 kSPS per channel. This is the last analog block before the digital domain.

## System Context

The ADC receives a filtered, amplified signal from the bandpass filter output. The signal is centered at ~0.9V with swing depending on gain setting and signal amplitude. At the ADC, the signal bandwidth is limited to 150 Hz by the upstream filter, so 1 kSPS (500 Hz Nyquist) provides comfortable oversampling.

12-bit resolution gives 0.44 mV/LSB over 1.8V range. With total front-end gain of 50x-6400x, this maps to:
- At gain=50: 8.8 µV/LSB input-referred (adequate for ECG)
- At gain=6400: 0.069 µV/LSB input-referred (adequate for EEG)

## Evaluation Criteria

### TB1: Static Linearity (DNL/INL)
- Ramp test or histogram test: apply a slow ramp covering the full input range
- Compute DNL and INL for all 4096 codes
- **Pass:** DNL < 1.0 LSB (no missing codes), INL < 2.0 LSB
- **Plot:** `plots/dnl_inl.png` (DNL and INL vs code)

### TB2: Dynamic Performance (ENOB)
- Apply a sinusoidal input near Nyquist/4 (~125 Hz at 1 kSPS)
- Run 4096-point FFT of output codes
- Compute SINAD, ENOB, SFDR, THD
- **Pass:** ENOB > 10 bits
- **Plot:** `plots/fft_spectrum.png` (output spectrum with ENOB annotated)

### TB3: Conversion Time
- Measure total time from sample to valid digital output
- **Pass:** < 500 µs (supports 1 kSPS with margin for multiplexing 4 channels)
- **Plot:** `plots/conversion_timing.png`

### TB4: Power Consumption
- Measure average supply current at 1 kSPS
- **Pass:** < 10 µW
- **Plot:** `plots/power_vs_sample_rate.png`

### TB5: Input Range
- Sweep DC input from 0V to 1.8V
- Verify output code tracks linearly across the full range
- **Pass:** Usable range > 1.5V
- **Plot:** `plots/transfer_function.png`

### TB6: PVT Corner Analysis
- Run TB1 (DNL/INL) across 5 corners × 3 temperatures
- **Pass:** DNL < 1.5 LSB and INL < 3.0 LSB at ALL corners (relaxed from nominal)
- **Plot:** `plots/pvt_linearity.png`

### TB7: Noise Floor
- Apply constant DC input at mid-scale
- Collect 1000 consecutive samples
- Compute RMS code noise
- **Pass:** Code noise < 1.5 LSB rms (consistent with ENOB > 10)
- **Plot:** `plots/noise_histogram.png`

## Interface

**Inputs:** `vin` (analog input, 0 to 1.8V), `vref` (1.2V from bandgap), `clk` (sampling clock)
**Outputs:** `dout[11:0]` (12-bit digital output), `eoc` (end-of-conversion flag)

## Design Constraints

- Single 1.8V supply
- SKY130 1.8V devices and MIM capacitors
- Binary-weighted or split-capacitor DAC — agent's choice
- Comparator: StrongARM latch or dynamic comparator
- SAR logic: can be synchronous or asynchronous
- 1 kSPS is very slow — this relaxes comparator speed and DAC settling requirements significantly
- The main challenge is matching of capacitor DAC elements for 12-bit linearity

## Reference

The JKU open-source 12-bit SAR ADC (SKY130_SAR-ADC1) exists as reference, but you are free to design from scratch or use a different architecture.
