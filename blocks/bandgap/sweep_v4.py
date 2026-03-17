#!/usr/bin/env python3
"""V4 sweep: vary Rbias + Rcomp + OTA with current best wp/Ra/Rptat."""
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

def run_quick(netlist):
    n = re.sub(r'\.control.*?\.endc', '', netlist, flags=re.DOTALL)
    n = re.sub(r'\.end\s*$', '', n, flags=re.MULTILINE)
    sup_f = os.path.join(BLOCK_DIR, "sv_sup")
    temp_f = os.path.join(BLOCK_DIR, "sv_temp")
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
    fpath = os.path.join(BLOCK_DIR, "sv_test.cir")
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

best = -999
best_cfg = ""

# Try different combinations with wider wp_pass values
for wp in ['20e-6', '22e-6', '24e-6']:
    for rb in ['350e-6', '400e-6', '450e-6']:
        for rc in ['8k', '10k', '12k']:
            for lp_ota in ['4e-6', '5e-6', '6e-6']:
                for ln_ota in ['2e-6', '3e-6']:
                    n = set_params(base, {'p_wp_pass': wp, 'p_lp_ota': lp_ota, 'p_ln_ota': ln_ota})
                    n = set_rbias(n, rb)
                    n = re.sub(r'Rcomp ota_outp opamp_out \S+', f'Rcomp ota_outp opamp_out {rc}', n)
                    r = run_quick(n)
                    if r['vref'] is None or r['vref'] < 0.5: continue
                    vm = (0.05 - abs(r['vref'] - 1.20)) / 0.05 * 100 if 1.15 <= r['vref'] <= 1.25 else -999
                    tm = (50 - r['tc']) / 50 * 100
                    pm = (r['psrr'] - 60) / 60 * 100
                    pw = (20 - r['power']) / 20 * 100 if r['power'] and 0 < r['power'] < 20 else -999
                    mn = min(vm, tm, pm, pw)
                    if mn > best:
                        best = mn
                        best_cfg = f"wp={wp} rb={rb} rc={rc} lp_ota={lp_ota} ln_ota={ln_ota}"
                        print(f"NEW BEST min={mn:.1f}%: vref={r['vref']:.4f} tc={r['tc']:.1f} psrr={r['psrr']:.1f} pwr={r['power']:.1f} | {best_cfg}")

print(f"\nBest: {best:.1f}% at {best_cfg}")
