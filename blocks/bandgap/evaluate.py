#!/usr/bin/env python3
"""
Bandgap Voltage Reference Evaluator
Runs TB1-TB4 (DC, temp sweep, supply sweep, startup transient).
Measures all specs from specs.json. Generates plots. Reports score.
"""

import subprocess
import os
import re
import json
import sys
import numpy as np

PLOT_DIR = "plots"
os.makedirs(PLOT_DIR, exist_ok=True)

# Try to import matplotlib; fall back to non-interactive backend
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def read_params_from_csv(fname="parameters.csv"):
    """Read current parameter values from CSV."""
    params = {}
    with open(fname) as f:
        header = f.readline()
        for line in f:
            parts = line.strip().split(",")
            if len(parts) >= 5:
                params[parts[0]] = parts[4]
    return params


def write_netlist(template_file, output_file, params, extra_commands=""):
    """Read design.cir, substitute parameters, replace .control block."""
    with open(template_file) as f:
        netlist = f.read()

    # Override parameter values
    for pname, pval in params.items():
        # Replace .param lines
        netlist = re.sub(
            rf'(\.param\s+{pname}\s*=\s*)[\S]+',
            rf'\g<1>{pval}',
            netlist
        )

    # Replace the .control ... .endc block
    netlist = re.sub(
        r'\.control.*?\.endc',
        extra_commands,
        netlist,
        flags=re.DOTALL
    )

    with open(output_file, 'w') as f:
        f.write(netlist)
    return output_file


def run_ngspice(netlist_file, timeout=120):
    """Run ngspice and return stdout+stderr."""
    result = subprocess.run(
        ["ngspice", "-b", netlist_file],
        capture_output=True, text=True, timeout=timeout,
        cwd=os.path.dirname(os.path.abspath(__file__)) or "."
    )
    return result.stdout + "\n" + result.stderr


def parse_wrdata(filename):
    """Parse ngspice wrdata output file. Returns (x_array, y_array)."""
    x, y = [], []
    if not os.path.exists(filename):
        return np.array([]), np.array([])
    with open(filename) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or line.startswith('*'):
                continue
            parts = line.split()
            if len(parts) >= 2:
                try:
                    x.append(float(parts[0]))
                    y.append(float(parts[1]))
                except ValueError:
                    continue
    return np.array(x), np.array(y)


def tb1_dc_operating_point(params):
    """TB1: DC operating point at TT/27C/1.8V."""
    print("\n=== TB1: DC Operating Point ===")

    ctrl = """.control
set wr_vecnames
op
let vref_val = v(vref)
let idd = -@VDD[i]
let power_uw = idd * 1.8 * 1e6
print vref_val idd power_uw
print v(nb1) v(nb2) v(e1) v(e2) v(mid2)
quit
.endc"""

    nf = write_netlist("design.cir", "tb1_dc.cir", params, ctrl)
    out = run_ngspice(nf)

    # Parse results
    vref = None
    power = None
    idd = None

    for line in out.split('\n'):
        if 'vref_val' in line and '=' in line:
            m = re.search(r'=\s*([\d.eE+\-]+)', line)
            if m:
                vref = float(m.group(1))
        if 'power_uw' in line and '=' in line:
            m = re.search(r'=\s*([\d.eE+\-]+)', line)
            if m:
                power = float(m.group(1))
        if 'idd' in line and '=' in line and 'power' not in line:
            m = re.search(r'=\s*([\d.eE+\-]+)', line)
            if m:
                idd = float(m.group(1))

    print(f"  V_REF = {vref} V")
    print(f"  I_DD  = {idd} A")
    print(f"  Power = {power} uW")

    return {"vref_dc": vref, "power_uw": power, "idd": idd}


def tb2_temperature_sweep(params):
    """TB2: Temperature sweep -40C to 125C."""
    print("\n=== TB2: Temperature Sweep ===")

    ctrl = """.control
dc temp -40 125 1
wrdata temp_sweep v(vref)
quit
.endc"""

    nf = write_netlist("design.cir", "tb2_temp.cir", params, ctrl)
    out = run_ngspice(nf)

    temp, vref = parse_wrdata("temp_sweep")

    if len(vref) < 10:
        print("  ERROR: Temperature sweep produced insufficient data")
        return {"tc_ppm_c": 9999, "vref_min_temp": None, "vref_max_temp": None}

    vref_nom = vref[np.argmin(np.abs(temp - 27))]
    vref_min = np.min(vref)
    vref_max = np.max(vref)
    delta_t = 165.0  # -40 to 125

    tc_ppm = (vref_max - vref_min) / (vref_nom * delta_t) * 1e6

    print(f"  V_REF(27C) = {vref_nom:.6f} V")
    print(f"  V_REF_min  = {vref_min:.6f} V (at T={temp[np.argmin(vref)]:.0f}C)")
    print(f"  V_REF_max  = {vref_max:.6f} V (at T={temp[np.argmax(vref)]:.0f}C)")
    print(f"  TC = {tc_ppm:.1f} ppm/C")

    # Plot
    plt.figure(figsize=(8, 5))
    plt.plot(temp, vref * 1000, 'b-', linewidth=2)
    plt.xlabel('Temperature (°C)')
    plt.ylabel('V_REF (mV)')
    plt.title(f'Bandgap V_REF vs Temperature (TC = {tc_ppm:.1f} ppm/°C)')
    plt.grid(True, alpha=0.3)
    plt.axhline(y=1150, color='r', linestyle='--', alpha=0.5, label='Spec min (1.15V)')
    plt.axhline(y=1250, color='r', linestyle='--', alpha=0.5, label='Spec max (1.25V)')
    plt.legend()
    plt.tight_layout()
    plt.savefig(f'{PLOT_DIR}/vref_vs_temperature.png', dpi=150)
    plt.close()

    return {
        "tc_ppm_c": tc_ppm,
        "vref_nom": vref_nom,
        "vref_min_temp": vref_min,
        "vref_max_temp": vref_max
    }


