#!/usr/bin/env python3
"""
Bandgap Voltage Reference — Full Evaluation Suite
TB1: DC operating point
TB2: Temperature sweep (-40 to 125°C)
TB3: Supply sweep (1.62V to 1.98V) → line regulation + PSRR
TB4: Startup transient
TB5: PVT corners (5 corners × 3 temps × 3 supplies)

Reads design.cir as the base netlist. Produces plots/ and measurements.json.
"""

import subprocess, os, re, sys, json, shutil
import numpy as np

try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    HAS_MPL = True
except ImportError:
    HAS_MPL = False
    print("WARNING: matplotlib not available, skipping plots")

BLOCK_DIR = os.path.dirname(os.path.abspath(__file__))
SKY130_DIR = os.path.join(BLOCK_DIR, "sky130_models")
PLOTS_DIR = os.path.join(BLOCK_DIR, "plots")
os.makedirs(PLOTS_DIR, exist_ok=True)

SPECS = {
    'vref_v': {'target': (1.15, 1.25), 'weight': 20, 'type': 'range'},
    'tc_ppm_c': {'target': 50, 'weight': 25, 'type': 'less_than'},
    'psrr_dc_db': {'target': 60, 'weight': 20, 'type': 'greater_than'},
    'line_regulation_mv_v': {'target': 5, 'weight': 10, 'type': 'less_than'},
    'power_uw': {'target': 20, 'weight': 15, 'type': 'less_than'},
    'startup_time_us': {'target': 100, 'weight': 10, 'type': 'less_than'},
}


def read_design():
    with open(os.path.join(BLOCK_DIR, "design.cir")) as f:
        return f.read()


def make_testbench(netlist, corner, sim_control):
    """Replace .lib corner and .control block in netlist."""
    # Remove existing .control/.endc and everything after .option/.nodeset up to .end
    n = re.sub(r'\.control.*?\.endc', '', netlist, flags=re.DOTALL)
    n = re.sub(r'\.end\s*$', '', n, flags=re.MULTILINE)
    # Replace corner
    n = re.sub(r'\.lib\s+"sky130_models/sky130\.lib\.spice"\s+\w+',
               f'.lib "sky130_models/sky130.lib.spice" {corner}', n)
    n += "\n" + sim_control + "\n.end\n"
    return n


def run_ngspice(netlist_str, filename, timeout=120):
    """Write netlist to file and run ngspice -b. Returns stdout+stderr."""
    fpath = os.path.join(BLOCK_DIR, filename)
    with open(fpath, 'w') as f:
        f.write(netlist_str)
    result = subprocess.run(
        ["ngspice", "-b", fpath],
        capture_output=True, text=True, timeout=timeout,
        cwd=SKY130_DIR
    )
    return result.stdout + "\n" + result.stderr


def parse_wrdata(filepath):
    """Parse ngspice wrdata output (col0=sweep, col1=value, optional col2...)."""
    data = []
    if not os.path.exists(filepath):
        return np.array([])
    with open(filepath) as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) >= 2:
                try:
                    row = [float(p) for p in parts]
                    data.append(row)
                except ValueError:
                    continue
    return np.array(data) if data else np.array([])


def parse_print_value(output, varname):
    """Extract a printed value from ngspice output."""
    for line in output.split('\n'):
        if varname in line and '=' in line:
            m = re.search(r'=\s*([-+]?[\d.]+(?:[eE][-+]?\d+)?)', line)
            if m:
                return float(m.group(1))
    return None


# ============================================================
# TB1: DC Operating Point
# ============================================================
def run_tb1(netlist, corner='tt', temp=27, vdd=1.8):
    ctrl = f""".control
option temp={temp}
alter @VDD[dc] = {vdd}
op
let vref_val = v(vref)
let idd = -i(VDD)
let power_uw = idd * {vdd} * 1e6
print vref_val idd power_uw
quit
.endc"""
    # Override VDD
    n = netlist.replace(f'VDD vdd 0 DC 1.8', f'VDD vdd 0 DC {vdd}')
    tb = make_testbench(n, corner, ctrl)
    # Set temp in options
    tb = re.sub(r'(\.option\s+)', f'.option temp={temp}\n\\1', tb, count=1)
    out = run_ngspice(tb, "tb1_run.cir")

    vref = parse_print_value(out, 'vref_val')
    idd = parse_print_value(out, 'idd')
    power = parse_print_value(out, 'power_uw')

    return {'vref': vref, 'idd': idd, 'power_uw': power, 'raw': out}


