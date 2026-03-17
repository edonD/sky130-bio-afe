#!/usr/bin/env python3
"""Combined sweep of wp_pass and Ra/Rptat for optimal margins."""
import subprocess, os, re
import numpy as np

BLOCK_DIR = os.path.dirname(os.path.abspath(__file__))
SKY130_DIR = os.path.join(BLOCK_DIR, "sky130_models")

def set_params(netlist, params):
    for k, v in params.items():
        netlist = re.sub(rf'(\.param\s+{k}\s*=\s*)[\S]+', rf'\g<1>{v}', netlist)
    return netlist

def run_eval(netlist):
    n = re.sub(r'\.control.*?\.endc', '', netlist, flags=re.DOTALL)
    n = re.sub(r'\.end\s*$', '', n, flags=re.MULTILINE)
    sup_f = os.path.join(BLOCK_DIR, "sf_sup")
    temp_f = os.path.join(BLOCK_DIR, "sf_temp")
    ctrl = f""".control
op
let vref_val = v(vref)
let idd = -i(VDD)
let power_uw = idd * 1.8 * 1e6
print vref_val power_uw
dc VDD 1.98 1.62 -0.01
wrdata {sup_f} v(vref)
dc temp 125 -40 -5
wrdata {temp_f} v(vref)
quit
.endc
.end
"""
    n += "\n" + ctrl
    fpath = os.path.join(BLOCK_DIR, "sf_test.cir")
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
    if os.path.exists(sup_f):
        data = []
        with open(sup_f) as f:
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
    if os.path.exists(temp_f):
        data = []
        with open(temp_f) as f:
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

def margins(r):
    if r['vref'] is None: return -999
    vref_m = (0.05 - abs(r['vref'] - 1.20)) / 0.05 * 100 if 1.15 <= r['vref'] <= 1.25 else -999
    tc_m = (50 - r['tc']) / 50 * 100
    psrr_m = (r['psrr'] - 60) / 60 * 100
    power_m = (20 - r['power']) / 20 * 100 if r['power'] and 0 < r['power'] < 20 else -999
    return min(vref_m, tc_m, psrr_m, power_m), vref_m, tc_m, psrr_m

with open(os.path.join(BLOCK_DIR, "design.cir")) as f:
    base = f.read()

best = -999
best_cfg = ""
print(f"{'wp_pass':>8} {'ra_l':>8} {'rptat_l':>8} | {'vref':>7} {'tc':>6} {'psrr':>6} {'power':>6} | {'v_m':>5} {'tc_m':>5} {'p_m':>5} {'min':>5}")
print("-" * 90)

for wp in ['10e-6', '12e-6', '14e-6', '16e-6', '18e-6', '20e-6']:
    for ra in ['110e-6', '115e-6', '118e-6', '120e-6', '122e-6', '125e-6']:
        for rptat in ['11e-6', '11.5e-6', '12e-6', '12.5e-6', '13e-6']:
            n = set_params(base, {'p_wp_pass': wp, 'p_ra_l': ra, 'p_rptat_l': rptat})
            try:
                r = run_eval(n)
                if r['vref'] is None or r['vref'] < 0.5: continue
                mn, vm, tm, pm = margins(r)
                if mn > best:
                    best = mn
                    best_cfg = f"wp={wp} ra={ra} rptat={rptat}"
                    marker = " *** NEW BEST"
                else:
                    marker = ""
                if mn > 15:  # Only print promising results
                    print(f"{wp:>8} {ra:>8} {rptat:>8} | {r['vref']:7.4f} {r['tc']:6.1f} {r['psrr']:6.1f} {r['power']:6.1f} | {vm:5.1f} {tm:5.1f} {pm:5.1f} {mn:5.1f}{marker}")
            except: pass

print(f"\nBest min_margin: {best:.1f}% at {best_cfg}")
