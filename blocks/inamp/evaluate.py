#!/usr/bin/env python3
"""
SKY130 Instrumentation Amplifier — Evaluator
Fully-differential CCIA with folded-cascode OTA and ideal CMFB.
"""

import subprocess
import os
import json
import math
import re
import numpy as np

os.chdir(os.path.dirname(os.path.abspath(__file__)))

PLOTS_DIR = "plots"
SPECS_FILE = "specs.json"
MEASUREMENTS_FILE = "measurements.json"
os.makedirs(PLOTS_DIR, exist_ok=True)

with open(SPECS_FILE) as f:
    specs = json.load(f)

# ── Fully-differential folded-cascode OTA ─────────────────────
# High open-loop gain for accurate Cin/Cfb gain setting.
# PMOS input pair: large W/L for low 1/f noise.
# NMOS cascode loads for high output impedance.
# Ideal CMFB sets output CM to 0.9V.
OTA = r"""
.subckt fd_ota inp inn outp outn vdd vss

.param wp_in  = 100u
.param lp_in  = 4u
.param wn_ld  = 5u
.param ln_ld  = 4u
.param wn_cas = 5u
.param ln_cas = 1u
.param itail  = 3u
.param ifold  = 2u

* PMOS tail current source (ideal)
Itail vdd tail {itail}

* PMOS input differential pair
* M1: gate=inn, drain=fd1 → inn is inverting for outp (via fold)
* M2: gate=inp, drain=fd2 → inp is inverting for outn (via fold)
* NOTE: cross-connection — M1 drain goes to fold1 which drives outn,
*       M2 drain goes to fold2 which drives outp.
* Actually: M1.drain=fd1, Mn_cas1(fd1→outn), so inn↑ → M1 less current
*   → less current into fd1 → Mn_cas1 carries less → outn rises.
*   So inn is NON-inverting for outn, INVERTING for outp.
Xm1 fd1 inn tail vdd sky130_fd_pr__pfet_01v8 w={wp_in} l={lp_in}
Xm2 fd2 inp tail vdd sky130_fd_pr__pfet_01v8 w={wp_in} l={lp_in}

* PMOS fold current sources from VDD (ideal)
* These inject current at the output nodes
Ifold1 vdd outn {ifold}
Ifold2 vdd outp {ifold}

* NMOS cascodes: carry signal current from output to fold nodes
Xm_nc1 outn ncas fd1 vss sky130_fd_pr__nfet_01v8 w={wn_cas} l={ln_cas}
Xm_nc2 outp ncas fd2 vss sky130_fd_pr__nfet_01v8 w={wn_cas} l={ln_cas}

* NMOS loads at fold nodes (gate from CMFB)
Xm3 fd1 ncmfb vss vss sky130_fd_pr__nfet_01v8 w={wn_ld} l={ln_ld}
Xm4 fd2 ncmfb vss vss sky130_fd_pr__nfet_01v8 w={wn_ld} l={ln_ld}

* Cascode bias: needs to be above Vgs_M3 + Vth_cas
* V(fd) ≈ 0.4-0.5V, so ncas ≈ 0.9V puts cascode well in saturation
Vncas ncas vss 0.9

* Ideal CMFB: adjust NMOS load gate to set output CM = 0.9V
* Nominal ncmfb ≈ 0.45V; CMFB gain = 50
Ecmfb ncmfb vss vol='max(0.2, min(1.2, 0.45 + 50*((v(outp)+v(outn))/2 - 0.9)))'

.ends fd_ota
"""

HDR = '.lib "/home/ubuntu/workspace/sky130_models/sky130.lib.spice" tt\n'