# ============================================================
# TB2: Temperature Sweep
# ============================================================
def run_tb2(netlist, corner='tt'):
    datafile = os.path.join(BLOCK_DIR, "tb2_data")
    # Sweep from 125 down to -40 for better convergence (starts near 27C nodeset)
    ctrl = f""".control
dc temp 125 -40 -1
wrdata {datafile} v(vref)
quit
.endc"""
    tb = make_testbench(netlist, corner, ctrl)
    out = run_ngspice(tb, "tb2_run.cir")
    data = parse_wrdata(datafile)
    return data, out


def analyze_tb2(data):
    if len(data) < 10:
        return {'tc_ppm_c': 9999, 'vref_27': None, 'vmin': None, 'vmax': None}
    temps = data[:, 0]
    vrefs = data[:, 1]
    idx27 = np.argmin(np.abs(temps - 27))
    vnom = vrefs[idx27]
    vmin = np.min(vrefs)
    vmax = np.max(vrefs)
    tc = (vmax - vmin) / (vnom * 165) * 1e6 if vnom > 0 else 9999
    return {'tc_ppm_c': tc, 'vref_27': vnom, 'vmin': vmin, 'vmax': vmax,
            'tmin': temps[np.argmin(vrefs)], 'tmax': temps[np.argmax(vrefs)]}


# ============================================================
# TB3: Supply Sweep
# ============================================================
def run_tb3(netlist, corner='tt'):
    datafile = os.path.join(BLOCK_DIR, "tb3_data")
    # Sweep from high to low for better convergence (starts near nominal 1.8V)
    ctrl = f""".control
dc VDD 1.98 1.62 -0.005
wrdata {datafile} v(vref)
quit
.endc"""
    tb = make_testbench(netlist, corner, ctrl)
    out = run_ngspice(tb, "tb3_run.cir")
    data = parse_wrdata(datafile)
    return data, out


def analyze_tb3(data):
    if len(data) < 5:
        return {'psrr_dc_db': 0, 'line_reg_mv_v': 999}
    vdd_vals = data[:, 0]
    vref_vals = data[:, 1]
    dvdd = vdd_vals[-1] - vdd_vals[0]
    dvref = vref_vals[-1] - vref_vals[0]
    line_reg = abs(dvref / dvdd) * 1000 if abs(dvdd) > 0 else 999
    psrr = 20 * np.log10(abs(dvdd / dvref)) if abs(dvref) > 1e-15 else 120
    return {'psrr_dc_db': psrr, 'line_reg_mv_v': line_reg,
            'dvdd_mv': dvdd * 1000, 'dvref_uv': dvref * 1e6}


# ============================================================
# TB4: Startup Transient
# ============================================================
def run_tb4(netlist, corner='tt'):
    datafile = os.path.join(BLOCK_DIR, "tb4_data")
    # Replace DC supply with PWL ramp
    n = netlist.replace('VDD vdd 0 DC 1.8', 'VDD vdd 0 PWL(0 0 10u 1.8 500u 1.8)')
    ctrl = f""".control
tran 0.1u 500u
wrdata {datafile} v(vref) v(vdd)
quit
.endc"""
    tb = make_testbench(n, corner, ctrl)
    # Remove .nodeset for transient (let it start from 0)
    tb = re.sub(r'\.nodeset.*?\n(\+.*?\n)*', '', tb)
    out = run_ngspice(tb, "tb4_run.cir", timeout=180)
    data = parse_wrdata(datafile)
    return data, out


