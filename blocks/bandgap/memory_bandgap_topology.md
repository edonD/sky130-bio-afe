---
name: bandgap_voltage_mode_topology
description: Voltage-mode Kuijk BGR achieves score 1.00 — key insight was putting V_REF in the op-amp loop
type: project
---

The bandgap voltage reference achieved score 1.00 (all 6 specs pass) using a voltage-mode Kuijk topology with a PMOS pass transistor. The key architectural decision was making V_REF the directly regulated output of the op-amp loop, rather than a passive mirror copy.

**Why:** The initial current-mode design (PMOS mirror + OTA) was stuck at PSRR = 40 dB because V_REF was on an unregulated 3rd mirror branch. 13+ experiments failed to improve PSRR with the current-mode topology. Switching to voltage-mode (V_REF = op-amp output via PMOS pass) gave PSRR = 73 dB.

**How to apply:** For future analog blocks requiring high PSRR, prefer voltage-mode (LDO-like) architectures where the regulated output is directly in the feedback loop. Also: Rbias for op-amp tail current is a critical PSRR knob — larger R = less VDD sensitivity. OTA load L is the main gain knob.

**Critical bug found:** Op-amp input polarity was accidentally swapped (positive feedback). The circuit appeared to work at nominal due to .nodeset forcing a metastable point. Always verify feedback polarity analytically before simulating.
