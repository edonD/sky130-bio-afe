#!/usr/bin/env python3
"""Robustness test: vary each design parameter by ±20% and verify all specs still pass."""

import subprocess, os, json, math, sys
import numpy as np

WORK_DIR = os.path.dirname(os.path.abspath(__file__))
SKY130_LIB = os.path.join(WORK_DIR, 'sky130_models', 'sky130.lib.spice')
VDD = 1.8
VCM = 0.9
RF_VAL = 10e6

SPECS = {
    'gain_error_pct':    {'target': 1.0,   'op': '<'},
    'bandwidth_hz':      {'target': 10000, 'op': '>'},
    'power_uw':          {'target': 10,    'op': '<'},
}

# Nominal parameters (from design.cir / evaluate.py opamp_subckt)
NOMINAL = {
    'ibias':       0.95e-6,   # Bias current
    'diff_w':      10e-6,     # Diff pair W
    'diff_l':      4e-6,      # Diff pair L
    'load_w':      4e-6,      # PMOS load W
    'load_l':      8e-6,      # PMOS load L
    'cs_w':        12e-6,     # 2nd stage PMOS W
    'cs_l':        8e-6,      # 2nd stage PMOS L
    'm7_w':        2e-6,      # 2nd stage NMOS W
    'cc_dim':      27e-6,     # Cc MIM w=l dimension (~1.46pF)
    'rz':          1500,      # Nulling resistor
    'rf':          10e6,      # Feedback resistor
}

def make_netlist(params, gain=128):
    rin_val = params['rf'] / gain
    cc_w = params['cc_dim']
    cc_l = params['cc_dim']
    return f"""* Robustness test PGA — gain={gain}
.lib "{SKY130_LIB}" tt

Vdd vdd 0 {VDD}
Vss vss 0 0
Vcm vcm_node 0 {VCM}

.subckt opamp inp inn out vdd vss
Ibias vdd nbias {params['ibias']}
XMn_diode nbias nbias vss vss sky130_fd_pr__nfet_01v8 w=2u l=4u m=1
XM5 tail nbias vss vss sky130_fd_pr__nfet_01v8 w=2u l=4u m=2
XM1 d1 inp tail vss sky130_fd_pr__nfet_01v8 w={params['diff_w']} l={params['diff_l']} m=1
XM2 d2 inn tail vss sky130_fd_pr__nfet_01v8 w={params['diff_w']} l={params['diff_l']} m=1
XM3 d2 d2 vdd vdd sky130_fd_pr__pfet_01v8 w={params['load_w']} l={params['load_l']} m=1
XM4 d1 d2 vdd vdd sky130_fd_pr__pfet_01v8 w={params['load_w']} l={params['load_l']} m=1
XM6 out d1 vdd vdd sky130_fd_pr__pfet_01v8 w={params['cs_w']} l={params['cs_l']} m=1
XM7 out nbias vss vss sky130_fd_pr__nfet_01v8 w={params['m7_w']} l=8u m=2
XCc d1 cc_mid sky130_fd_pr__cap_mim_m3_1 w={cc_w} l={cc_l} m=1
Rz cc_mid out {params['rz']}
.ends opamp

X1 vcm_node vminus vout vdd vss opamp
Rf vminus vout {params['rf']}
Rin vin vminus {rin_val}
Vin vin 0 dc {VCM} ac 1

.control
op
print i(Vdd)
ac dec 100 0.1 100Meg
wrdata _robustness_ac.dat v(vout)
.endc
.end
"""

def run_test(params, label=""):
    nf = os.path.join(WORK_DIR, '_tb_robustness.spice')
    with open(nf, 'w') as f:
        f.write(make_netlist(params))
    r = subprocess.run(['ngspice', '-b', nf], capture_output=True, text=True, timeout=120, cwd=WORK_DIR)
    
    # Parse power
    power_uw = None
    for line in r.stdout.splitlines():
        if 'i(vdd)' in line.lower() and '=' in line:
            try:
                val = float(line.split('=')[-1].strip().split()[0])
                power_uw = abs(val) * VDD * 1e6
            except: pass
    
    # Parse AC
    data = []
    path = os.path.join(WORK_DIR, '_robustness_ac.dat')
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#') or line.startswith('*'): continue
                parts = line.split()
                try: data.append([float(x) for x in parts])
                except: continue
    
    gain_err = 100
    bw = 0
    if len(data) > 5:
        arr = np.array(data)
        freqs = arr[:, 0]
        if arr.shape[1] >= 3:
            mags = np.sqrt(arr[:, 1]**2 + arr[:, 2]**2)
        else:
            mags = np.abs(arr[:, 1])
        
        low_idx = np.argmin(np.abs(freqs - 1.0))
        lf_gain = mags[low_idx]
        gain_err = abs(lf_gain - 128) / 128 * 100
        
        gain_3db = lf_gain / math.sqrt(2)
        bw_idx = np.where(mags < gain_3db)[0]
        bw = freqs[bw_idx[0]] if len(bw_idx) > 0 else freqs[-1]
    
    return {'gain_error_pct': gain_err, 'bandwidth_hz': bw, 'power_uw': power_uw or 999}

# Run nominal
print("="*70)
print("ROBUSTNESS TEST: ±20% parameter variation")
print("="*70)

nom_results = run_test(NOMINAL, "nominal")
print(f"\nNominal: err={nom_results['gain_error_pct']:.2f}%, BW={nom_results['bandwidth_hz']:.0f} Hz, P={nom_results['power_uw']:.2f} uW")

print(f"\n{'Parameter':<12} {'Variation':<10} {'GainErr%':<10} {'BW(Hz)':<10} {'Power(uW)':<10} {'Status'}")
print("-"*62)

all_pass = True
for param_name, nom_val in NOMINAL.items():
    for factor, label in [(0.8, '-20%'), (1.2, '+20%')]:
        params = NOMINAL.copy()
        params[param_name] = nom_val * factor
        
        results = run_test(params, f"{param_name}_{label}")
        
        pass_all = (results['gain_error_pct'] < 1.0 and 
                   results['bandwidth_hz'] > 10000 and 
                   results['power_uw'] < 10)
        status = "PASS" if pass_all else "FAIL"
        if not pass_all:
            all_pass = False
        
        print(f"{param_name:<12} {label:<10} {results['gain_error_pct']:<10.2f} {results['bandwidth_hz']:<10.0f} {results['power_uw']:<10.2f} [{status}]")

print(f"\nOverall robustness: {'PASS' if all_pass else 'FAIL'}")