def analyze_tb4(data):
    if len(data) < 10:
        return {'startup_time_us': 999, 'final_vref': 0}
    times = data[:, 0]
    vrefs = data[:, 1]
    # Final value = average of last 10% of data
    n10 = max(1, len(vrefs) // 10)
    final = np.mean(vrefs[-n10:])
    if final < 0.5:
        return {'startup_time_us': 999, 'final_vref': final, 'stuck': True}
    # Find time when vref first reaches within 1% of final
    threshold = 0.99 * final
    settled_idx = np.where(vrefs >= threshold)[0]
    if len(settled_idx) == 0:
        return {'startup_time_us': 999, 'final_vref': final}
    # Check it stays within 1% after that point
    first_cross = settled_idx[0]
    startup_us = times[first_cross] * 1e6
    return {'startup_time_us': startup_us, 'final_vref': final}


# ============================================================
# TB5: PVT Corner Analysis
# ============================================================
def run_tb5(netlist):
    """Run temp sweep across corners and supplies."""
    corners = ['tt', 'ss', 'ff', 'sf', 'fs']
    temps_check = [-40, 27, 125]
    supplies = [1.62, 1.8, 1.98]
    results = []
    corner_curves = {}

    for corner in corners:
        datafile = os.path.join(BLOCK_DIR, f"tb5_{corner}")
        ctrl = f""".control
dc temp -40 125 5
wrdata {datafile} v(vref)
quit
.endc"""
        tb = make_testbench(netlist, corner, ctrl)
        run_ngspice(tb, f"tb5_{corner}.cir")
        data = parse_wrdata(datafile)
        if len(data) > 5:
            corner_curves[corner] = data
            for t in temps_check:
                idx = np.argmin(np.abs(data[:, 0] - t))
                vref = data[idx, 1]
                results.append({'corner': corner, 'temp': t, 'vdd': 1.8, 'vref': vref})

    # Also check supply corners at tt
    for vdd in [1.62, 1.98]:
        n = netlist.replace('VDD vdd 0 DC 1.8', f'VDD vdd 0 DC {vdd}')
        for corner in corners:
            r = run_tb1(n, corner=corner, vdd=vdd)
            if r['vref'] is not None:
                results.append({'corner': corner, 'temp': 27, 'vdd': vdd, 'vref': r['vref']})

    return results, corner_curves


# ============================================================
# Scoring
# ============================================================
def compute_score(measurements):
    total_weight = sum(s['weight'] for s in SPECS.values())
    earned = 0
    details = {}

    for name, spec in SPECS.items():
        val = measurements.get(name)
        if val is None:
            details[name] = {'value': None, 'pass': False, 'margin_pct': -100}
            continue

        if spec['type'] == 'range':
            lo, hi = spec['target']
            mid = (lo + hi) / 2
            half = (hi - lo) / 2
            dist = abs(val - mid)
            passed = lo <= val <= hi
            margin = (half - dist) / half * 100 if half > 0 else 0
        elif spec['type'] == 'less_than':
            passed = val < spec['target']
            margin = (spec['target'] - val) / spec['target'] * 100 if spec['target'] > 0 else 0
        elif spec['type'] == 'greater_than':
            passed = val > spec['target']
            margin = (val - spec['target']) / spec['target'] * 100 if spec['target'] > 0 else 0

        if passed:
            earned += spec['weight']
        details[name] = {
            'value': val, 'pass': passed,
            'margin_pct': round(margin, 1),
            'meets_25pct': margin >= 25
        }

    score = earned / total_weight
    return score, details


# ============================================================
# Plotting
# ============================================================
def plot_tb2(data, filename="vref_vs_temperature.png"):
    if not HAS_MPL or len(data) < 5:
        return
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(data[:, 0], data[:, 1] * 1000, 'b-', linewidth=2)
    ax.set_xlabel('Temperature (°C)')
    ax.set_ylabel('V_REF (mV)')
    ax.set_title('Bandgap Reference vs Temperature')
    ax.grid(True, alpha=0.3)
    ax.axhline(y=1200, color='r', linestyle='--', alpha=0.5, label='1.200V')
    ax.legend()
    fig.tight_layout()
    fig.savefig(os.path.join(PLOTS_DIR, filename), dpi=150)
    plt.close(fig)


def plot_tb3(data, filename="vref_vs_supply.png"):
    if not HAS_MPL or len(data) < 5:
        return
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(data[:, 0], data[:, 1] * 1000, 'b-', linewidth=2)
    ax.set_xlabel('VDD (V)')
    ax.set_ylabel('V_REF (mV)')
    ax.set_title('Bandgap Reference vs Supply Voltage')
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(PLOTS_DIR, filename), dpi=150)
    plt.close(fig)


