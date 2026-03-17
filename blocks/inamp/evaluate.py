#!/usr/bin/env python3
"""
SKY130 Instrumentation Amplifier — Evaluator
Runs all testbenches, extracts measurements, scores against specs.
"""

import subprocess
import os
import sys
import json
import math
import re
import numpy as np

# Work from the script's directory
os.chdir(os.path.dirname(os.path.abspath(__file__)))

DESIGN_FILE = "design.cir"
SPECS_FILE = "specs.json"
MEASUREMENTS_FILE = "measurements.json"
PLOTS_DIR = "plots"
NGSPICE = "ngspice"

# Ensure plots directory exists
os.makedirs(PLOTS_DIR, exist_ok=True)

# Load specs
with open(SPECS_FILE) as f:
    specs = json.load(f)


def run_ngspice(netlist_str, timeout=120):
    """Run an ngspice simulation and return stdout."""
    tmpfile = "/tmp/inamp_tb.cir"
    with open(tmpfile, "w") as f:
        f.write(netlist_str)
    try:
        result = subprocess.run(
            [NGSPICE, "-b", tmpfile],
            capture_output=True, text=True, timeout=timeout
        )
        return result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        return "ERROR: Simulation timed out"


def read_design_params():
    """Read the design.cir and extract .param lines for reuse."""
    with open(DESIGN_FILE) as f:
        content = f.read()
    # Extract everything up to .end
    lines = []
    for line in content.split('\n'):
        if line.strip().lower() == '.end':
            break
        lines.append(line)
    return '\n'.join(lines)


def get_lib_and_params():
    """Get the .lib statement and parameters from design.cir."""
    design_header = read_design_params()
    return design_header


def parse_measurement(output, name):
    """Parse a measurement value from ngspice output."""
    # Look for: name = value
    pattern = rf'{name}\s*=\s*([-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?)'
    match = re.search(pattern, output)
    if match:
        return float(match.group(1))
    return None


def tb1_dc_gain():
    """TB1: DC Gain and Operating Point"""
    print("\n" + "="*60)
    print("TB1: DC Gain and Operating Point")
    print("="*60)

    netlist = f"""* TB1: DC Gain Test
.lib "/home/ubuntu/workspace/sky130_models/sky130.lib.spice" tt

.param vdd_val = 1.8
.param vcm_val = 0.9
.param ibias_val = 2u
.param wp_in = 50u
.param lp_in = 2u
.param wn_load = 5u
.param ln_load = 2u
.param wp_tail = 10u
.param lp_tail = 2u
.param wp_cas = 5u
.param lp_cas = 1u
.param wn_cas = 5u
.param ln_cas = 1u
.param cin_val = 10p
.param cfb_val = 200f
.param rpseudo = 100G

VDD vdd 0 {{vdd_val}}

* Bias
Ibias vdd nbias {{ibias_val}}
Xbias_n nbias nbias 0 0 sky130_fd_pr__nfet_01v8 w={{wn_load}} l={{ln_load}}

* Differential input: 0.5mV differential on 0.9V common-mode
Vinp inp 0 DC 0.9005
Vinn inn 0 DC 0.8995

* Input coupling
Cin_p inp inn_p {{cin_val}}
Cin_n inn inn_n {{cin_val}}

* DC bias
Rbias_p vcm_node inn_p {{rpseudo}}
Rbias_n vcm_node inn_n {{rpseudo}}
Vcm_bias vcm_node 0 {{vcm_val}}

* Feedback caps
Cfb_p outp inn_p {{cfb_val}}
Cfb_n outn inn_n {{cfb_val}}

* PMOS tail
Xp_tail_bias ptail_bias ptail_bias vdd vdd sky130_fd_pr__pfet_01v8 w={{wp_tail}} l={{lp_tail}}
Ip_tail_ref vdd ptail_bias {{ibias_val*2}}
Xp_tail tail ptail_bias vdd vdd sky130_fd_pr__pfet_01v8 w={{wp_tail}} l={{lp_tail}}

* Input pair
Xp_in1 pd1 inn_n tail vdd sky130_fd_pr__pfet_01v8 w={{wp_in}} l={{lp_in}}
Xp_in2 pd2 inn_p tail vdd sky130_fd_pr__pfet_01v8 w={{wp_in}} l={{lp_in}}

* NMOS loads
Xn_load1 nd1 nbias 0 0 sky130_fd_pr__nfet_01v8 w={{wn_load}} l={{ln_load}}
Xn_load2 nd2 nbias 0 0 sky130_fd_pr__nfet_01v8 w={{wn_load}} l={{ln_load}}

* Cascodes
Xn_cas1 outn ncas_bias nd1 0 sky130_fd_pr__nfet_01v8 w={{wn_cas}} l={{ln_cas}}
Xn_cas2 outp ncas_bias nd2 0 sky130_fd_pr__nfet_01v8 w={{wn_cas}} l={{ln_cas}}
Xp_cas1 outn pcas_bias pd1 vdd sky130_fd_pr__pfet_01v8 w={{wp_cas}} l={{lp_cas}}
Xp_cas2 outp pcas_bias pd2 vdd sky130_fd_pr__pfet_01v8 w={{wp_cas}} l={{lp_cas}}

Vncas ncas_bias 0 0.7
Vpcas pcas_bias 0 1.0

* CMFB (simplified)
Ecmfb vcm_sense 0 vol='(v(outp)+v(outn))/2'
Gcmfb outp outn vcm_sense vcm_node 10u

CL_p outp 0 1p
CL_n outn 0 1p

* --- Transient to let caps charge ---
.tran 1m 2 uic

.control
run

* Measure final voltages
let vout_diff = v(outp) - v(outn)
let vout_p = v(outp)
let vout_n = v(outn)
let vcm_out = (v(outp) + v(outn))/2

* Take values at end of simulation
let final_vout_diff = vout_diff[length(vout_diff)-1]
let final_voutp = vout_p[length(vout_p)-1]
let final_voutn = vout_n[length(vout_n)-1]
let final_vcm = vcm_out[length(vcm_out)-1]

print final_vout_diff final_voutp final_voutn final_vcm

* Save plot
set gnuplot_terminal=png
gnuplot {PLOTS_DIR}/dc_gain vout_diff title "Differential Output vs Time" ylabel "Voltage (V)" xlabel "Time (s)"

quit
.endc
.end
"""
    output = run_ngspice(netlist)
    print(output[-2000:] if len(output) > 2000 else output)

    vout_diff = parse_measurement(output, "final_vout_diff")
    voutp = parse_measurement(output, "final_voutp")
    voutn = parse_measurement(output, "final_voutn")
    vcm_out = parse_measurement(output, "final_vcm")

    if vout_diff is not None:
        vin_diff = 0.001  # 1 mV
        gain = abs(vout_diff) / vin_diff
        gain_db = 20 * math.log10(max(gain, 1e-10))
        print(f"  Vout_diff = {vout_diff*1000:.3f} mV")
        print(f"  Gain = {gain:.1f} V/V = {gain_db:.1f} dB")
        print(f"  Voutp = {voutp:.4f} V, Voutn = {voutn:.4f} V")
        print(f"  Output CM = {vcm_out:.4f} V")

        # Check output not railed
        if voutp is not None and voutn is not None:
            if voutp < 0.2 or voutp > 1.6 or voutn < 0.2 or voutn > 1.6:
                print("  WARNING: Output may be railed!")

        return {"gain_vv": gain, "gain_db": gain_db, "voutp": voutp, "voutn": voutn, "vcm_out": vcm_out}
    else:
        print("  ERROR: Could not parse output")
        return None


