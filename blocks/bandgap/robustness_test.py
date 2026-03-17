#!/usr/bin/env python3
"""
Robustness test: vary each design parameter by ±20% one at a time.
All specs must still pass at each variation.
"""
import subprocess, os, re, json
import numpy as np

BLOCK_DIR = os.path.dirname(os.path.abspath(__file__))
SKY130_DIR = os.path.join(BLOCK_DIR, "sky130_models")

SPECS = {
    'vref_v': {'target': (1.15, 1.25), 'type': 'range'},
    'tc_ppm_c': {'target': 50, 'type': 'less_than'},
    'psrr_dc_db': {'target': 60, 'type': 'greater_than'},
    'line_regulation_mv_v': {'target': 5, 'type': 'less_than'},
    'power_uw': {'target': 20, 'type': 'less_than'},
}

def set_params(netlist, params):
    for k, v in params.items():
        netlist = re.sub(rf'(\.param\s+{k}\s*=\s*)[\S]+', rf'\g<1>{v}', netlist)
    return netlist

def run_eval(netlist):
    n = re.sub(r'\.control.*?\.endc', '', netlist, flags=re.DOTALL)
    n = re.sub(r'\.end\s*$', '', n, flags=re.MULTILINE)
    sup_f = os.path.join(BLOCK_DIR, "rob_sup")
    temp_f = os.path.join(BLOCK_DIR, "rob_temp")
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
    fpath = os.path.join(BLOCK_DIR, "rob_test.cir")
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
    line_reg = 999
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
            line_reg = abs(dv / dvdd) * 1000 if abs(dvdd) > 0 else 999
    return {'vref_v': vref, 'tc_ppm_c': tc, 'psrr_dc_db': psrr,
            'line_regulation_mv_v': line_reg, 'power_uw': power}

def check_pass(r):
    fails = []
    if r['vref_v'] is None: return ['vref_v: None']
    if not (1.15 <= r['vref_v'] <= 1.25): fails.append(f"vref_v={r['vref_v']:.4f}")
    if r['tc_ppm_c'] >= 50: fails.append(f"tc={r['tc_ppm_c']:.1f}")
    if r['psrr_dc_db'] < 60: fails.append(f"psrr={r['psrr_dc_db']:.1f}")
    if r['line_regulation_mv_v'] >= 5: fails.append(f"line_reg={r['line_regulation_mv_v']:.2f}")
    if r['power_uw'] is None or r['power_uw'] >= 20: fails.append(f"power={r['power_uw']}")
    return fails

with open(os.path.join(BLOCK_DIR, "design.cir")) as f:
    base = f.read()

# Extract parameters
params = {}
for m in re.finditer(r'\.param\s+(\w+)\s*=\s*(\S+)', base):
    params[m.group(1)] = float(m.group(2))

print("=" * 80)
print("ROBUSTNESS TEST: ±20% Parameter Variation")
print("=" * 80)

# Nominal result
print("\n--- Nominal ---")
r_nom = run_eval(base)
nom_fails = check_pass(r_nom)
print(f"  vref={r_nom['vref_v']:.4f} tc={r_nom['tc_ppm_c']:.1f} psrr={r_nom['psrr_dc_db']:.1f} "
      f"power={r_nom['power_uw']:.1f} | {'PASS' if not nom_fails else 'FAIL: ' + ', '.join(nom_fails)}")

results = []
total_pass = 0
total_tests = 0

for pname, pval in params.items():
    if pval == 0: continue
    for factor, label in [(0.8, "-20%"), (1.2, "+20%")]:
        new_val = pval * factor
        n = set_params(base, {pname: f"{new_val:.6e}"})
        try:
            r = run_eval(n)
            fails = check_pass(r)
            status = "PASS" if not fails else "FAIL"
            total_tests += 1
            if not fails: total_pass += 1
            detail = f"vref={r['vref_v']:.4f} tc={r['tc_ppm_c']:.1f} psrr={r['psrr_dc_db']:.1f} pwr={r['power_uw']:.1f}"
            fail_str = f" [{', '.join(fails)}]" if fails else ""
            print(f"  {pname} {label} ({pval:.2e} → {new_val:.2e}): {status} {detail}{fail_str}")
            results.append({'param': pname, 'variation': label, 'nominal': pval, 'varied': new_val,
                           'results': r, 'pass': not fails, 'fails': fails})
        except Exception as e:
            print(f"  {pname} {label}: ERROR {e}")
            total_tests += 1

print(f"\n{'=' * 80}")
print(f"ROBUSTNESS SUMMARY: {total_pass}/{total_tests} variations pass all specs")
print(f"{'=' * 80}")

# Save results
with open(os.path.join(BLOCK_DIR, "robustness_results.json"), 'w') as f:
    json.dump({'total_pass': total_pass, 'total_tests': total_tests,
               'results': results}, f, indent=2, default=str)

if total_pass == total_tests:
    print("ROBUST: All parameters tolerate ±20% variation!")
else:
    print("\nFailing variations:")
    for r in results:
        if not r['pass']:
            print(f"  {r['param']} {r['variation']}: {', '.join(r['fails'])}")
