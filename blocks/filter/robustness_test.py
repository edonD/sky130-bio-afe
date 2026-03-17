#!/usr/bin/env python3
"""
Robustness test: vary each design parameter by ±20% and verify all specs pass.
Tests: Rbias, pseudo-R, Cin/Cfb, all Sallen-Key caps, all R values.
"""

import subprocess
import numpy as np
import re
import os

def run_sim_with_modifications(mods_desc, netlist_mods):
    """Run a single AC simulation with modified design and return key metrics."""
    with open('design.cir', 'r') as f:
        netlist = f.read()

    # Apply modifications
    for old, new in netlist_mods:
        netlist = netlist.replace(old, new)

    # Strip .end and add AC analysis
    lines = netlist.rstrip().split('\n')
    if lines[-1].strip() == '.end':
        lines = lines[:-1]
    netlist = '\n'.join(lines) + '\n'
    netlist += """
.ac dec 200 0.01 100k
.control
run
let vout_mag = abs(v(output))
let vout_db = vdb(output)
wrdata _robustness_ac.txt vout_mag vout_db
quit
.endc
.end
"""

    with open('_robustness.cir', 'w') as f:
        f.write(netlist)

    result = subprocess.run(['ngspice', '-b', '_robustness.cir'],
                          capture_output=True, text=True, timeout=120)

    if not os.path.exists('_robustness_ac.txt'):
        return None

    arr = np.loadtxt('_robustness_ac.txt')
    if arr is None or len(arr) < 10:
        return None

    freq = np.abs(arr[:, 0])
    mask = freq > 0
    freq = freq[mask]

    if arr.shape[1] >= 5:
        mag_db = arr[mask, 3]
    else:
        mag_lin = arr[mask, 1]
        mag_db = 20 * np.log10(np.maximum(mag_lin, 1e-15))

    # Remove duplicates
    uf, idx = np.unique(freq, return_index=True)
    freq = uf
    mag_db = mag_db[idx]

    # Extract metrics
    pb_mask = (freq >= 0.5) & (freq <= 150)
    if not np.any(pb_mask):
        return None

    peak_db = np.max(mag_db[pb_mask])

    # f_low
    target_low = peak_db - 3.0
    f_low = 999
    for i in range(len(freq) - 1):
        if freq[i] < 100 and mag_db[i] < target_low and mag_db[i+1] >= target_low:
            f_low = freq[i] + (freq[i+1] - freq[i]) * (target_low - mag_db[i]) / (mag_db[i+1] - mag_db[i])
            break
    if f_low == 999 and mag_db[0] >= target_low:
        f_low = freq[0]

    # f_high
    target_high = peak_db - 3.0
    f_high = 0
    for i in range(len(freq) - 2, 0, -1):
        if freq[i] > 1 and mag_db[i] >= target_high and mag_db[i+1] < target_high:
            f_high = freq[i] + (freq[i+1] - freq[i]) * (target_high - mag_db[i]) / (mag_db[i+1] - mag_db[i])
            break

    # Ripple
    ripple = np.max(mag_db[pb_mask]) - np.min(mag_db[pb_mask])

    # Attenuation at 250 Hz
    idx_250 = np.argmin(np.abs(freq - 250))
    atten_250 = peak_db - mag_db[idx_250]

    return {
        'f_low': f_low, 'f_high': f_high,
        'ripple': ripple, 'atten_250': atten_250,
        'peak': peak_db
    }

def check_specs(metrics):
    """Check if all specs pass."""
    if metrics is None:
        return False, "SIM FAILED"
    fails = []
    if metrics['f_low'] >= 1.0: fails.append(f"f_low={metrics['f_low']:.2f}")
    if not (130 <= metrics['f_high'] <= 170): fails.append(f"f_high={metrics['f_high']:.1f}")
    if metrics['ripple'] >= 1.0: fails.append(f"ripple={metrics['ripple']:.2f}")
    if metrics['atten_250'] <= 20: fails.append(f"atten={metrics['atten_250']:.1f}")
    if fails:
        return False, ", ".join(fails)
    return True, "ALL PASS"