def tb3_supply_sweep(params):
    """TB3: Supply sweep 1.62V to 1.98V for line regulation and PSRR."""
    print("\n=== TB3: Supply Sweep (Line Regulation / PSRR) ===")

    # Need to modify netlist to make VDD a parameter we can sweep
    ctrl = """.control
dc VDD 1.62 1.98 0.01
wrdata supply_sweep v(vref)
quit
.endc"""

    nf = write_netlist("design.cir", "tb3_supply.cir", params, ctrl)
    out = run_ngspice(nf)

    vdd_arr, vref = parse_wrdata("supply_sweep")

    if len(vref) < 5:
        print("  ERROR: Supply sweep produced insufficient data")
        return {"line_reg_mv_v": 9999, "psrr_dc_db": 0}

    # Line regulation: delta_vref / delta_vdd in mV/V
    delta_vdd = vdd_arr[-1] - vdd_arr[0]
    delta_vref = vref[-1] - vref[0]
    line_reg = abs(delta_vref / delta_vdd) * 1000  # mV/V

    # PSRR = 20*log10(delta_VDD / delta_VREF)
    if abs(delta_vref) > 1e-15:
        psrr_db = 20 * np.log10(abs(delta_vdd / delta_vref))
    else:
        psrr_db = 120  # Suspiciously good, cap it

    print(f"  Delta_VDD  = {delta_vdd*1000:.1f} mV")
    print(f"  Delta_VREF = {delta_vref*1e6:.1f} uV")
    print(f"  Line Reg   = {line_reg:.2f} mV/V")
    print(f"  PSRR_DC    = {psrr_db:.1f} dB")

    # Plot
    plt.figure(figsize=(8, 5))
    plt.plot(vdd_arr, vref * 1000, 'b-', linewidth=2)
    plt.xlabel('VDD (V)')
    plt.ylabel('V_REF (mV)')
    plt.title(f'V_REF vs Supply (Line Reg = {line_reg:.2f} mV/V, PSRR = {psrr_db:.1f} dB)')
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(f'{PLOT_DIR}/vref_vs_supply.png', dpi=150)
    plt.close()

    return {"line_reg_mv_v": line_reg, "psrr_dc_db": psrr_db}


