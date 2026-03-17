#!/usr/bin/env python3
"""
Quick parameter sweep to find optimal OTA sizing and Rout for bandgap.
Focus on improving PSRR while maintaining V_REF, TC, and power specs.
"""
import subprocess, os, re, sys, json
import numpy as np

BLOCK_DIR = os.path.dirname(os.path.abspath(__file__))
SKY130_DIR = os.path.join(BLOCK_DIR, "sky130_models")


def run_quick_eval(params_override):
    """Run DC + supply sweep only (skip temp and startup for speed)."""
    with open(os.path.join(BLOCK_DIR, "design.cir")) as f:
        netlist = f.read()

    for k, v in params_override.items():
        netlist = re.sub(rf'(\.param\s+{k}\s*=\s*)[\S]+', rf'\g<1>{v}', netlist)

    # DC operating point + supply sweep in one run
    ctrl = f""".control
op
let vref_val = v(vref)
let idd = -@VDD[i]
let power_uw = idd * 1.8 * 1e6
print vref_val power_uw

dc VDD 1.62 1.98 0.01
wrdata {os.path.join(BLOCK_DIR, 'opt_supply')} v(vref)

dc temp -40 125 5
wrdata {os.path.join(BLOCK_DIR, 'opt_temp')} v(vref)

quit
.endc"""

    netlist = re.sub(r'\.control.*?\.endc', ctrl, netlist, flags=re.DOTALL)
    nf = os.path.join(BLOCK_DIR, "opt_test.cir")
    with open(nf, 'w') as f:
        f.write(netlist)

    result = subprocess.run(
        ["ngspice", "-b", nf],
        capture_output=True, text=True, timeout=120, cwd=SKY130_DIR
    )
    out = result.stdout + "\n" + result.stderr

    # Parse DC
    vref = None
    power = None
    for line in out.split('\n'):
        if 'vref_val' in line and '=' in line:
            m = re.search(r'=\s*([\d.eE+\-]+)', line)
            if m: vref = float(m.group(1))
        if 'power_uw' in line and '=' in line:
            m = re.search(r'=\s*([\d.eE+\-]+)', line)
            if m: power = float(m.group(1))

    # Parse supply sweep
    supply_file = os.path.join(BLOCK_DIR, 'opt_supply')
    psrr_db = 0
    line_reg = 999
    if os.path.exists(supply_file):
        data = []
        with open(supply_file) as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) >= 2:
                    try: data.append([float(p) for p in parts[:2]])
                    except: pass
        if len(data) > 5:
            arr = np.array(data)
            dv = arr[-1, 1] - arr[0, 1]
            dvdd = arr[-1, 0] - arr[0, 0]
            line_reg = abs(dv/dvdd) * 1000
            if abs(dv) > 1e-15:
                psrr_db = 20 * np.log10(abs(dvdd/dv))

    # Parse temp sweep
    tc_ppm = 9999
    temp_file = os.path.join(BLOCK_DIR, 'opt_temp')
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
            temps, vrefs = arr[:, 0], arr[:, 1]
            vnom = vrefs[np.argmin(np.abs(temps - 27))]
            if vnom > 0:
                tc_ppm = (np.max(vrefs) - np.min(vrefs)) / (vnom * 165) * 1e6

    return {
        'vref': vref, 'power': power, 'psrr_db': psrr_db,
        'line_reg': line_reg, 'tc_ppm': tc_ppm
    }


def score_result(r):
    if r['vref'] is None: return 0
    s = 0
    if 1.15 <= r['vref'] <= 1.25: s += 20
    if r['tc_ppm'] < 50: s += 25
    if r['psrr_db'] > 60: s += 20
    if r['line_reg'] < 5: s += 10
    if r['power'] is not None and 0 < r['power'] < 20: s += 15
    s += 10  # assume startup passes
    return s / 100


# Sweep OTA parameters
best_score = 0
best_params = {}
best_result = {}

sweep_configs = []
# Vary OTA load L (main gain knob) and diff pair W/L
for lp_ota in ['2e-6', '4e-6', '8e-6']:
    for wn_ota in ['1e-6', '2e-6', '4e-6']:
        for ln_ota in ['2e-6', '4e-6']:
            for rout_l in ['120e-6', '122e-6', '124e-6']:
                for rbias_l in ['200e-6', '400e-6']:
                    sweep_configs.append({
                        'p_lp_ota': lp_ota, 'p_wp_ota': wn_ota,
                        'p_wn_ota': wn_ota, 'p_ln_ota': ln_ota,
                        'p_rout_l': rout_l
                    })

# Also try varying Rbias (affects OTA bias sensitivity)
# This is embedded in the netlist directly, need special handling

print(f"Running {len(sweep_configs)} configurations...")

for i, cfg in enumerate(sweep_configs):
    try:
        r = run_quick_eval(cfg)
        s = score_result(r)
        if s > best_score or (s == best_score and r['psrr_db'] > best_result.get('psrr_db', 0)):
            best_score = s
            best_params = cfg
            best_result = r
            print(f"  [{i}] NEW BEST: score={s:.2f} vref={r['vref']:.4f}V tc={r['tc_ppm']:.1f}ppm "
                  f"psrr={r['psrr_db']:.1f}dB line={r['line_reg']:.2f}mV/V power={r['power']:.1f}uW")
    except Exception as e:
        pass

    if (i+1) % 20 == 0:
        print(f"  ... {i+1}/{len(sweep_configs)} done")

print(f"\n=== BEST CONFIGURATION ===")
print(f"Score: {best_score:.2f}")
print(f"Params: {best_params}")
print(f"Results: {best_result}")