# Define parameters to vary
# Format: (description, [(old_string, new_string_-20%), (old_string, new_string_+20%)])
params = [
    ("Rbias", "Rbias vdd nbias 4.0Meg",
     [("Rbias vdd nbias 4.0Meg", "Rbias vdd nbias 3.2Meg"),  # -20%
      ("Rbias vdd nbias 4.0Meg", "Rbias vdd nbias 4.8Meg")]), # +20%

    ("Pseudo-R", "Rpr a b 100G",
     [("Rpr a b 100G", "Rpr a b 80G"),
      ("Rpr a b 100G", "Rpr a b 120G")]),

    ("C_in", "C_in input hpf_in 50p",
     [("C_in input hpf_in 50p", "C_in input hpf_in 40p"),
      ("C_in input hpf_in 50p", "C_in input hpf_in 60p")]),

    ("C_fb", "C_fb hpf_in hpf_out 50p",
     [("C_fb hpf_in hpf_out 50p", "C_fb hpf_in hpf_out 40p"),
      ("C_fb hpf_in hpf_out 50p", "C_fb hpf_in hpf_out 60p")]),

    ("S1_Ca", "C_s1a s1_mid s1_out 90p",
     [("C_s1a s1_mid s1_out 90p", "C_s1a s1_mid s1_out 72p"),
      ("C_s1a s1_mid s1_out 90p", "C_s1a s1_mid s1_out 108p")]),

    ("S1_Cb", "C_s1b s1_buf vcm 87p",
     [("C_s1b s1_buf vcm 87p", "C_s1b s1_buf vcm 70p"),
      ("C_s1b s1_buf vcm 87p", "C_s1b s1_buf vcm 104p")]),

    ("S2_Ca", "C_s2a s2_mid s2_out 107p",
     [("C_s2a s2_mid s2_out 107p", "C_s2a s2_mid s2_out 86p"),
      ("C_s2a s2_mid s2_out 107p", "C_s2a s2_mid s2_out 128p")]),

    ("S3_Ca", "C_s3a s3_mid s3_out 159p",
     [("C_s3a s3_mid s3_out 159p", "C_s3a s3_mid s3_out 127p"),
      ("C_s3a s3_mid s3_out 159p", "C_s3a s3_mid s3_out 191p")]),

    ("S4_Ca", "C_s4a s4_mid s4_out 375p",
     [("C_s4a s4_mid s4_out 375p", "C_s4a s4_mid s4_out 300p"),
      ("C_s4a s4_mid s4_out 375p", "C_s4a s4_mid s4_out 450p")]),

    ("S4_Cb", "C_s4b s4_buf vcm 21p",
     [("C_s4b s4_buf vcm 21p", "C_s4b s4_buf vcm 17p"),
      ("C_s4b s4_buf vcm 21p", "C_s4b s4_buf vcm 25p")]),

    ("All_R (10M)", "10Meg",
     [("10Meg", "8Meg"),
      ("10Meg", "12Meg")]),
]

print("=" * 80)
print("ROBUSTNESS TEST: ±20% parameter variation")
print("=" * 80)

# First run nominal
print("\nNominal design:")
nominal = run_sim_with_modifications("nominal", [])
if nominal:
    print(f"  f_low={nominal['f_low']:.3f} f_high={nominal['f_high']:.1f} ripple={nominal['ripple']:.2f} atten={nominal['atten_250']:.1f}")

all_pass = True
results = []

for name, orig_str, mods in params:
    for i, (old, new) in enumerate(mods):
        pct = "-20%" if i == 0 else "+20%"
        label = f"{name} {pct}"
        m = run_sim_with_modifications(label, [(old, new)])
        passed, status = check_specs(m)
        if m:
            print(f"  {label:20s}: f_low={m['f_low']:.3f} f_high={m['f_high']:.1f} ripple={m['ripple']:.2f} atten={m['atten_250']:.1f} → {status}")
        else:
            print(f"  {label:20s}: SIM FAILED")
            passed = False
        if not passed:
            all_pass = False
        results.append((label, passed, m))

print("\n" + "=" * 80)
if all_pass:
    print("ROBUSTNESS: ALL PARAMETERS PASS WITH ±20% VARIATION ✓")
else:
    print("ROBUSTNESS: SOME PARAMETERS FAIL WITH ±20% VARIATION ✗")
    for label, passed, m in results:
        if not passed:
            _, status = check_specs(m)
            print(f"  FAIL: {label} — {status}")

# Cleanup
for f in ['_robustness.cir', '_robustness_ac.txt']:
    if os.path.exists(f):
        os.remove(f)