def tb2_ac_response():
    """TB2: AC Frequency Response"""
    print("\n" + "="*60)
    print("TB2: AC Frequency Response")
    print("="*60)

    netlist = f"""* TB2: AC Response
.lib "/home/ubuntu/workspace/sky130_models/sky130.lib.spice" tt

.param vdd_val = 1.8
.param vcm_val = 0.9
.param ibias_val = 2u
.param wp_in = 50u
.param lp_in = 2u
.param wn_load = 5u
.param ln_load = 2u
.param wp_tail = 10u
.param lp_tail = 2u
.param wp_cas = 5u
.param lp_cas = 1u
.param wn_cas = 5u
.param ln_cas = 1u
.param cin_val = 10p
.param cfb_val = 200f
.param rpseudo = 100G

VDD vdd 0 {{vdd_val}}

Ibias vdd nbias {{ibias_val}}
Xbias_n nbias nbias 0 0 sky130_fd_pr__nfet_01v8 w={{wn_load}} l={{ln_load}}

* AC differential input
Vinp inp 0 DC 0.9 AC 0.5
Vinn inn 0 DC 0.9 AC -0.5

Cin_p inp inn_p {{cin_val}}
Cin_n inn inn_n {{cin_val}}

Rbias_p vcm_node inn_p {{rpseudo}}
Rbias_n vcm_node inn_n {{rpseudo}}
Vcm_bias vcm_node 0 {{vcm_val}}

Cfb_p outp inn_p {{cfb_val}}
Cfb_n outn inn_n {{cfb_val}}

Xp_tail_bias ptail_bias ptail_bias vdd vdd sky130_fd_pr__pfet_01v8 w={{wp_tail}} l={{lp_tail}}
Ip_tail_ref vdd ptail_bias {{ibias_val*2}}
Xp_tail tail ptail_bias vdd vdd sky130_fd_pr__pfet_01v8 w={{wp_tail}} l={{lp_tail}}

Xp_in1 pd1 inn_n tail vdd sky130_fd_pr__pfet_01v8 w={{wp_in}} l={{lp_in}}
Xp_in2 pd2 inn_p tail vdd sky130_fd_pr__pfet_01v8 w={{wp_in}} l={{lp_in}}

Xn_load1 nd1 nbias 0 0 sky130_fd_pr__nfet_01v8 w={{wn_load}} l={{ln_load}}
Xn_load2 nd2 nbias 0 0 sky130_fd_pr__nfet_01v8 w={{wn_load}} l={{ln_load}}

Xn_cas1 outn ncas_bias nd1 0 sky130_fd_pr__nfet_01v8 w={{wn_cas}} l={{ln_cas}}
Xn_cas2 outp ncas_bias nd2 0 sky130_fd_pr__nfet_01v8 w={{wn_cas}} l={{ln_cas}}
Xp_cas1 outn pcas_bias pd1 vdd sky130_fd_pr__pfet_01v8 w={{wp_cas}} l={{lp_cas}}
Xp_cas2 outp pcas_bias pd2 vdd sky130_fd_pr__pfet_01v8 w={{wp_cas}} l={{lp_cas}}

Vncas ncas_bias 0 0.7
Vpcas pcas_bias 0 1.0

Ecmfb vcm_sense 0 vol='(v(outp)+v(outn))/2'
Gcmfb outp outn vcm_sense vcm_node 10u

CL_p outp 0 1p
CL_n outn 0 1p

.ac dec 50 0.1 10Meg

.control
run

let vout_diff_mag = vm(outp) - vm(outn)
let gain_db = db(v(outp) - v(outn))
let phase_deg = 180/PI * (ph(v(outp)) - ph(v(outn)))

* Find gain at key frequencies
meas ac gain_1hz find vdb(outp)-vdb(outn) at=1
meas ac gain_60hz find vdb(outp)-vdb(outn) at=60
meas ac gain_150hz find vdb(outp)-vdb(outn) at=150

* Find -3dB bandwidth
let diff_out = v(outp) - v(outn)
meas ac midband_gain max vdb(diff_out) from=1 to=1k
meas ac bw_3db when vdb(diff_out)=(midband_gain-3) fall=1

set gnuplot_terminal=png
gnuplot {PLOTS_DIR}/ac_response gain_db title "Differential Gain (dB) vs Frequency" ylabel "Gain (dB)" xlabel "Frequency (Hz)"

print gain_1hz gain_60hz gain_150hz midband_gain bw_3db
quit
.endc
.end
"""
    output = run_ngspice(netlist)
    print(output[-2000:] if len(output) > 2000 else output)

    midband_gain = parse_measurement(output, "midband_gain")
    bw = parse_measurement(output, "bw_3db")
    gain_60 = parse_measurement(output, "gain_60hz")

    results = {}
    if midband_gain is not None:
        print(f"  Midband gain = {midband_gain:.1f} dB")
        results["midband_gain_db"] = midband_gain
    if bw is not None:
        print(f"  -3dB Bandwidth = {bw:.0f} Hz")
        results["bandwidth_hz"] = bw
    if gain_60 is not None:
        print(f"  Gain at 60 Hz = {gain_60:.1f} dB")
        results["gain_60hz_db"] = gain_60

    return results if results else None


