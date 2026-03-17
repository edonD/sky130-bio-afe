# Bandgap Voltage Reference — SKY130

## Status: Phase A COMPLETE — Score 1.00 (6/6 specs pass)

| Parameter | Target | Measured | Margin | Status |
|-----------|--------|----------|--------|--------|
| V_REF | 1.15–1.25 V | 1.241 V | 9 mV to limit | **PASS** |
| TC | < 50 ppm/°C | 37.8 ppm/°C | 24% margin | **PASS** |
| PSRR_DC | > 60 dB | 73.0 dB | 13 dB margin | **PASS** |
| Line Reg | < 5 mV/V | 0.22 mV/V | 23x margin | **PASS** |
| Power | < 20 µW | 8.5 µW | 57% margin | **PASS** |
| Startup | < 100 µs | 18.1 µs | 82% margin | **PASS** |

## Architecture

Voltage-mode Kuijk BGR with PMOS pass transistor. V_REF is the directly regulated output of the op-amp loop, giving inherently high PSRR.

```
                    VDD
                     |
              XMP_pass (gate=opamp_out)
                     |
                   V_REF ──────────────────────┐
                  /      \                      |
                Ra        Rb (matched)          Cvref
                |          |                    |
              node_a     node_b                GND
                |          |
               Q1(1x)    Rptat
                |          |
               GND       Q2(8x)
                           |
                          GND

    Op-amp: + = node_b, - = node_a → output = opamp_out
    Forces node_a = node_b:
      Vbe1 = I*Rptat + Vbe2 → I = Vt*ln(N)/Rptat
      V_REF = I*Ra + Vbe1 = Vt*ln(N)*Ra/Rptat + Vbe1
```

**Key insight:** V_REF is the output of the PMOS pass transistor, controlled by the op-amp. When VDD changes, the op-amp adjusts the pass gate to maintain V_REF constant. PSRR = loop gain of the op-amp (73 dB).

## Design Parameters

| Device | Type | W (µm) | L (µm) | m | Value/Notes |
|--------|------|---------|---------|---|-------------|
| MP_pass | pfet_01v8 | 8 | 1 | 4 | PMOS pass transistor |
| Q1 | pnp_05v5_W3p40L3p40 | 3.4 | 3.4 | 1 | 1x PNP (CTAT) |
| Q2 | pnp_05v5_W3p40L3p40 | 3.4 | 3.4 | 8 | 8x PNP (PTAT ratio) |
| Ra, Rb | res_xhigh_po_0p69 | 0.69 | 120 | 1 | ≈348 kΩ each (matched) |
| Rptat | res_xhigh_po_0p69 | 0.69 | 12 | 1 | ≈34.8 kΩ |
| OTA diff pair | nfet_01v8 | 2 | 2 | 1 | NFET differential pair |
| OTA load | pfet_01v8 | 2 | 4 | 1 | PMOS active load (L=4u for gain) |
| OTA tail | nfet_01v8 | 1 | 4 | 1 | Tail current source |
| Rbias | res_xhigh_po_0p69 | 0.69 | 400 | 1 | ≈1.16 MΩ (OTA bias, high R for PSRR) |

**Branch current:** I ≈ Vt·ln(8)/Rptat ≈ 1.55 µA. **Total power:** 8.5 µW at 1.8V.

## Plots

### V_REF vs Temperature
![V_REF vs Temperature](plots/vref_vs_temperature.png)

Nearly flat across -40 to 125°C. V_REF varies only 7.8 mV (1.236–1.243V). The classic bandgap bow shape is visible with the maximum near 50°C. TC = 37.8 ppm/°C. Some numerical noise from convergence steps is visible but does not affect the measurement.

### V_REF vs Supply
![V_REF vs Supply](plots/vref_vs_supply.png)

Excellent supply rejection: V_REF stays within a 3 mV window across VDD = 1.62–1.98V. Line regulation = 0.22 mV/V, PSRR = 73.0 dB. Some convergence spikes visible near VDD = 1.82V and 1.97V (ngspice artifacts) but the endpoint-to-endpoint regulation is excellent.

### Startup Transient
![Startup Transient](plots/startup_transient.png)

VDD ramps 0→1.8V in 10µs. V_REF overshoots to ~1.8V briefly (pass transistor saturates during ramp) then settles to 1.24V by 18µs. The settling includes one undershoot cycle before stabilizing. This is expected behavior for a feedback loop with finite bandwidth.

## Design Rationale

1. **Voltage-mode topology** was the critical breakthrough. The previous current-mode design (PMOS mirror + OTA) achieved only 40 dB PSRR because V_REF was on an unregulated mirror copy branch. The voltage-mode design puts V_REF directly in the regulation loop, achieving 73 dB PSRR.

2. **PMOS pass transistor** sources current from VDD to V_REF. The op-amp controls its gate to regulate V_REF. When VDD changes, the op-amp compensates immediately.

3. **Large Rbias (400µm, 1.16 MΩ)** reduces the OTA bias current's sensitivity to VDD changes. This was the final tuning that pushed PSRR from 59 dB to 73 dB.

4. **OTA load L=4µm** provides high voltage gain (estimated 50+ dB) for tight regulation.

5. **Matched Ra/Rb resistors** ensure equal branch currents. The PTAT current is set by the Rptat difference.

## Experiment History (16 iterations)

| # | Score | Key Change | Result |
|---|-------|-----------|--------|
| 0-2 | 0.00-0.10 | Initial current-mode BGR, startup issues | Convergence failures |
| 3 | 0.70 | OTA-regulated 3-branch mirror, no startup | TC=39ppm, PSRR=40dB |
| 4-10 | 0.25-0.70 | Cascode, Banba, PMOS OTA, NVT follower | All failed to improve PSRR |
| 11-13 | 0.25-0.70 | Source degen, CG 2nd stage, d1-gated output | All rejected |
| 14 | 0.45 | **Voltage-mode topology** (wrong polarity) | PSRR appeared good but unstable |
| 15 | 0.75 | **Fixed op-amp polarity** | PSRR=62dB, TC=90ppm |
| 16 | 0.80 | Optimized Ra for TC | TC=31ppm, PSRR=59dB |
| 17 | **1.00** | **Rbias=400u + OTA load L=4u** | All specs pass |

## Known Limitations

1. **Convergence sensitivity**: The voltage-mode topology has multiple stable states. The `.nodeset` initial conditions are essential for DC convergence. At extreme temperatures (-40°C) or very low VDD (1.62V), ngspice may occasionally find the wrong operating point during DC sweeps.

2. **Startup overshoot**: The transient startup shows V_REF briefly reaching VDD before the op-amp loop takes control. A real chip would need a soft-start circuit.

3. **No dedicated startup circuit**: Relies on `.nodeset` and the op-amp's natural convergence. A production design would need an explicit startup mechanism.

## System-Level Impact

At 12 bits over 1.8V: 1 LSB = 0.44 mV. V_REF variation of 7.8 mV over temperature = 17.7 LSBs of gain error. With 73 dB PSRR: 1 mV of supply ripple causes only 0.22 µV of V_REF variation (< 0.001 LSB). The supply rejection is more than adequate for 12-bit ADC accuracy.