def make_inamp(vcm_inp=0.9, vcm_inn=0.9, ac_inp="0", ac_inn="0",
               extra="", cin="10p", cfb="200f", rfb="1T", rpb="1T"):
    """Build complete InAmp netlist: OTA + caps + bias."""
    return HDR + OTA + f"""
.param cin_v  = {cin}
.param cfb_v  = {cfb}
.param rfb_v  = {rfb}
.param rpb_v  = {rpb}

VDD vdd 0 1.8

* Input sources
Vip inp_ext 0 DC {vcm_inp} AC {ac_inp}
Vin inn_ext 0 DC {vcm_inn} AC {ac_inn}

* Input coupling capacitors (reject DC electrode offset)
Cin_p inp_ext gp {{cin_v}}
Cin_n inn_ext gn {{cin_v}}

* DC bias for OTA inputs (pseudo-resistors to Vcm=0.9V)
Rpb_p vcm gp {{rpb_v}}
Rpb_n vcm gn {{rpb_v}}
Vcm   vcm 0 0.9

* Feedback caps (gain = Cin/Cfb ≈ 50 V/V = 34 dB)
* gp → inp of OTA (inverting for outp)
* gn → inn of OTA (inverting for outn)
* Negative feedback: outp → gp, outn → gn
Cfb_p outp gp {{cfb_v}}
Cfb_n outn gn {{cfb_v}}

* DC feedback resistors in parallel with Cfb
* Sets HPF cutoff: f_HPF = 1/(2π × Rfb × Cfb)
* With Rfb=1T, Cfb=200f: f_HPF ≈ 0.8 Hz
Rfb_p outp gp {{rfb_v}}
Rfb_n outn gn {{rfb_v}}

* OTA: gp=inp (inverting for outp), gn=inn (inverting for outn)
Xota gp gn outp outn vdd 0 fd_ota

* Load caps (next stage input)
CL_p outp 0 1p
CL_n outn 0 1p

* Initial conditions
.ic v(gp)=0.9 v(gn)=0.9 v(outp)=0.9 v(outn)=0.9

{extra}
"""


def run_ngspice(netlist, timeout=120):
    path = "/tmp/inamp_tb.cir"
    with open(path, "w") as f:
        f.write(netlist)
    try:
        r = subprocess.run(["ngspice", "-b", path],
                           capture_output=True, text=True, timeout=timeout)
        return r.stdout + "\n" + r.stderr
    except subprocess.TimeoutExpired:
        return "ERROR: timeout"


def grab(output, name):
    m = re.search(rf'{name}\s*=\s*([-+]?\d+\.?\d*(?:[eE][-+]?\d+)?)', output)
    return float(m.group(1)) if m else None


# ── TB1: DC Gain ──────────────────────────────────────────────
def tb1_dc_gain():
    print("\n>>> TB1: DC Gain (1 mV differential, transient 1s)")
    net = make_inamp(
        vcm_inp=0.9005, vcm_inn=0.8995,
        extra=f"""
.tran 1m 1

.control
run
let vdiff = v(outp) - v(outn)
let t_len = length(vdiff) - 1
let final_vdiff = vdiff[t_len]
let final_outp = v(outp)[t_len]
let final_outn = v(outn)[t_len]
let final_cm = (v(outp)[t_len] + v(outn)[t_len])/2
print final_vdiff final_outp final_outn final_cm
set gnuplot_terminal=png
gnuplot {PLOTS_DIR}/dc_gain vdiff title "Diff Output (1mV diff input)" ylabel "V" xlabel "s"
quit
.endc
.end
""")
    out = run_ngspice(net, timeout=180)
    print(out[-1500:])
    vdiff = grab(out, "final_vdiff")
    voutp = grab(out, "final_outp")
    voutn = grab(out, "final_outn")
    vcm = grab(out, "final_cm")
    if vdiff is None:
        return None
    gain = abs(vdiff) / 0.001
    gain_db = 20 * math.log10(max(gain, 1e-10))
    print(f"  Vdiff_out={vdiff*1000:.3f} mV  Gain={gain:.1f} V/V = {gain_db:.1f} dB")
    print(f"  Voutp={voutp:.4f}  Voutn={voutn:.4f}  CM={vcm:.4f}")
    sat = (voutp is not None and (voutp < 0.2 or voutp > 1.6)) or \
          (voutn is not None and (voutn < 0.2 or voutn > 1.6))
    if sat:
        print("  WARNING: output may be saturated!")
    return {"gain_db": gain_db, "gain_vv": gain, "voutp": voutp, "voutn": voutn,
            "vcm_out": vcm, "saturated": sat}


# ── TB2: AC Response ──────────────────────────────────────────
def tb2_ac():
    print("\n>>> TB2: AC Frequency Response")
    net = make_inamp(
        ac_inp="0.5", ac_inn="-0.5",
        extra=f"""
.ac dec 50 0.01 100Meg

.control
run
let vdiff = v(outp) - v(outn)
let gain_db = vdb(vdiff)

meas ac gain_1hz   FIND vdb(vdiff) AT=1
meas ac gain_60hz  FIND vdb(vdiff) AT=60
meas ac gain_150hz FIND vdb(vdiff) AT=150
meas ac peak_gain  MAX  vdb(vdiff) from=1 to=1k
meas ac bw_3db WHEN vdb(vdiff)='peak_gain-3' FALL=1

set gnuplot_terminal=png
gnuplot {PLOTS_DIR}/ac_response gain_db title "Diff Gain (dB)" ylabel "dB" xlabel "Hz"

print gain_1hz gain_60hz gain_150hz peak_gain bw_3db
quit
.endc
.end
""")
    out = run_ngspice(net)
    print(out[-2000:])
    r = {}
    for k in ["gain_1hz", "gain_60hz", "gain_150hz", "peak_gain", "bw_3db"]:
        v = grab(out, k)
        if v is not None:
            r[k] = v
            print(f"  {k} = {v:.4g}")
    return r if r else None