def tb3_cmrr():
    """TB3: Common-Mode Rejection"""
    print("\n" + "="*60)
    print("TB3: Common-Mode Rejection Ratio")
    print("="*60)

    # First get differential gain, then common-mode gain
    netlist_cm = f"""* TB3: CMRR - Common-mode response
.lib "/home/ubuntu/workspace/sky130_models/sky130.lib.spice" tt

.param vdd_val = 1.8
.param vcm_val = 0.9
.param ibias_val = 2u
.param wp_in = 50u
.param lp_in = 2u
.param wn_load = 5u
.param ln_load = 2u
.param wp_tail = 10u
.param lp_tail = 2u
.param wp_cas = 5u
.param lp_cas = 1u
.param wn_cas = 5u
.param ln_cas = 1u
.param cin_val = 10p
.param cfb_val = 200f
.param rpseudo = 100G

VDD vdd 0 {{vdd_val}}

Ibias vdd nbias {{ibias_val}}
Xbias_n nbias nbias 0 0 sky130_fd_pr__nfet_01v8 w={{wn_load}} l={{ln_load}}

* Common-mode AC input (same signal on both inputs)
Vinp inp 0 DC 0.9 AC 1
Vinn inn 0 DC 0.9 AC 1

Cin_p inp inn_p {{cin_val}}
Cin_n inn inn_n {{cin_val}}

Rbias_p vcm_node inn_p {{rpseudo}}
Rbias_n vcm_node inn_n {{rpseudo}}
Vcm_bias vcm_node 0 {{vcm_val}}

Cfb_p outp inn_p {{cfb_val}}
Cfb_n outn inn_n {{cfb_val}}

Xp_tail_bias ptail_bias ptail_bias vdd vdd sky130_fd_pr__pfet_01v8 w={{wp_tail}} l={{lp_tail}}
Ip_tail_ref vdd ptail_bias {{ibias_val*2}}
Xp_tail tail ptail_bias vdd vdd sky130_fd_pr__pfet_01v8 w={{wp_tail}} l={{lp_tail}}

Xp_in1 pd1 inn_n tail vdd sky130_fd_pr__pfet_01v8 w={{wp_in}} l={{lp_in}}
Xp_in2 pd2 inn_p tail vdd sky130_fd_pr__pfet_01v8 w={{wp_in}} l={{lp_in}}

Xn_load1 nd1 nbias 0 0 sky130_fd_pr__nfet_01v8 w={{wn_load}} l={{ln_load}}
Xn_load2 nd2 nbias 0 0 sky130_fd_pr__nfet_01v8 w={{wn_load}} l={{ln_load}}

Xn_cas1 outn ncas_bias nd1 0 sky130_fd_pr__nfet_01v8 w={{wn_cas}} l={{ln_cas}}
Xn_cas2 outp ncas_bias nd2 0 sky130_fd_pr__nfet_01v8 w={{wn_cas}} l={{ln_cas}}
Xp_cas1 outn pcas_bias pd1 vdd sky130_fd_pr__pfet_01v8 w={{wp_cas}} l={{lp_cas}}
Xp_cas2 outp pcas_bias pd2 vdd sky130_fd_pr__pfet_01v8 w={{wp_cas}} l={{lp_cas}}

Vncas ncas_bias 0 0.7
Vpcas pcas_bias 0 1.0

Ecmfb vcm_sense 0 vol='(v(outp)+v(outn))/2'
Gcmfb outp outn vcm_sense vcm_node 10u

CL_p outp 0 1p
CL_n outn 0 1p

.ac dec 50 1 10k

.control
run

let cm_gain_db = vdb(outp) - vdb(outn)
let cm_out = v(outp) - v(outn)

meas ac cm_gain_60hz find vdb(cm_out) at=60

set gnuplot_terminal=png
gnuplot {PLOTS_DIR}/cmrr_vs_freq cm_gain_db title "Common-Mode Gain (dB)" ylabel "Gain (dB)" xlabel "Frequency (Hz)"

print cm_gain_60hz
quit
.endc
.end
"""
    output = run_ngspice(netlist_cm)
    print(output[-2000:] if len(output) > 2000 else output)

    cm_gain_60 = parse_measurement(output, "cm_gain_60hz")

    if cm_gain_60 is not None:
        # CMRR = diff_gain - cm_gain (both in dB)
        # We'll use the diff gain from TB2, but for now compute from expected gain
        # Actual CMRR needs differential gain measurement too
        print(f"  CM gain at 60 Hz = {cm_gain_60:.1f} dB")
        return {"cm_gain_60hz_db": cm_gain_60}
    return None


