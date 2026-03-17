#!/usr/bin/env python3
"""Fast targeted sweep: one parameter at a time from working baseline."""
import subprocess, os, re
import numpy as np

BLOCK_DIR = os.path.dirname(os.path.abspath(__file__))
SKY130_DIR = os.path.join(BLOCK_DIR, "sky130_models")

def set_params(netlist, params):
    for k, v in params.items():
        netlist = re.sub(rf'(\.param\s+{k}\s*=\s*)[\S]+', rf'\g<1>{v}', netlist)
    return netlist

def set_rbias(netlist, val):
    return re.sub(r'(XRbias vdd ota_bias vss sky130_fd_pr__res_xhigh_po_0p69 w=\{p_r_w\} l=)\S+',
                  rf'\g<1>{val}', netlist)

def set_mpass(netlist, val):
    return re.sub(r'(XMP_pass vref opamp_out vdd vdd sky130_fd_pr__pfet_01v8.*m=)\d+',
                  rf'\g<1>{val}', netlist)

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

with open(os.path.join(BLOCK_DIR, "design.cir")) as f:
    base = f.read()

print("=== Baseline ===")
r = run_eval(base)
print(f"  vref={r['vref']:.4f} tc={r['tc']:.1f} psrr={r['psrr']:.1f} power={r['power']:.1f}")

print("\n=== Sweep PMOS pass L (higher L → higher rds → less VDD feedthrough) ===")
for lp in ['0.5e-6', '1e-6', '1.5e-6', '2e-6', '3e-6', '4e-6']:
    n = set_params(base, {'p_lp_pass': lp})
    r = run_eval(n)
    if r['vref']: print(f"  lp_pass={lp}: vref={r['vref']:.4f} tc={r['tc']:.1f} psrr={r['psrr']:.1f} power={r['power']:.1f}")

print("\n=== Sweep PMOS pass W (wider → more gm → more loop gain) ===")
for wp in ['4e-6', '6e-6', '8e-6', '10e-6', '15e-6', '20e-6']:
    n = set_params(base, {'p_wp_pass': wp})
    r = run_eval(n)
    if r['vref']: print(f"  wp_pass={wp}: vref={r['vref']:.4f} tc={r['tc']:.1f} psrr={r['psrr']:.1f} power={r['power']:.1f}")

print("\n=== Sweep PMOS pass multiplier ===")
for m in ['2', '4', '6', '8']:
    n = set_mpass(base, m)
    r = run_eval(n)
    if r['vref']: print(f"  m_pass={m}: vref={r['vref']:.4f} tc={r['tc']:.1f} psrr={r['psrr']:.1f} power={r['power']:.1f}")

print("\n=== Sweep Rbias length ===")
for rb in ['300e-6', '350e-6', '400e-6', '450e-6', '500e-6']:
    n = set_rbias(base, rb)
    r = run_eval(n)
    if r['vref']: print(f"  rbias_l={rb}: vref={r['vref']:.4f} tc={r['tc']:.1f} psrr={r['psrr']:.1f} power={r['power']:.1f}")

print("\n=== Sweep Ccomp (stability affects DC convergence) ===")
for cc in ['0.5p', '1p', '2p', '3p', '5p']:
    n = re.sub(r'Ccomp opamp_out vss \S+', f'Ccomp opamp_out vss {cc}', base)
    r = run_eval(n)
    if r['vref']: print(f"  Ccomp={cc}: vref={r['vref']:.4f} tc={r['tc']:.1f} psrr={r['psrr']:.1f} power={r['power']:.1f}")

print("\n=== Sweep Rcomp ===")
for rc in ['5k', '10k', '20k', '50k', '100k']:
    n = re.sub(r'Rcomp ota_outp opamp_out \S+', f'Rcomp ota_outp opamp_out {rc}', base)
    r = run_eval(n)
    if r['vref']: print(f"  Rcomp={rc}: vref={r['vref']:.4f} tc={r['tc']:.1f} psrr={r['psrr']:.1f} power={r['power']:.1f}")