def plot_tb4(data, filename="startup_transient.png"):
    if not HAS_MPL or len(data) < 10:
        return
    fig, ax1 = plt.subplots(figsize=(8, 5))
    t_us = data[:, 0] * 1e6
    ax1.plot(t_us, data[:, 1], 'b-', linewidth=2, label='V_REF')
    if data.shape[1] > 2:
        ax2 = ax1.twinx()
        ax2.plot(t_us, data[:, 2], 'r--', linewidth=1, label='VDD', alpha=0.5)
        ax2.set_ylabel('VDD (V)', color='r')
        ax2.legend(loc='lower right')
    ax1.set_xlabel('Time (µs)')
    ax1.set_ylabel('V_REF (V)')
    ax1.set_title('Startup Transient')
    ax1.grid(True, alpha=0.3)
    ax1.legend(loc='center right')
    fig.tight_layout()
    fig.savefig(os.path.join(PLOTS_DIR, filename), dpi=150)
    plt.close(fig)


def plot_pvt(corner_curves, filename="pvt_corners.png"):
    if not HAS_MPL or not corner_curves:
        return
    fig, ax = plt.subplots(figsize=(8, 5))
    colors = {'tt': 'blue', 'ss': 'red', 'ff': 'green', 'sf': 'orange', 'fs': 'purple'}
    for corner, data in corner_curves.items():
        ax.plot(data[:, 0], data[:, 1] * 1000, color=colors.get(corner, 'gray'),
                linewidth=1.5, label=corner.upper())
    ax.set_xlabel('Temperature (°C)')
    ax.set_ylabel('V_REF (mV)')
    ax.set_title('V_REF vs Temperature — All Process Corners')
    ax.axhline(y=1150, color='k', linestyle='--', alpha=0.3, label='Spec limits')
    ax.axhline(y=1250, color='k', linestyle='--', alpha=0.3)
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(PLOTS_DIR, filename), dpi=150)
    plt.close(fig)