def tb4_noise():
    """TB4: Input-Referred Noise"""
    print("\n" + "="*60)
    print("TB4: Input-Referred Noise")
    print("="*60)

    netlist = f"""* TB4: Noise Analysis
.lib "/home/ubuntu/workspace/sky130_models/sky130.lib.spice" tt

.param vdd_val = 1.8
.param vcm_val = 0.9
.param ibias_val = 2u
.param wp_in = 50u
.param lp_in = 2u
.param wn_load = 5u
.param ln_load = 2u
.param wp_tail = 10u
.param lp_tail = 2u
.param wp_cas = 5u
.param lp_cas = 1u
.param wn_cas = 5u
.param ln_cas = 1u
.param cin_val = 10p
.param cfb_val = 200f
.param rpseudo = 100G

VDD vdd 0 {{vdd_val}}

Ibias vdd nbias {{ibias_val}}
Xbias_n nbias nbias 0 0 sky130_fd_pr__nfet_01v8 w={{wn_load}} l={{ln_load}}

* Input for noise analysis - AC source for transfer function
Vinp inp 0 DC 0.9 AC 0.5
Vinn inn 0 DC 0.9 AC -0.5

Cin_p inp inn_p {{cin_val}}
Cin_n inn inn_n {{cin_val}}

Rbias_p vcm_node inn_p {{rpseudo}}
Rbias_n vcm_node inn_n {{rpseudo}}
Vcm_bias vcm_node 0 {{vcm_val}}

Cfb_p outp inn_p {{cfb_val}}
Cfb_n outn inn_n {{cfb_val}}

Xp_tail_bias ptail_bias ptail_bias vdd vdd sky130_fd_pr__pfet_01v8 w={{wp_tail}} l={{lp_tail}}
Ip_tail_ref vdd ptail_bias {{ibias_val*2}}
Xp_tail tail ptail_bias vdd vdd sky130_fd_pr__pfet_01v8 w={{wp_tail}} l={{lp_tail}}

Xp_in1 pd1 inn_n tail vdd sky130_fd_pr__pfet_01v8 w={{wp_in}} l={{lp_in}}
Xp_in2 pd2 inn_p tail vdd sky130_fd_pr__pfet_01v8 w={{wp_in}} l={{lp_in}}

Xn_load1 nd1 nbias 0 0 sky130_fd_pr__nfet_01v8 w={{wn_load}} l={{ln_load}}
Xn_load2 nd2 nbias 0 0 sky130_fd_pr__nfet_01v8 w={{wn_load}} l={{ln_load}}

Xn_cas1 outn ncas_bias nd1 0 sky130_fd_pr__nfet_01v8 w={{wn_cas}} l={{ln_cas}}
Xn_cas2 outp ncas_bias nd2 0 sky130_fd_pr__nfet_01v8 w={{wn_cas}} l={{ln_cas}}
Xp_cas1 outn pcas_bias pd1 vdd sky130_fd_pr__pfet_01v8 w={{wp_cas}} l={{lp_cas}}
Xp_cas2 outp pcas_bias pd2 vdd sky130_fd_pr__pfet_01v8 w={{wp_cas}} l={{lp_cas}}

Vncas ncas_bias 0 0.7
Vpcas pcas_bias 0 1.0

Ecmfb vcm_sense 0 vol='(v(outp)+v(outn))/2'
Gcmfb outp outn vcm_sense vcm_node 10u

CL_p outp 0 1p
CL_n outn 0 1p

.noise v(outp,outn) Vinp dec 50 0.1 10k

.control
run

setplot noise1
let onoise_density = onoise_spectrum
set gnuplot_terminal=png
gnuplot {PLOTS_DIR}/noise_spectral_density onoise_density title "Output Noise Spectral Density" ylabel "V/sqrt(Hz)" xlabel "Frequency (Hz)"

* Integrate noise from 0.5 to 150 Hz
setplot noise2
print onoise_total

quit
.endc
.end
"""
    output = run_ngspice(netlist)
    print(output[-2000:] if len(output) > 2000 else output)

    # Parse total output noise
    total_noise = parse_measurement(output, "onoise_total")
    if total_noise is not None:
        print(f"  Total output noise (integrated) = {total_noise*1e6:.3f} µV")
        # Need gain to refer to input - will compute in scoring
        return {"output_noise_vrms": total_noise}
    return None