# ── TB3: CMRR ────────────────────────────────────────────────
def tb3_cmrr():
    print("\n>>> TB3: CMRR")
    net = make_inamp(
        ac_inp="1", ac_inn="1",
        extra=f"""
.ac dec 50 1 10k

.control
run
let vdiff = v(outp) - v(outn)
let cm_gain_db = vdb(vdiff)
meas ac cm_gain_60 FIND vdb(vdiff) AT=60

set gnuplot_terminal=png
gnuplot {PLOTS_DIR}/cmrr_vs_freq cm_gain_db title "CM-to-Diff Gain (dB)" ylabel "dB" xlabel "Hz"

print cm_gain_60
quit
.endc
.end
""")
    out = run_ngspice(net)
    print(out[-1500:])
    cm60 = grab(out, "cm_gain_60")
    if cm60 is not None:
        print(f"  CM→Diff gain at 60 Hz = {cm60:.1f} dB")
    return {"cm_gain_60_db": cm60} if cm60 is not None else None


# ── TB4: Noise ────────────────────────────────────────────────
def tb4_noise():
    print("\n>>> TB4: Input-Referred Noise (0.5–150 Hz)")
    net = make_inamp(
        ac_inp="1", ac_inn="0",
        extra=f"""
* Noise analysis over the biosignal band
.noise v(outp,outn) Vip dec 100 0.5 150

.control
run
setplot noise1
set gnuplot_terminal=png
gnuplot {PLOTS_DIR}/noise_spectral_density onoise_spectrum title "Output Noise (V/rtHz)" ylabel "V/rtHz" xlabel "Hz"

setplot noise2
print onoise_total inoise_total
quit
.endc
.end
""")
    out = run_ngspice(net)
    print(out[-1500:])
    inoise = grab(out, "inoise_total")
    onoise = grab(out, "onoise_total")
    if inoise is not None:
        print(f"  Input-referred noise (0.5-150 Hz) = {inoise*1e6:.3f} µVrms")
    if onoise is not None:
        print(f"  Output noise (0.5-150 Hz) = {onoise*1e6:.3f} µVrms")
    return {"inoise_total": inoise, "onoise_total": onoise} if inoise is not None else None


# ── TB5: Offset ───────────────────────────────────────────────
def tb5_offset():
    print("\n>>> TB5: Input Offset")
    net = make_inamp(
        extra=f"""
.tran 1m 1

.control
run
let vdiff = v(outp) - v(outn)
let vfinal = vdiff[length(vdiff)-1]
print vfinal
set gnuplot_terminal=png
gnuplot {PLOTS_DIR}/offset_measurement vdiff title "Output (zero input)" ylabel "V" xlabel "s"
quit
.endc
.end
""")
    out = run_ngspice(net, timeout=180)
    print(out[-1000:])
    v = grab(out, "vfinal")
    if v is not None:
        print(f"  Output offset = {v*1000:.3f} mV")
        return {"output_offset_v": v}
    return None


# ── TB6: Electrode offset ────────────────────────────────────
def tb6_electrode():
    print("\n>>> TB6: Electrode Offset Tolerance")
    results = {}
    for eoff_mv in [300, -300]:
        vcm_in = 0.9 + eoff_mv / 1000.0
        net = make_inamp(
            vcm_inp=vcm_in + 0.0005,
            vcm_inn=vcm_in - 0.0005,
            extra=f"""
.tran 1m 1

.control
run
let vdiff = v(outp) - v(outn)
let t_len = length(vdiff) - 1
let vfinal = vdiff[t_len]
let voutp_f = v(outp)[t_len]
let voutn_f = v(outn)[t_len]
print vfinal voutp_f voutn_f
quit
.endc
.end
""")
        out = run_ngspice(net, timeout=180)
        vdiff = grab(out, "vfinal")
        voutp = grab(out, "voutp_f")
        voutn = grab(out, "voutn_f")
        if vdiff is not None:
            gain = abs(vdiff) / 0.001
            gain_db = 20 * math.log10(max(gain, 1e-10))
            sat = (voutp is not None and (voutp < 0.2 or voutp > 1.6)) or \
                  (voutn is not None and (voutn < 0.2 or voutn > 1.6))
            print(f"  Off {eoff_mv:+d}mV: Vdiff={vdiff*1000:.2f}mV gain={gain_db:.1f}dB sat={'YES' if sat else 'no'}")
            if voutp is not None:
                print(f"    Voutp={voutp:.4f} Voutn={voutn:.4f}")
            results[f"off{eoff_mv}_gain_db"] = gain_db
            results[f"off{eoff_mv}_sat"] = sat
    return results if results else None


