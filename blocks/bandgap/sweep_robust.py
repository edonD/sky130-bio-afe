#!/usr/bin/env python3
"""Sweep to find parameters that maximize minimum PSRR across ±20% variations."""
import subprocess, os, re
import numpy as np

BLOCK_DIR = os.path.dirname(os.path.abspath(__file__))
SKY130_DIR = os.path.join(BLOCK_DIR, "sky130_models")

def set_params(netlist, params):
    for k, v in params.items():
        netlist = re.sub(rf'(\.param\s+{k}\s*=\s*)[\S]+', rf'\g<1>{v}', netlist)
    return netlist

def run_quick(netlist):
    n = re.sub(r'\.control.*?\.endc', '', netlist, flags=re.DOTALL)
    n = re.sub(r'\.end\s*$', '', n, flags=re.MULTILINE)
    sup_f = os.path.join(BLOCK_DIR, "sr_sup")
    temp_f = os.path.join(BLOCK_DIR, "sr_temp")
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
    fpath = os.path.join(BLOCK_DIR, "sr_test.cir")
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

def check_robustness(base, nominal_params):
    """Check worst-case PSRR across ±20% variation of sensitive params."""
    worst_psrr = 999
    # Only check the params that failed in robustness test
    sensitive = ['p_lp_pass', 'p_r_w', 'p_ln_tail']
    for pname in sensitive:
        pval = nominal_params[pname]
        for factor in [0.8, 1.2]:
            n = set_params(base, {pname: f"{pval * factor:.6e}"})
            r = run_quick(n)
            if r['psrr'] < worst_psrr:
                worst_psrr = r['psrr']
    return worst_psrr

with open(os.path.join(BLOCK_DIR, "design.cir")) as f:
    base = f.read()

# Current nominal parameters
nom = {}
for m in re.finditer(r'\.param\s+(\w+)\s*=\s*(\S+)', base):
    nom[m.group(1)] = float(m.group(2))

# Sweep wp_pass from 20 to 30 with different Rbias to maximize worst-case PSRR
best_worst = 0
best_cfg = ""

for wp in [18, 20, 22, 24, 26, 28, 30]:
    for ra in [120, 122, 124]:
        for rptat in [12, 12.5, 13]:
            cfg = {'p_wp_pass': f'{wp}e-6', 'p_ra_l': f'{ra}e-6', 'p_rptat_l': f'{rptat}e-6'}
            n = set_params(base, cfg)
            # First check nominal
            r_nom = run_quick(n)
            if r_nom['vref'] is None or not (1.15 <= r_nom['vref'] <= 1.25): continue
            if r_nom['tc'] >= 50 or r_nom['psrr'] < 60: continue

            vref_m = (0.05 - abs(r_nom['vref'] - 1.20)) / 0.05 * 100
            tc_m = (50 - r_nom['tc']) / 50 * 100
            psrr_m = (r_nom['psrr'] - 60) / 60 * 100
            if min(vref_m, tc_m, psrr_m) < 25: continue

            # Check robustness
            nom_updated = nom.copy()
            nom_updated['p_wp_pass'] = wp * 1e-6
            nom_updated['p_ra_l'] = ra * 1e-6
            nom_updated['p_rptat_l'] = rptat * 1e-6
            worst = check_robustness(n, nom_updated)

            if worst > best_worst:
                best_worst = worst
                best_cfg = cfg
                print(f"wp={wp} ra={ra} rptat={rptat}: nom_psrr={r_nom['psrr']:.1f} worst_psrr={worst:.1f} "
                      f"vref={r_nom['vref']:.4f} tc={r_nom['tc']:.1f} | margins: v={vref_m:.0f} t={tc_m:.0f} p={psrr_m:.0f}")

print(f"\nBest worst-case PSRR: {best_worst:.1f} dB at {best_cfg}")