def tb5_offset():
    """TB5: Input Offset"""
    print("\n" + "="*60)
    print("TB5: Input Offset")
    print("="*60)

    netlist = f"""* TB5: Input Offset Measurement
.lib "/home/ubuntu/workspace/sky130_models/sky130.lib.spice" tt

.param vdd_val = 1.8
.param vcm_val = 0.9
.param ibias_val = 2u
.param wp_in = 50u
.param lp_in = 2u
.param wn_load = 5u
.param ln_load = 2u
.param wp_tail = 10u
.param lp_tail = 2u
.param wp_cas = 5u
.param lp_cas = 1u
.param wn_cas = 5u
.param ln_cas = 1u
.param cin_val = 10p
.param cfb_val = 200f
.param rpseudo = 100G

VDD vdd 0 {{vdd_val}}

Ibias vdd nbias {{ibias_val}}
Xbias_n nbias nbias 0 0 sky130_fd_pr__nfet_01v8 w={{wn_load}} l={{ln_load}}

* Zero differential input
Vinp inp 0 DC 0.9
Vinn inn 0 DC 0.9

Cin_p inp inn_p {{cin_val}}
Cin_n inn inn_n {{cin_val}}

Rbias_p vcm_node inn_p {{rpseudo}}
Rbias_n vcm_node inn_n {{rpseudo}}
Vcm_bias vcm_node 0 {{vcm_val}}

Cfb_p outp inn_p {{cfb_val}}
Cfb_n outn inn_n {{cfb_val}}

Xp_tail_bias ptail_bias ptail_bias vdd vdd sky130_fd_pr__pfet_01v8 w={{wp_tail}} l={{lp_tail}}
Ip_tail_ref vdd ptail_bias {{ibias_val*2}}
Xp_tail tail ptail_bias vdd vdd sky130_fd_pr__pfet_01v8 w={{wp_tail}} l={{lp_tail}}

Xp_in1 pd1 inn_n tail vdd sky130_fd_pr__pfet_01v8 w={{wp_in}} l={{lp_in}}
Xp_in2 pd2 inn_p tail vdd sky130_fd_pr__pfet_01v8 w={{wp_in}} l={{lp_in}}

Xn_load1 nd1 nbias 0 0 sky130_fd_pr__nfet_01v8 w={{wn_load}} l={{ln_load}}
Xn_load2 nd2 nbias 0 0 sky130_fd_pr__nfet_01v8 w={{wn_load}} l={{ln_load}}

Xn_cas1 outn ncas_bias nd1 0 sky130_fd_pr__nfet_01v8 w={{wn_cas}} l={{ln_cas}}
Xn_cas2 outp ncas_bias nd2 0 sky130_fd_pr__nfet_01v8 w={{wn_cas}} l={{ln_cas}}
Xp_cas1 outn pcas_bias pd1 vdd sky130_fd_pr__pfet_01v8 w={{wp_cas}} l={{lp_cas}}
Xp_cas2 outp pcas_bias pd2 vdd sky130_fd_pr__pfet_01v8 w={{wp_cas}} l={{lp_cas}}

Vncas ncas_bias 0 0.7
Vpcas pcas_bias 0 1.0

Ecmfb vcm_sense 0 vol='(v(outp)+v(outn))/2'
Gcmfb outp outn vcm_sense vcm_node 10u

CL_p outp 0 1p
CL_n outn 0 1p

.tran 1m 2 uic

.control
run

let vout_diff = v(outp) - v(outn)
let final_offset_out = vout_diff[length(vout_diff)-1]
print final_offset_out

set gnuplot_terminal=png
gnuplot {PLOTS_DIR}/offset_measurement vout_diff title "Output Offset (zero input)" ylabel "Voltage (V)" xlabel "Time (s)"

quit
.endc
.end
"""
    output = run_ngspice(netlist)
    print(output[-2000:] if len(output) > 2000 else output)

    offset_out = parse_measurement(output, "final_offset_out")
    if offset_out is not None:
        print(f"  Output offset = {offset_out*1000:.3f} mV")
        return {"output_offset_v": offset_out}
    return None