def tb4_startup_transient(params):
    """TB4: Startup transient — ramp VDD 0->1.8V in 10us, monitor settling."""
    print("\n=== TB4: Startup Transient ===")

    # Need to replace DC VDD source with a PWL ramp
    with open("design.cir") as f:
        netlist = f.read()

    # Override parameters
    for pname, pval in params.items():
        netlist = re.sub(
            rf'(\.param\s+{pname}\s*=\s*)[\S]+',
            rf'\g<1>{pval}',
            netlist
        )

    # Replace VDD source with PWL ramp
    netlist = netlist.replace(
        "VDD vdd 0 DC 1.8",
        "VDD vdd 0 PWL(0 0 10u 1.8 200u 1.8)"
    )

    # Replace .control block
    ctrl = """.control
tran 0.1u 200u
wrdata startup_tran v(vref) v(vdd)
quit
.endc"""

    netlist = re.sub(r'\.control.*?\.endc', ctrl, netlist, flags=re.DOTALL)

    with open("tb4_startup.cir", 'w') as f:
        f.write(netlist)

    out = run_ngspice("tb4_startup.cir")

    time_arr, vref = parse_wrdata("startup_tran")

    if len(vref) < 10:
        print("  ERROR: Startup transient produced insufficient data")
        return {"startup_time_us": 9999}

    # The wrdata may have interleaved columns; parse both
    # Actually wrdata with two signals writes: time v1 time v2 on alternating lines
    # Let's re-parse more carefully
    data = []
    if os.path.exists("startup_tran"):
        with open("startup_tran") as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) >= 2:
                    try:
                        data.append([float(p) for p in parts])
                    except ValueError:
                        continue

    if not data:
        print("  ERROR: Could not parse startup data")
        return {"startup_time_us": 9999}

    data = np.array(data)
    # wrdata with 2 vectors: columns are time, v(vref), v(vdd)
    if data.shape[1] >= 3:
        time_arr = data[:, 0]
        vref = data[:, 1]
        vdd_t = data[:, 2]
    else:
        time_arr = data[:, 0]
        vref = data[:, 1]
        vdd_t = None

    # Find final vref value (last 10% of simulation)
    final_vref = np.mean(vref[-len(vref)//10:])

    # Find when vref first reaches within 1% of final value and stays
    threshold = 0.01 * abs(final_vref)
    settled = np.abs(vref - final_vref) < threshold

    startup_time_us = 9999
    if np.any(settled):
        # Find first time it stays settled (check it doesn't leave)
        for i in range(len(settled)):
            if settled[i] and np.all(settled[i:min(i+50, len(settled))]):
                startup_time_us = time_arr[i] * 1e6  # Convert to us
                break

    print(f"  Final V_REF = {final_vref:.4f} V")
    print(f"  Startup time = {startup_time_us:.1f} us")

    # Plot
    fig, ax1 = plt.subplots(figsize=(8, 5))
    ax1.plot(time_arr * 1e6, vref, 'b-', linewidth=2, label='V_REF')
    if vdd_t is not None:
        ax2 = ax1.twinx()
        ax2.plot(time_arr * 1e6, vdd_t, 'r--', linewidth=1, alpha=0.5, label='VDD')
        ax2.set_ylabel('VDD (V)', color='r')
        ax2.legend(loc='upper right')
    ax1.set_xlabel('Time (µs)')
    ax1.set_ylabel('V_REF (V)', color='b')
    ax1.set_title(f'Startup Transient (settling = {startup_time_us:.1f} µs)')
    ax1.grid(True, alpha=0.3)
    ax1.axhline(y=final_vref * 0.99, color='g', linestyle=':', alpha=0.5, label='99% settled')
    ax1.axhline(y=final_vref * 1.01, color='g', linestyle=':', alpha=0.5)
    ax1.legend(loc='lower right')
    plt.tight_layout()
    plt.savefig(f'{PLOT_DIR}/startup_transient.png', dpi=150)
    plt.close()

    return {"startup_time_us": startup_time_us}


def compute_score(measurements):
    """Compute weighted score based on specs.json."""
    with open("specs.json") as f:
        specs = json.load(f)

    total_weight = 0
    earned_weight = 0
    results = {}

    spec_map = {
        "vref_v": ("vref_dc", lambda v: 1.15 <= v <= 1.25 if v is not None else False),
        "tc_ppm_c": ("tc_ppm_c", lambda v: v < 50 if v is not None else False),
        "psrr_dc_db": ("psrr_dc_db", lambda v: v > 60 if v is not None else False),
        "line_regulation_mv_v": ("line_reg_mv_v", lambda v: v < 5 if v is not None else False),
        "power_uw": ("power_uw", lambda v: v is not None and 0 < v < 20),
        "startup_time_us": ("startup_time_us", lambda v: v < 100 if v is not None else False),
    }

    for spec_name, spec_info in specs["measurements"].items():
        weight = spec_info["weight"]
        total_weight += weight

        meas_key, check_fn = spec_map[spec_name]
        meas_val = measurements.get(meas_key)
        passed = check_fn(meas_val)

        if passed:
            earned_weight += weight

        status = "PASS" if passed else "FAIL"
        results[spec_name] = {
            "measured": meas_val,
            "target": spec_info["target"],
            "weight": weight,
            "status": status
        }
        print(f"  {spec_name}: {meas_val} ({spec_info['target']}) [{status}] (weight={weight})")

    score = earned_weight / total_weight if total_weight > 0 else 0
    return score, results


def main():
    print("=" * 60)
    print("BANDGAP VOLTAGE REFERENCE EVALUATION")
    print("=" * 60)

    # Read parameters
    params = read_params_from_csv()
    print(f"\nParameters: {params}")

    # Run all testbenches
    measurements = {}

    tb1 = tb1_dc_operating_point(params)
    measurements.update(tb1)

    tb2 = tb2_temperature_sweep(params)
    measurements.update(tb2)

    tb3 = tb3_supply_sweep(params)
    measurements.update(tb3)

    tb4 = tb4_startup_transient(params)
    measurements.update(tb4)

    # Compute score
    print("\n" + "=" * 60)
    print("SCORING")
    print("=" * 60)
    score, results = compute_score(measurements)

    specs_met = sum(1 for r in results.values() if r["status"] == "PASS")
    total_specs = len(results)

    print(f"\nscore = {score:.4f}")
    print(f"specs_met = {specs_met}/{total_specs}")

    # Save measurements
    measurements["score"] = score
    measurements["specs_met"] = f"{specs_met}/{total_specs}"
    with open("measurements.json", 'w') as f:
        json.dump(measurements, f, indent=2, default=str)

    print(f"\nResults saved to measurements.json")
    print(f"Plots saved to {PLOT_DIR}/")

    # Clean up temp files
    for f in ["tb1_dc.cir", "tb2_temp.cir", "tb3_supply.cir", "tb4_startup.cir",
              "temp_sweep", "supply_sweep", "startup_tran"]:
        pass  # Keep for debugging

    return score


if __name__ == "__main__":
    score = main()
    sys.exit(0 if score > 0 else 1)