# ── Power ─────────────────────────────────────────────────────
def measure_power():
    print("\n>>> Power Consumption")
    net = make_inamp(
        extra="""
.op

.control
run
let idd = -@VDD[i]
let pwr = idd * 1.8 * 1e6
print idd pwr
quit
.endc
.end
""")
    out = run_ngspice(net)
    print(out[-1000:])
    pwr = grab(out, "pwr")
    idd = grab(out, "idd")
    if pwr is not None:
        print(f"  Isupply={abs(idd)*1e6:.2f} µA  Power={abs(pwr):.2f} µW")
        return {"power_uw": abs(pwr), "idd_ua": abs(idd) * 1e6}
    return None


# ── Scoring ───────────────────────────────────────────────────
def score_results(meas):
    print("\n" + "=" * 60)
    print("SCORING")
    print("=" * 60)
    sdefs = specs["measurements"]
    total_w = sum(s["weight"] for s in sdefs.values())
    got_w = 0; n_pass = 0; n_total = len(sdefs)

    for name, s in sdefs.items():
        tgt = s["target"]; w = s["weight"]
        val = meas.get(name)
        if val is None:
            status = "MISS"; passed = False
        else:
            if tgt.startswith(">"):
                passed = val > float(tgt[1:])
            elif tgt.startswith("<"):
                passed = val < float(tgt[1:])
            else:
                passed = False
            status = "PASS" if passed else "FAIL"
        if passed:
            got_w += w; n_pass += 1
        vs = f"{val:.4g}" if val is not None else "N/A"
        print(f"  {name:35s} tgt={tgt:>8s}  val={vs:>12s}  [{status}] w={w}")

    sc = got_w / total_w
    print(f"\n  Score: {sc:.4f}  ({n_pass}/{n_total} pass)")
    return sc, n_pass, n_total


# ── Main ──────────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("SKY130 InAmp — Folded-Cascode CCIA Evaluation")
    print("=" * 60)

    meas = {}

    # TB1: DC Gain (transient)
    r = tb1_dc_gain()
    if r:
        meas["gain_db"] = r["gain_db"]

    # TB2: AC Response (most reliable gain measurement)
    r = tb2_ac()
    if r:
        if "peak_gain" in r:
            meas["gain_db"] = r["peak_gain"]
        if "bw_3db" in r:
            meas["bandwidth_hz"] = r["bw_3db"]

    diff_gain_db = meas.get("gain_db", 0)

    # TB3: CMRR
    r = tb3_cmrr()
    if r and "cm_gain_60_db" in r:
        cmrr = diff_gain_db - r["cm_gain_60_db"]
        meas["cmrr_60hz_db"] = cmrr
        print(f"  CMRR = {diff_gain_db:.1f} - ({r['cm_gain_60_db']:.1f}) = {cmrr:.1f} dB")

    # TB4: Noise
    r = tb4_noise()
    if r and "inoise_total" in r:
        meas["input_referred_noise_uvrms"] = r["inoise_total"] * 1e6
        print(f"  Input-referred noise = {r['inoise_total']*1e6:.3f} µVrms")

    # TB5: Offset
    r = tb5_offset()
    if r:
        gain_lin = 10 ** (diff_gain_db / 20) if diff_gain_db > 0 else 1
        meas["input_offset_uv"] = abs(r["output_offset_v"]) / gain_lin * 1e6
        print(f"  Input offset = {meas['input_offset_uv']:.1f} µV")

    # TB6: Electrode offset
    tb6_electrode()

    # Power
    r = measure_power()
    if r:
        meas["power_uw"] = r["power_uw"]

    # Score
    sc, n_pass, n_total = score_results(meas)

    with open(MEASUREMENTS_FILE, "w") as f:
        json.dump({"measurements": meas, "score": sc,
                    "specs_met": n_pass, "total_specs": n_total}, f, indent=2)

    print(f"\nscore = {sc:.4f}")
    print(f"specs_met = {n_pass}/{n_total}")
    return sc


if __name__ == "__main__":
    main()