def tb6_electrode_offset():
    """TB6: Electrode Offset Tolerance"""
    print("\n" + "="*60)
    print("TB6: Electrode Offset Tolerance")
    print("="*60)

    results = {}
    for offset_mv in [300, -300]:
        vcm = 0.9 + offset_mv/1000.0
        vin_diff = 0.001  # 1mV

        netlist = f"""* TB6: Electrode Offset = {offset_mv} mV
.lib "/home/ubuntu/workspace/sky130_models/sky130.lib.spice" tt

.param vdd_val = 1.8
.param vcm_val = 0.9
.param ibias_val = 2u
.param wp_in = 50u
.param lp_in = 2u
.param wn_load = 5u
.param ln_load = 2u
.param wp_tail = 10u
.param lp_tail = 2u
.param wp_cas = 5u
.param lp_cas = 1u
.param wn_cas = 5u
.param ln_cas = 1u
.param cin_val = 10p
.param cfb_val = 200f
.param rpseudo = 100G

VDD vdd 0 {{vdd_val}}

Ibias vdd nbias {{ibias_val}}
Xbias_n nbias nbias 0 0 sky130_fd_pr__nfet_01v8 w={{wn_load}} l={{ln_load}}

* Input with electrode offset
Vinp inp 0 DC {vcm + vin_diff/2}
Vinn inn 0 DC {vcm - vin_diff/2}

Cin_p inp inn_p {{cin_val}}
Cin_n inn inn_n {{cin_val}}

Rbias_p vcm_node inn_p {{rpseudo}}
Rbias_n vcm_node inn_n {{rpseudo}}
Vcm_bias vcm_node 0 {{vcm_val}}

Cfb_p outp inn_p {{cfb_val}}
Cfb_n outn inn_n {{cfb_val}}

Xp_tail_bias ptail_bias ptail_bias vdd vdd sky130_fd_pr__pfet_01v8 w={{wp_tail}} l={{lp_tail}}
Ip_tail_ref vdd ptail_bias {{ibias_val*2}}
Xp_tail tail ptail_bias vdd vdd sky130_fd_pr__pfet_01v8 w={{wp_tail}} l={{lp_tail}}

Xp_in1 pd1 inn_n tail vdd sky130_fd_pr__pfet_01v8 w={{wp_in}} l={{lp_in}}
Xp_in2 pd2 inn_p tail vdd sky130_fd_pr__pfet_01v8 w={{wp_in}} l={{lp_in}}

Xn_load1 nd1 nbias 0 0 sky130_fd_pr__nfet_01v8 w={{wn_load}} l={{ln_load}}
Xn_load2 nd2 nbias 0 0 sky130_fd_pr__nfet_01v8 w={{wn_load}} l={{ln_load}}

Xn_cas1 outn ncas_bias nd1 0 sky130_fd_pr__nfet_01v8 w={{wn_cas}} l={{ln_cas}}
Xn_cas2 outp ncas_bias nd2 0 sky130_fd_pr__nfet_01v8 w={{wn_cas}} l={{ln_cas}}
Xp_cas1 outn pcas_bias pd1 vdd sky130_fd_pr__pfet_01v8 w={{wp_cas}} l={{lp_cas}}
Xp_cas2 outp pcas_bias pd2 vdd sky130_fd_pr__pfet_01v8 w={{wp_cas}} l={{lp_cas}}

Vncas ncas_bias 0 0.7
Vpcas pcas_bias 0 1.0

Ecmfb vcm_sense 0 vol='(v(outp)+v(outn))/2'
Gcmfb outp outn vcm_sense vcm_node 10u

CL_p outp 0 1p
CL_n outn 0 1p

.tran 1m 2 uic

.control
run

let vout_diff = v(outp) - v(outn)
let final_vout = vout_diff[length(vout_diff)-1]
let final_voutp = v(outp)[length(v(outp))-1]
let final_voutn = v(outn)[length(v(outn))-1]
print final_vout final_voutp final_voutn

quit
.endc
.end
"""
        output = run_ngspice(netlist)
        vout = parse_measurement(output, "final_vout")
        voutp = parse_measurement(output, "final_voutp")
        voutn = parse_measurement(output, "final_voutn")

        if vout is not None:
            gain = abs(vout) / vin_diff
            gain_db = 20 * math.log10(max(gain, 1e-10))
            print(f"  Offset {offset_mv:+d} mV: Vout_diff = {vout*1000:.3f} mV, Gain = {gain_db:.1f} dB")
            print(f"    Voutp = {voutp:.4f} V, Voutn = {voutn:.4f} V")
            if voutp < 0.2 or voutp > 1.6 or voutn < 0.2 or voutn > 1.6:
                print(f"    WARNING: Output saturated!")
            results[f"gain_db_offset_{offset_mv}mv"] = gain_db

    return results if results else None


