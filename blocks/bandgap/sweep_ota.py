#!/usr/bin/env python3
"""Targeted parameter sweep for V2 bandgap optimization."""
import subprocess, os, re, sys
import numpy as np

BLOCK_DIR = os.path.dirname(os.path.abspath(__file__))
SKY130_DIR = os.path.join(BLOCK_DIR, "sky130_models")

def read_base():
    with open(os.path.join(BLOCK_DIR, "design.cir")) as f:
        return f.read()

def set_params(netlist, params):
    for k, v in params.items():
        netlist = re.sub(rf'(\.param\s+{k}\s*=\s*)[\S]+', rf'\g<1>{v}', netlist)
    return netlist

def run_quick(netlist, label):
    n = re.sub(r'\.control.*?\.endc', '', netlist, flags=re.DOTALL)
    n = re.sub(r'\.end\s*$', '', n, flags=re.MULTILINE)
    sup_file = os.path.join(BLOCK_DIR, f"sw_sup")
    temp_file = os.path.join(BLOCK_DIR, f"sw_temp")
    ctrl = f""".control
op
let vref_val = v(vref)
let idd = -i(VDD)
let power_uw = idd * 1.8 * 1e6
print vref_val power_uw
dc VDD 1.98 1.62 -0.01
wrdata {sup_file} v(vref)
dc temp 125 -40 -5
wrdata {temp_file} v(vref)
quit
.endc
.end
"""
    n += "\n" + ctrl
    fpath = os.path.join(BLOCK_DIR, f"sw_test.cir")
    with open(fpath, 'w') as f:
        f.write(n)
    result = subprocess.run(["ngspice", "-b", fpath],
        capture_output=True, text=True, timeout=120, cwd=SKY130_DIR)
    out = result.stdout + "\n" + result.stderr
    vref = power = None
    for line in out.split('\n'):
        if 'vref_val' in line and '=' in line:
            m = re.search(r'=\s*([-+]?[\d.]+(?:[eE][-+]?\d+)?)', line)
            if m: vref = float(m.group(1))
        if 'power_uw' in line and '=' in line:
            m = re.search(r'=\s*([-+]?[\d.]+(?:[eE][-+]?\d+)?)', line)
            if m: power = float(m.group(1))
    psrr = 0
    if os.path.exists(sup_file):
        data = []
        with open(sup_file) as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) >= 2:
                    try: data.append([float(p) for p in parts[:2]])
                    except: pass
        if len(data) > 5:
            arr = np.array(data)
            dv = arr[0, 1] - arr[-1, 1]
            dvdd = arr[0, 0] - arr[-1, 0]
            if abs(dv) > 1e-15:
                psrr = 20 * np.log10(abs(dvdd / dv))
    tc = 9999
    if os.path.exists(temp_file):
        data = []
        with open(temp_file) as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) >= 2:
                    try: data.append([float(p) for p in parts[:2]])
                    except: pass
        if len(data) > 5:
            arr = np.array(data)
            vrefs = arr[:, 1]
            temps = arr[:, 0]
            idx27 = np.argmin(np.abs(temps - 27))
            vnom = vrefs[idx27]
            if vnom > 0:
                tc = (np.max(vrefs) - np.min(vrefs)) / (vnom * 165) * 1e6
    return {'vref': vref, 'power': power, 'psrr': psrr, 'tc': tc}

base = read_base()

# Targeted sweep: keep N=8, vary Ra/Rptat ratio and OTA sizing
configs = []

# Phase 1: Find best Ra/Rptat for TC with baseline OTA
for ra in ['118e-6', '119e-6', '120e-6', '121e-6', '122e-6']:
    for rptat in ['11.5e-6', '12e-6', '12.5e-6']:
        configs.append({
            'p_ra_l': ra, 'p_rptat_l': rptat, 'p_nbjt': '8',
            'p_lp_ota': '4e-6', 'p_ln_ota': '2e-6',
            'p_wp_ota': '2e-6', 'p_wn_ota': '2e-6', 'p_ln_tail': '4e-6'
        })

# Phase 2: Try different OTA sizes with the baseline Ra/Rptat
for lp in ['4e-6', '6e-6', '8e-6', '10e-6']:
    for wp in ['2e-6', '4e-6', '6e-6']:
        for ln in ['2e-6', '4e-6']:
            for lt in ['4e-6', '8e-6']:
                configs.append({
                    'p_ra_l': '120e-6', 'p_rptat_l': '12e-6', 'p_nbjt': '8',
                    'p_lp_ota': lp, 'p_ln_ota': ln,
                    'p_wp_ota': wp, 'p_wn_ota': '2e-6', 'p_ln_tail': lt
                })

# Phase 3: Different Rbias lengths
for rb in ['300e-6', '400e-6', '500e-6', '600e-6', '800e-6']:
    configs.append({
        'p_ra_l': '120e-6', 'p_rptat_l': '12e-6', 'p_nbjt': '8',
        'p_lp_ota': '4e-6', 'p_ln_ota': '2e-6',
        'p_wp_ota': '2e-6', 'p_wn_ota': '2e-6', 'p_ln_tail': '4e-6'
    })

print(f"Total: {len(configs)} configs")
best_composite = -999
best_cfg = None
best_r = None

for i, cfg in enumerate(configs):
    try:
        n = set_params(base, cfg)
        r = run_quick(n, str(i))
        if r['vref'] is None or r['vref'] < 0.5: continue

        vref_m = (0.05 - abs(r['vref'] - 1.20)) / 0.05 * 100 if 1.15 <= r['vref'] <= 1.25 else -999
        tc_m = (50 - r['tc']) / 50 * 100 if r['tc'] < 50 else -999
        psrr_m = (r['psrr'] - 60) / 60 * 100 if r['psrr'] > 60 else -999
        power_m = (20 - r['power']) / 20 * 100 if r['power'] and 0 < r['power'] < 20 else -999
        min_m = min(vref_m, tc_m, psrr_m, power_m)
        composite = min_m  # Maximize the minimum margin

        if composite > best_composite:
            best_composite = composite
            best_cfg = cfg
            best_r = r
            print(f"[{i}] NEW BEST: min_margin={min_m:.1f}% vref={r['vref']:.4f}V tc={r['tc']:.1f}ppm "
                  f"psrr={r['psrr']:.1f}dB power={r['power']:.1f}uW | {cfg}")
    except: pass
    if (i+1) % 20 == 0:
        print(f"  ... {i+1}/{len(configs)}")

print(f"\nBEST: min_margin={best_composite:.1f}% cfg={best_cfg} result={best_r}")