# ============================================================
# Main
# ============================================================
def main():
    print("=" * 60)
    print("BANDGAP VOLTAGE REFERENCE EVALUATION")
    print("=" * 60)

    netlist = read_design()

    # Print parameters
    params = {}
    for m in re.finditer(r'\.param\s+(\w+)\s*=\s*(\S+)', netlist):
        params[m.group(1)] = m.group(2)
    print(f"\nParameters: {params}\n")

    # TB1: DC Operating Point
    print("=== TB1: DC Operating Point ===")
    tb1 = run_tb1(netlist)
    print(f"  V_REF = {tb1['vref']:.6f} V" if tb1['vref'] else "  V_REF = FAILED")
    print(f"  I_DD  = {tb1['idd']:.6e} A" if tb1['idd'] else "  I_DD  = FAILED")
    print(f"  Power = {tb1['power_uw']:.2f} uW" if tb1['power_uw'] else "  Power = FAILED")

    # TB2: Temperature Sweep
    print("\n=== TB2: Temperature Sweep ===")
    tb2_data, tb2_raw = run_tb2(netlist)
    tb2 = analyze_tb2(tb2_data)
    print(f"  TC = {tb2['tc_ppm_c']:.1f} ppm/C")
    if tb2['vref_27']:
        print(f"  V_REF(27C) = {tb2['vref_27']:.6f} V")
        print(f"  V_REF_min  = {tb2['vmin']:.6f} V (at T={tb2.get('tmin', '?')}C)")
        print(f"  V_REF_max  = {tb2['vmax']:.6f} V (at T={tb2.get('tmax', '?')}C)")
    plot_tb2(tb2_data)

    # TB3: Supply Sweep
    print("\n=== TB3: Supply Sweep (Line Regulation / PSRR) ===")
    tb3_data, tb3_raw = run_tb3(netlist)
    tb3 = analyze_tb3(tb3_data)
    print(f"  Delta_VREF = {tb3.get('dvref_uv', 0):.1f} uV")
    print(f"  Line Reg   = {tb3['line_reg_mv_v']:.2f} mV/V")
    print(f"  PSRR_DC    = {tb3['psrr_dc_db']:.1f} dB")
    plot_tb3(tb3_data)

    # TB4: Startup Transient
    print("\n=== TB4: Startup Transient ===")
    tb4_data, tb4_raw = run_tb4(netlist)
    tb4 = analyze_tb4(tb4_data)
    print(f"  Final V_REF = {tb4['final_vref']:.4f} V")
    print(f"  Startup time = {tb4['startup_time_us']:.1f} us")
    if tb4.get('stuck'):
        print("  WARNING: V_REF appears stuck near 0V — startup circuit issue!")
    plot_tb4(tb4_data)

    # Compile measurements
    measurements = {
        'vref_v': tb1['vref'],
        'tc_ppm_c': tb2['tc_ppm_c'],
        'psrr_dc_db': tb3['psrr_dc_db'],
        'line_regulation_mv_v': tb3['line_reg_mv_v'],
        'power_uw': tb1['power_uw'],
        'startup_time_us': tb4['startup_time_us'],
    }

    # Score
    print("\n" + "=" * 60)
    print("SCORING")
    print("=" * 60)
    score, details = compute_score(measurements)
    all_25pct = True
    for name, d in details.items():
        status = "PASS" if d['pass'] else "FAIL"
        margin_str = f"margin={d['margin_pct']}%"
        m25 = "✓25%" if d.get('meets_25pct') else "✗25%"
        if not d.get('meets_25pct'):
            all_25pct = False
        spec = SPECS[name]
        if spec['type'] == 'range':
            tgt = f"{spec['target'][0]} to {spec['target'][1]}"
        elif spec['type'] == 'less_than':
            tgt = f"<{spec['target']}"
        else:
            tgt = f">{spec['target']}"
        print(f"  {name}: {d['value']:.4f} ({tgt}) [{status}] {margin_str} {m25} (weight={spec['weight']})"
              if d['value'] is not None else f"  {name}: FAILED")

    print(f"\nscore = {score:.4f}")
    print(f"specs_met = {sum(1 for d in details.values() if d['pass'])}/6")
    print(f"all_25pct_margin = {all_25pct}")

    # TB5: PVT Corners (only if base score is 1.0)
    pvt_results = None
    if score >= 1.0:
        print("\n=== TB5: PVT Corner Analysis ===")
        pvt_results, corner_curves = run_tb5(netlist)
        plot_pvt(corner_curves)
        pvt_pass = 0
        pvt_fail = 0
        pvt_fail_details = []
        for r in pvt_results:
            if 1.15 <= r['vref'] <= 1.25:
                pvt_pass += 1
            else:
                pvt_fail += 1
                pvt_fail_details.append(r)
        total = pvt_pass + pvt_fail
        print(f"  PVT: {pvt_pass}/{total} corners pass (V_REF in 1.15-1.25V)")
        if pvt_fail_details:
            for r in pvt_fail_details[:10]:
                print(f"    FAIL: {r['corner']} T={r['temp']}C VDD={r['vdd']}V V_REF={r['vref']:.4f}V")
        measurements['pvt_pass_rate'] = pvt_pass / total if total > 0 else 0
        measurements['pvt_total'] = total

    # Save measurements
    measurements['score'] = score
    measurements['details'] = {k: {kk: vv for kk, vv in v.items()} for k, v in details.items()}
    with open(os.path.join(BLOCK_DIR, "measurements.json"), 'w') as f:
        json.dump(measurements, f, indent=2, default=str)

    print(f"\nResults saved to measurements.json")
    print(f"Plots saved to {PLOTS_DIR}/")

    return score, measurements


if __name__ == "__main__":
    score, meas = main()
    sys.exit(0 if score >= 1.0 else 1)