def compute_power():
    """Compute total power consumption."""
    print("\n" + "="*60)
    print("Power Consumption")
    print("="*60)

    netlist = f"""* Power measurement
.lib "/home/ubuntu/workspace/sky130_models/sky130.lib.spice" tt

.param vdd_val = 1.8
.param vcm_val = 0.9
.param ibias_val = 2u
.param wp_in = 50u
.param lp_in = 2u
.param wn_load = 5u
.param ln_load = 2u
.param wp_tail = 10u
.param lp_tail = 2u
.param wp_cas = 5u
.param lp_cas = 1u
.param wn_cas = 5u
.param ln_cas = 1u
.param cin_val = 10p
.param cfb_val = 200f
.param rpseudo = 100G

VDD vdd 0 {{vdd_val}}

Ibias vdd nbias {{ibias_val}}
Xbias_n nbias nbias 0 0 sky130_fd_pr__nfet_01v8 w={{wn_load}} l={{ln_load}}

Vinp inp 0 DC 0.9
Vinn inn 0 DC 0.9

Cin_p inp inn_p {{cin_val}}
Cin_n inn inn_n {{cin_val}}

Rbias_p vcm_node inn_p {{rpseudo}}
Rbias_n vcm_node inn_n {{rpseudo}}
Vcm_bias vcm_node 0 {{vcm_val}}

Cfb_p outp inn_p {{cfb_val}}
Cfb_n outn inn_n {{cfb_val}}

Xp_tail_bias ptail_bias ptail_bias vdd vdd sky130_fd_pr__pfet_01v8 w={{wp_tail}} l={{lp_tail}}
Ip_tail_ref vdd ptail_bias {{ibias_val*2}}
Xp_tail tail ptail_bias vdd vdd sky130_fd_pr__pfet_01v8 w={{wp_tail}} l={{lp_tail}}

Xp_in1 pd1 inn_n tail vdd sky130_fd_pr__pfet_01v8 w={{wp_in}} l={{lp_in}}
Xp_in2 pd2 inn_p tail vdd sky130_fd_pr__pfet_01v8 w={{wp_in}} l={{lp_in}}

Xn_load1 nd1 nbias 0 0 sky130_fd_pr__nfet_01v8 w={{wn_load}} l={{ln_load}}
Xn_load2 nd2 nbias 0 0 sky130_fd_pr__nfet_01v8 w={{wn_load}} l={{ln_load}}

Xn_cas1 outn ncas_bias nd1 0 sky130_fd_pr__nfet_01v8 w={{wn_cas}} l={{ln_cas}}
Xn_cas2 outp ncas_bias nd2 0 sky130_fd_pr__nfet_01v8 w={{wn_cas}} l={{ln_cas}}
Xp_cas1 outn pcas_bias pd1 vdd sky130_fd_pr__pfet_01v8 w={{wp_cas}} l={{lp_cas}}
Xp_cas2 outp pcas_bias pd2 vdd sky130_fd_pr__pfet_01v8 w={{wp_cas}} l={{lp_cas}}

Vncas ncas_bias 0 0.7
Vpcas pcas_bias 0 1.0

Ecmfb vcm_sense 0 vol='(v(outp)+v(outn))/2'
Gcmfb outp outn vcm_sense vcm_node 10u

CL_p outp 0 1p
CL_n outn 0 1p

.op

.control
run
let ivdd = @VDD[i]
let power_uw = -ivdd * 1.8 * 1e6
print ivdd power_uw
quit
.endc
.end
"""
    output = run_ngspice(netlist)
    print(output[-1500:] if len(output) > 1500 else output)

    power = parse_measurement(output, "power_uw")
    ivdd = parse_measurement(output, "ivdd")

    if power is not None:
        print(f"  Supply current = {abs(ivdd)*1e6:.2f} µA")
        print(f"  Power = {abs(power):.2f} µW")
        return {"power_uw": abs(power), "ivdd_ua": abs(ivdd)*1e6}
    return None


