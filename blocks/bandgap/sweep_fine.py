#!/usr/bin/env python3
"""Fine-grained sweep around the working baseline to optimize all margins."""
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
dc temp 125 -40 -1
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
    if r['vref'] is None: return {'min': -999}
    vref_m = (0.05 - abs(r['vref'] - 1.20)) / 0.05 * 100 if 1.15 <= r['vref'] <= 1.25 else -999
    tc_m = (50 - r['tc']) / 50 * 100 if r['tc'] < 9000 else -999
    psrr_m = (r['psrr'] - 60) / 60 * 100
    power_m = (20 - r['power']) / 20 * 100 if r['power'] and 0 < r['power'] < 20 else -999
    return {'vref': vref_m, 'tc': tc_m, 'psrr': psrr_m, 'power': power_m,
            'min': min(vref_m, tc_m, psrr_m, power_m)}

with open(os.path.join(BLOCK_DIR, "design.cir")) as f:
    base = f.read()

# Fine sweep: vary Rbias, Ra, Rptat, pass transistor W/L, and OTA W around the baseline
best = -999
best_cfg = {}
best_r = {}
n_done = 0

# Sweep Rbias length (most impactful for PSRR)
for rb_l in ['350e-6', '375e-6', '400e-6', '425e-6', '450e-6']:
    # Sweep pass transistor (affects PSRR through loop gain)
    for wp_pass in ['6e-6', '8e-6', '10e-6', '12e-6']:
        for lp_pass in ['0.5e-6', '1e-6', '1.5e-6']:
            for m_pass in ['2', '4', '6']:
                cfg = {'p_ra_l': '120e-6', 'p_rptat_l': '12e-6'}
                n = set_params(base, cfg)
                # Update Rbias
                n = re.sub(r'(XRbias vdd ota_bias vss sky130_fd_pr__res_xhigh_po_0p69 w=\{p_r_w\} l=)\S+',
                           rf'\g<1>{rb_l}', n)
                # Update pass transistor
                n = set_params(n, {'p_wp_pass': wp_pass, 'p_lp_pass': lp_pass})
                n = re.sub(r'(XMP_pass vref opamp_out vdd vdd sky130_fd_pr__pfet_01v8.*m=)\d+',
                           rf'\g<1>{m_pass}', n)

                try:
                    r = run_eval(n)
                    m = margins(r)
                    if m['min'] > best:
                        best = m['min']
                        best_cfg = {'rb_l': rb_l, 'wp_pass': wp_pass, 'lp_pass': lp_pass, 'm_pass': m_pass}
                        best_r = r
                        print(f"[{n_done}] NEW BEST: min_margin={m['min']:.1f}% "
                              f"vref={r['vref']:.4f} tc={r['tc']:.1f} psrr={r['psrr']:.1f} power={r['power']:.1f} "
                              f"| margins: v={m['vref']:.0f} t={m['tc']:.0f} p={m['psrr']:.0f} pw={m['power']:.0f} "
                              f"| {best_cfg}")
                except: pass
                n_done += 1
                if n_done % 30 == 0:
                    print(f"  ... {n_done} done, best min_margin={best:.1f}%")

print(f"\n=== BEST: min_margin={best:.1f}% ===")
print(f"Config: {best_cfg}")
print(f"Results: {best_r}")
print(f"Margins: {margins(best_r)}")
