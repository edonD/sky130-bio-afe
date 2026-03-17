#!/usr/bin/env python3
"""PVT Corner Analysis for Bandgap Reference (TB5)"""
import subprocess, os, re, json
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

BLOCK_DIR = os.path.dirname(os.path.abspath(__file__))
SKY130_DIR = os.path.join(BLOCK_DIR, "sky130_models")
PLOT_DIR = os.path.join(BLOCK_DIR, "plots")

CORNERS = ['tt', 'ss', 'ff', 'sf', 'fs']
TEMPS = [-40, 27, 125]
SUPPLIES = [1.62, 1.80, 1.98]


def run_pvt_point(corner, temp, vdd):
    """Run a single PVT point and return V_REF."""
    with open(os.path.join(BLOCK_DIR, "design.cir")) as f:
        netlist = f.read()

    # Read params from CSV and override
    params = {}
    with open(os.path.join(BLOCK_DIR, "parameters.csv")) as f:
        f.readline()
        for line in f:
            parts = line.strip().split(",")
            if len(parts) >= 5:
                params[parts[0]] = parts[4]

    for pname, pval in params.items():
        netlist = re.sub(rf'(\.param\s+{pname}\s*=\s*)[\S]+', rf'\g<1>{pval}', netlist)

    # Replace corner
    netlist = re.sub(r'\.lib\s+"sky130_models/sky130\.lib\.spice"\s+\w+',
                     f'.lib "sky130_models/sky130.lib.spice" {corner}', netlist)

    # Replace VDD
    netlist = re.sub(r'VDD vdd 0 DC [\d.]+', f'VDD vdd 0 DC {vdd}', netlist)

    # Replace .control block with temp-specific OP
    ctrl = f""".control
option temp={temp}
op
print v(vref)
let idd = -@VDD[i]
print idd
quit
.endc"""
    netlist = re.sub(r'\.control.*?\.endc', ctrl, netlist, flags=re.DOTALL)

    nf = os.path.join(BLOCK_DIR, f"pvt_{corner}_{temp}_{vdd:.2f}.cir")
    with open(nf, 'w') as f:
        f.write(netlist)

    try:
        result = subprocess.run(
            ["ngspice", "-b", nf],
            capture_output=True, text=True, timeout=60, cwd=SKY130_DIR
        )
        out = result.stdout + "\n" + result.stderr

        vref = None
        for line in out.split('\n'):
            if 'v(vref)' in line and '=' in line:
                m = re.search(r'=\s*([\d.eE+\-]+)', line)
                if m:
                    vref = float(m.group(1))
        return vref
    except Exception as e:
        print(f"  ERROR: {corner}/{temp}C/{vdd}V: {e}")
        return None
    finally:
        if os.path.exists(nf):
            os.remove(nf)


def main():
    print("=" * 60)
    print("TB5: PVT CORNER ANALYSIS")
    print("=" * 60)

    results = []
    all_pass = True

    for corner in CORNERS:
        for temp in TEMPS:
            for vdd in SUPPLIES:
                vref = run_pvt_point(corner, temp, vdd)
                passed = vref is not None and 1.15 <= vref <= 1.25
                if not passed:
                    all_pass = False
                status = "PASS" if passed else "FAIL"
                results.append({
                    'corner': corner, 'temp': temp, 'vdd': vdd,
                    'vref': vref, 'status': status
                })
                vref_str = f"{vref:.4f}V" if vref else "None"
                print(f"  {corner:2s} T={temp:4d}C VDD={vdd:.2f}V  V_REF={vref_str}  [{status}]")

    # Summary
    n_pass = sum(1 for r in results if r['status'] == 'PASS')
    n_total = len(results)
    print(f"\nPVT Summary: {n_pass}/{n_total} corners pass")
    print(f"Overall: {'PASS' if all_pass else 'FAIL'}")

    # Plot: V_REF vs Temperature for each corner (at VDD=1.8V)
    plt.figure(figsize=(10, 6))
    for corner in CORNERS:
        temps_c = []
        vrefs_c = []
        for r in results:
            if r['corner'] == corner and r['vdd'] == 1.80 and r['vref'] is not None:
                temps_c.append(r['temp'])
                vrefs_c.append(r['vref'] * 1000)
        if temps_c:
            plt.plot(temps_c, vrefs_c, 'o-', label=corner, markersize=8)

    plt.xlabel('Temperature (°C)')
    plt.ylabel('V_REF (mV)')
    plt.title(f'PVT Corner Analysis ({n_pass}/{n_total} pass)')
    plt.axhline(y=1150, color='r', linestyle='--', alpha=0.5, label='Spec limits')
    plt.axhline(y=1250, color='r', linestyle='--', alpha=0.5)
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(os.path.join(PLOT_DIR, 'pvt_corners.png'), dpi=150)
    plt.close()

    # Save results
    with open(os.path.join(BLOCK_DIR, "pvt_results.json"), 'w') as f:
        json.dump(results, f, indent=2, default=str)

    return all_pass


if __name__ == "__main__":
    main()