def score_results(measurements):
    """Score measurements against specs."""
    print("\n" + "="*60)
    print("SCORING")
    print("="*60)

    spec_defs = specs["measurements"]
    total_weight = sum(s["weight"] for s in spec_defs.values())
    weighted_score = 0
    specs_met = 0
    total_specs = len(spec_defs)
    results_table = []

    for name, spec in spec_defs.items():
        target = spec["target"]
        weight = spec["weight"]
        measured = measurements.get(name)

        if measured is None:
            status = "MISSING"
            passed = False
        else:
            if target.startswith(">"):
                threshold = float(target[1:])
                passed = measured > threshold
            elif target.startswith("<"):
                threshold = float(target[1:])
                passed = measured < threshold
            else:
                threshold = float(target)
                passed = abs(measured - threshold) < 0.1 * abs(threshold)

            status = "PASS" if passed else "FAIL"

        if passed:
            weighted_score += weight
            specs_met += 1

        measured_str = f"{measured:.4g}" if measured is not None else "N/A"
        results_table.append((name, target, measured_str, status, weight))
        print(f"  {name:35s} target={target:>10s}  measured={measured_str:>12s}  [{status}] (w={weight})")

    score = weighted_score / total_weight
    print(f"\n  Score: {score:.4f} ({specs_met}/{total_specs} specs met)")
    print(f"  Weighted: {weighted_score}/{total_weight}")

    return score, specs_met, total_specs


def main():
    print("=" * 60)
    print("SKY130 Instrumentation Amplifier — Evaluation")
    print("=" * 60)

    measurements = {}

    # TB1: DC Gain
    tb1 = tb1_dc_gain()
    if tb1:
        measurements["gain_db"] = tb1.get("gain_db", 0)

    # TB2: AC Response
    tb2 = tb2_ac_response()
    if tb2:
        if "bandwidth_hz" in tb2:
            measurements["bandwidth_hz"] = tb2["bandwidth_hz"]
        if "midband_gain_db" in tb2:
            # Use AC midband gain as more reliable
            measurements["gain_db"] = tb2["midband_gain_db"]

    # TB3: CMRR
    tb3 = tb3_cmrr()
    diff_gain_db = measurements.get("gain_db", 34)
    if tb3 and "cm_gain_60hz_db" in tb3:
        cm_gain = tb3["cm_gain_60hz_db"]
        cmrr = diff_gain_db - cm_gain
        measurements["cmrr_60hz_db"] = cmrr
        print(f"  CMRR at 60 Hz = {diff_gain_db:.1f} - ({cm_gain:.1f}) = {cmrr:.1f} dB")

    # TB4: Noise
    tb4 = tb4_noise()
    if tb4 and "output_noise_vrms" in tb4:
        gain_linear = 10**(diff_gain_db/20) if diff_gain_db > 0 else 50
        input_noise = tb4["output_noise_vrms"] / gain_linear
        measurements["input_referred_noise_uvrms"] = input_noise * 1e6
        print(f"  Input-referred noise = {input_noise*1e6:.3f} µVrms")

    # TB5: Offset
    tb5 = tb5_offset()
    if tb5 and "output_offset_v" in tb5:
        gain_linear = 10**(diff_gain_db/20) if diff_gain_db > 0 else 50
        input_offset = abs(tb5["output_offset_v"]) / gain_linear
        measurements["input_offset_uv"] = input_offset * 1e6
        print(f"  Input-referred offset = {input_offset*1e6:.1f} µV")

    # TB6: Electrode offset
    tb6 = tb6_electrode_offset()
    if tb6:
        for k, v in tb6.items():
            measurements[k] = v

    # Power
    pwr = compute_power()
    if pwr:
        measurements["power_uw"] = pwr["power_uw"]

    # Score
    score, specs_met, total_specs = score_results(measurements)

    # Save measurements
    with open(MEASUREMENTS_FILE, 'w') as f:
        json.dump({"measurements": measurements, "score": score,
                    "specs_met": specs_met, "total_specs": total_specs}, f, indent=2)

    print(f"\nscore = {score:.4f}")
    print(f"specs_met = {specs_met}/{total_specs}")

    return score


if __name__ == "__main__":
    score = main()
