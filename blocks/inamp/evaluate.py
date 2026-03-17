#!/usr/bin/env python3
"""
SKY130 Chopper Instrumentation Amplifier — Evaluator
Fully-differential CCIA with system-level chopping for realistic CMRR.

Tests:
  TB1: DC Gain (transient)
  TB2: AC Frequency Response
  TB3: CMRR — transient with choppers + 0.1% Cin mismatch
  TB4: Input-Referred Noise
  TB5: Input Offset
  TB6: Electrode Offset Tolerance
  TB7: Realistic ECG Transient
  TB8: PVT Corner Analysis (Phase B)
  Power measurement
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

# ── OTA subcircuit (shared by all testbenches) ────────────────
OTA = r"""
.subckt fd_ota inp inn outp outn vdd vss

.param wp_in  = 99u
.param lp_in  = 8u
.param wn_cas = 49u
.param ln_cas = 10u
.param itail  = 5u
.param ifold  = 0.5u

* PMOS tail current mirror (real, 10:1 ratio)
Ibias_ref ptbias vss {itail/10}
Xpt_ref ptbias ptbias vdd vdd sky130_fd_pr__pfet_01v8 w=7u l=4u
Xpt_tail tail ptbias vdd vdd sky130_fd_pr__pfet_01v8 w=70u l=4u

* PMOS LVT input pair — 8 parallel (effective WL=6336um^2)
Xm1a fd1 inn tail vdd sky130_fd_pr__pfet_01v8_lvt w={wp_in} l={lp_in}
Xm1b fd1 inn tail vdd sky130_fd_pr__pfet_01v8_lvt w={wp_in} l={lp_in}
Xm1c fd1 inn tail vdd sky130_fd_pr__pfet_01v8_lvt w={wp_in} l={lp_in}
Xm1d fd1 inn tail vdd sky130_fd_pr__pfet_01v8_lvt w={wp_in} l={lp_in}
Xm1e fd1 inn tail vdd sky130_fd_pr__pfet_01v8_lvt w={wp_in} l={lp_in}
Xm1f fd1 inn tail vdd sky130_fd_pr__pfet_01v8_lvt w={wp_in} l={lp_in}
Xm1g fd1 inn tail vdd sky130_fd_pr__pfet_01v8_lvt w={wp_in} l={lp_in}
Xm1h fd1 inn tail vdd sky130_fd_pr__pfet_01v8_lvt w={wp_in} l={lp_in}
Xm2a fd2 inp tail vdd sky130_fd_pr__pfet_01v8_lvt w={wp_in} l={lp_in}
Xm2b fd2 inp tail vdd sky130_fd_pr__pfet_01v8_lvt w={wp_in} l={lp_in}
Xm2c fd2 inp tail vdd sky130_fd_pr__pfet_01v8_lvt w={wp_in} l={lp_in}
Xm2d fd2 inp tail vdd sky130_fd_pr__pfet_01v8_lvt w={wp_in} l={lp_in}
Xm2e fd2 inp tail vdd sky130_fd_pr__pfet_01v8_lvt w={wp_in} l={lp_in}
Xm2f fd2 inp tail vdd sky130_fd_pr__pfet_01v8_lvt w={wp_in} l={lp_in}
Xm2g fd2 inp tail vdd sky130_fd_pr__pfet_01v8_lvt w={wp_in} l={lp_in}
Xm2h fd2 inp tail vdd sky130_fd_pr__pfet_01v8_lvt w={wp_in} l={lp_in}

* PMOS fold current sources from VDD (ideal, noiseless)
Ifold1 vdd outn {ifold}
Ifold2 vdd outp {ifold}

* NMOS cascodes — 2 parallel (effective WL=980um^2)
Xm_nc1a outn ncas fd1 vss sky130_fd_pr__nfet_01v8 w={wn_cas} l={ln_cas}
Xm_nc1b outn ncas fd1 vss sky130_fd_pr__nfet_01v8 w={wn_cas} l={ln_cas}
Xm_nc2a outp ncas fd2 vss sky130_fd_pr__nfet_01v8 w={wn_cas} l={ln_cas}
Xm_nc2b outp ncas fd2 vss sky130_fd_pr__nfet_01v8 w={wn_cas} l={ln_cas}

* NMOS loads — REAL transistors (large WL for low 1/f noise)
Xm3 fd1 ncmfb vss vss sky130_fd_pr__nfet_01v8 w=99u l=99u
Xm4 fd2 ncmfb vss vss sky130_fd_pr__nfet_01v8 w=99u l=99u

* Ideal CMFB
Ecmfb ncmfb vss vol='max(0.2, min(1.2, 0.45 + 50*((v(outp)+v(outn))/2 - 0.9)))'

* Cascode bias
Vncas ncas vss 0.7

.ends fd_ota
"""

HDR = '.lib "/home/ubuntu/workspace/sky130_models/sky130.lib.spice" tt\n'


def make_inamp(vcm_inp=0.9, vcm_inn=0.9, ac_inp="0", ac_inn="0",
               extra="", cin="62p", cfb="1p", rpb_val=1e12, rfb_val=1e12):
    """Build CCIA netlist WITHOUT choppers (for AC/noise/offset/power tests)."""
    return HDR + OTA + f"""
.param cin_v  = {cin}
.param cfb_v  = {cfb}

VDD vdd 0 1.8

* Input sources
Vip inp_ext 0 DC {vcm_inp} AC {ac_inp}
Vin inn_ext 0 DC {vcm_inn} AC {ac_inn}

* Input coupling capacitors
Cin_p inp_ext gp {{cin_v}}
Cin_n inn_ext gn {{cin_v}}

* DC bias for OTA inputs
Gpb_p gp vcm cur='(v(gp)-v(vcm))/{rpb_val}'
Gpb_n gn vcm cur='(v(gn)-v(vcm))/{rpb_val}'
Vcm   vcm 0 0.9

* Feedback caps
Cfb_p outp gp {{cfb_v}}
Cfb_n outn gn {{cfb_v}}

* DC feedback
Gfb_p gp outp cur='(v(gp)-v(outp))/{rfb_val}'
Gfb_n gn outn cur='(v(gn)-v(outn))/{rfb_val}'

* OTA
Xota gp gn outp outn vdd 0 fd_ota

* Load caps
CL_p outp 0 1p
CL_n outn 0 1p

.ic v(gp)=0.9 v(gn)=0.9 v(outp)=0.9 v(outn)=0.9

{extra}
"""


def make_chopped_inamp(hdr=None, cin_mismatch=0.001, fchop=10e3,
                       vcm_inp_dc=0.9, vcm_inn_dc=0.9,
                       input_src_extra="", extra=""):
    """Build CCIA netlist WITH input/output choppers and Cin mismatch.

    Architecture:
      inp_ext -> [CH_in] -> Cin(mismatched) -> gp/gn -> OTA -> outp_ota/outn_ota
      outp_ota -> Cfb -> gp  (feedback, unchanged)
      outp_ota -> [CH_out] -> outp  (demodulated output)
    """
    if hdr is None:
        hdr = HDR
    cin_p = f"{62e-12*(1+cin_mismatch/2):.6e}"
    cin_n = f"{62e-12*(1-cin_mismatch/2):.6e}"
    return hdr + OTA + f"""
.model chsw SW(Ron=100 Roff=1G Vt=0.9 Vh=0.1)

VDD vdd 0 1.8

{input_src_extra if input_src_extra else f"Vip inp_ext 0 DC {vcm_inp_dc}"}
{'' if input_src_extra else f"Vin inn_ext 0 DC {vcm_inn_dc}"}

* Chopper clocks at fchop = {fchop:.0f} Hz
Vclk  clk  0 PULSE(0 1.8 0 1n 1n {0.5/fchop:.9e} {1/fchop:.9e})
Vclkb clkb 0 PULSE(1.8 0 0 1n 1n {0.5/fchop:.9e} {1/fchop:.9e})

* Input chopper (CH_in)
S_ip_d inp_ext inp_ch clk  0 chsw
S_in_d inn_ext inn_ch clk  0 chsw
S_ip_x inp_ext inn_ch clkb 0 chsw
S_in_x inn_ext inp_ch clkb 0 chsw

* Input coupling caps with {cin_mismatch*100:.2f}% mismatch
Cin_p inp_ch gp {cin_p}
Cin_n inn_ch gn {cin_n}

* DC bias
Gpb_p gp vcm cur='(v(gp)-v(vcm))/1e12'
Gpb_n gn vcm cur='(v(gn)-v(vcm))/1e12'
Vcm vcm 0 0.9

* Feedback caps (connected to OTA output, INSIDE chopper loop)
Cfb_p outp_ota gp 1p
Cfb_n outn_ota gn 1p

* DC feedback
Gfb_p gp outp_ota cur='(v(gp)-v(outp_ota))/1e12'
Gfb_n gn outn_ota cur='(v(gn)-v(outn_ota))/1e12'

* OTA
Xota gp gn outp_ota outn_ota vdd 0 fd_ota

* Output chopper (CH_out) — demodulates to baseband
S_op_d outp_ota outp clk  0 chsw
S_on_d outn_ota outn clk  0 chsw
S_op_x outp_ota outn clkb 0 chsw
S_on_x outn_ota outp clkb 0 chsw

* Load caps
CL_p outp 0 1p
CL_n outn 0 1p

.ic v(gp)=0.9 v(gn)=0.9 v(outp_ota)=0.9 v(outn_ota)=0.9 v(outp)=0.9 v(outn)=0.9

{extra}
"""


def make_unchopped_mismatched(hdr=None, cin_mismatch=0.001,
                              vcm_inp_dc=0.9, vcm_inn_dc=0.9,
                              input_src_extra="", extra=""):
    """Build CCIA WITHOUT choppers but WITH Cin mismatch (to demonstrate the problem)."""
    if hdr is None:
        hdr = HDR
    cin_p = f"{62e-12*(1+cin_mismatch/2):.6e}"
    cin_n = f"{62e-12*(1-cin_mismatch/2):.6e}"
    return hdr + OTA + f"""
VDD vdd 0 1.8

{input_src_extra if input_src_extra else f"Vip inp_ext 0 DC {vcm_inp_dc}"}
{'' if input_src_extra else f"Vin inn_ext 0 DC {vcm_inn_dc}"}

* Input coupling caps with {cin_mismatch*100:.2f}% mismatch (NO choppers)
Cin_p inp_ext gp {cin_p}
Cin_n inn_ext gn {cin_n}

* DC bias
Gpb_p gp vcm cur='(v(gp)-v(vcm))/1e12'
Gpb_n gn vcm cur='(v(gn)-v(vcm))/1e12'
Vcm vcm 0 0.9

* Feedback caps
Cfb_p outp gp 1p
Cfb_n outn gn 1p

* DC feedback
Gfb_p gp outp cur='(v(gp)-v(outp))/1e12'
Gfb_n gn outn cur='(v(gn)-v(outn))/1e12'

* OTA
Xota gp gn outp outn vdd 0 fd_ota

* Load caps
CL_p outp 0 1p
CL_n outn 0 1p

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
    print("\n>>> TB1: DC Gain (1 mV differential, transient 0.2s)")
    net = make_inamp(
        vcm_inp=0.9005, vcm_inn=0.8995,
        extra=f"""
.tran 0.5m 0.2

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


# ── TB3: CMRR with Chopping ──────────────────────────────────
def tb3_cmrr(diff_gain_db=35.8):
    """CMRR measurement using transient simulation with choppers + Cin mismatch.

    Architecture: system-level chopping moves CM-to-diff error from 60Hz to fchop±60Hz.
    Also runs without chopping to demonstrate the problem.
    """
    print("\n>>> TB3: CMRR with Chopping (0.1% Cin mismatch)")

    fchop = 10e3
    fcm = 60.0
    vcm_amp = 0.01  # 10 mV CM amplitude
    cin_mismatch = 0.001  # 0.1%
    t_sim = 0.5  # 500ms for good frequency resolution
    t_settle = 0.1  # Skip first 100ms

    results = {}

    # --- Test 1: WITHOUT chopping (should show CMRR failure) ---
    print("  [1] Without chopping (mismatch only):")
    net_unchop = make_unchopped_mismatched(
        cin_mismatch=cin_mismatch,
        input_src_extra=f"""Vip inp_ext 0 sin(0.9 {vcm_amp} {fcm})
Vin inn_ext 0 sin(0.9 {vcm_amp} {fcm})""",
        extra=f"""
.tran 10u {t_sim} uic

.control
run
wrdata {PLOTS_DIR}/cmrr_unchopped_raw.csv v(outp)-v(outn)
quit
.endc
.end
""")
    out = run_ngspice(net_unchop, timeout=300)
    cmrr_unchop = _analyze_cmrr_transient(
        f'{PLOTS_DIR}/cmrr_unchopped_raw.csv', fcm, vcm_amp,
        diff_gain_db, t_settle, "unchopped")
    if cmrr_unchop is not None:
        results["cmrr_unchopped_db"] = cmrr_unchop
        print(f"      CMRR (unchopped) = {cmrr_unchop:.1f} dB  {'PASS' if cmrr_unchop > 100 else 'FAIL'}")

    # --- Test 2: WITH chopping (should show CMRR improvement) ---
    print("  [2] With chopping (fchop=10kHz):")
    net_chop = make_chopped_inamp(
        cin_mismatch=cin_mismatch, fchop=fchop,
        input_src_extra=f"""Vip inp_ext 0 sin(0.9 {vcm_amp} {fcm})
Vin inn_ext 0 sin(0.9 {vcm_amp} {fcm})""",
        extra=f"""
.tran 5u {t_sim} uic

.control
run
wrdata {PLOTS_DIR}/cmrr_chopped_raw.csv v(outp)-v(outn)
quit
.endc
.end
""")
    out = run_ngspice(net_chop, timeout=600)
    cmrr_chop = _analyze_cmrr_transient(
        f'{PLOTS_DIR}/cmrr_chopped_raw.csv', fcm, vcm_amp,
        diff_gain_db, t_settle, "chopped")
    if cmrr_chop is not None:
        results["cmrr_chopped_db"] = cmrr_chop
        print(f"      CMRR (chopped)   = {cmrr_chop:.1f} dB  {'PASS' if cmrr_chop > 100 else 'FAIL'}")

    # Generate CMRR comparison plot
    _plot_cmrr_comparison()

    return results


def _analyze_cmrr_transient(csv_path, fcm, vcm_amp, diff_gain_db, t_settle, label):
    """Analyze transient output to extract CMRR at fcm Hz."""
    try:
        data = np.loadtxt(csv_path, skiprows=1)
        t = data[:, 0]
        v = data[:, 1]

        # Skip initial settling
        mask = t > t_settle
        t_ss = t[mask]
        v_ss = v[mask]

        if len(v_ss) < 100:
            print(f"      {label}: insufficient data points")
            return None

        # Use FFT to find the fcm Hz component
        dt = np.median(np.diff(t_ss))
        N = len(v_ss)
        # Apply Hann window to reduce spectral leakage
        window = np.hanning(N)
        v_windowed = v_ss * window
        fft_v = np.fft.rfft(v_windowed)
        freqs = np.fft.rfftfreq(N, dt)

        # Find the fcm Hz bin
        idx_fcm = np.argmin(np.abs(freqs - fcm))

        # Amplitude (corrected for Hann window factor of 2)
        amp_fcm = 4 * np.abs(fft_v[idx_fcm]) / N  # 4 = 2(rfft) * 2(hann correction)

        # CM-to-diff gain at fcm
        cm_to_diff_gain = amp_fcm / vcm_amp
        if cm_to_diff_gain < 1e-15:
            cm_to_diff_db = -300  # Effectively zero
        else:
            cm_to_diff_db = 20 * np.log10(cm_to_diff_gain)

        # CMRR = differential_gain / cm_to_diff_gain
        cmrr_db = diff_gain_db - cm_to_diff_db

        # Debug info
        print(f"      {label}: CM-to-diff at {fcm}Hz = {cm_to_diff_db:.1f} dB, "
              f"amp = {amp_fcm*1e6:.3f} uV, "
              f"diff_gain = {diff_gain_db:.1f} dB")

        return cmrr_db

    except Exception as e:
        print(f"      {label}: analysis error: {e}")
        return None


def _plot_cmrr_comparison():
    """Generate matplotlib plot comparing chopped vs unchopped CMRR."""
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt

        fig, axes = plt.subplots(2, 1, figsize=(10, 8))

        for idx, (fname, label) in enumerate([
            (f'{PLOTS_DIR}/cmrr_unchopped_raw.csv', 'Unchopped (0.1% Cin mismatch)'),
            (f'{PLOTS_DIR}/cmrr_chopped_raw.csv', 'Chopped (fchop=10kHz, 0.1% Cin mismatch)')
        ]):
            try:
                data = np.loadtxt(fname, skiprows=1)
                t = data[:, 0]
                v = data[:, 1]

                # Time domain
                axes[0].plot(t*1000, v*1e6, linewidth=0.5, label=label)

                # FFT (skip first 100ms)
                mask = t > 0.1
                t_ss = t[mask]
                v_ss = v[mask]
                dt = np.median(np.diff(t_ss))
                N = len(v_ss)
                window = np.hanning(N)
                fft_v = np.fft.rfft(v_ss * window)
                freqs = np.fft.rfftfreq(N, dt)
                amp = 4 * np.abs(fft_v) / N

                # Plot spectrum up to 500 Hz
                fmask = freqs < 500
                axes[1].semilogy(freqs[fmask], amp[fmask]*1e6, linewidth=0.8, label=label)
            except Exception:
                pass

        axes[0].set_xlabel('Time (ms)')
        axes[0].set_ylabel('Diff Output (uV)')
        axes[0].set_title('CMRR Test: 10mV CM at 60Hz, 0.1% Cin Mismatch')
        axes[0].legend()
        axes[0].grid(True, alpha=0.3)

        axes[1].axvline(60, color='r', linestyle='--', alpha=0.5, label='60 Hz')
        axes[1].set_xlabel('Frequency (Hz)')
        axes[1].set_ylabel('Output Amplitude (uV)')
        axes[1].set_title('Output Spectrum — 60Hz Component Shows CMRR')
        axes[1].legend()
        axes[1].grid(True, alpha=0.3)
        axes[1].set_xlim(0, 500)

        plt.tight_layout()
        plt.savefig(f'{PLOTS_DIR}/cmrr_vs_freq.png', dpi=150)
        print("  CMRR comparison plot saved")
    except Exception as e:
        print(f"  CMRR plot error: {e}")


# ── TB4: Noise ────────────────────────────────────────────────
def tb4_noise():
    print("\n>>> TB4: Input-Referred Noise (0.5-150 Hz)")
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
        print(f"  Input-referred noise (0.5-150 Hz) = {inoise*1e6:.3f} uVrms")
    if onoise is not None:
        print(f"  Output noise (0.5-150 Hz) = {onoise*1e6:.3f} uVrms")
    return {"inoise_total": inoise, "onoise_total": onoise} if inoise is not None else None


# ── TB5: Offset ───────────────────────────────────────────────
def tb5_offset():
    print("\n>>> TB5: Input Offset")
    net = make_inamp(
        extra=f"""
.tran 0.5m 0.2

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
.tran 0.5m 0.2

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
        print(f"  Isupply={abs(idd)*1e6:.2f} uA  Power={abs(pwr):.2f} uW")
        return {"power_uw": abs(pwr), "idd_ua": abs(idd) * 1e6}
    return None


# ── TB7: Realistic ECG Transient ──────────────────────────────
def tb7_ecg_transient():
    """Synthetic ECG + 60 Hz interference + 300 mV electrode offset, WITH chopping."""
    print("\n>>> TB7: Realistic ECG Transient (with chopping)")

    net = make_chopped_inamp(
        cin_mismatch=0.001,
        fchop=10e3,
        input_src_extra=f"""* Common-mode: 1.2V (0.9V + 300mV electrode offset) + 2mV 60Hz
Vcm_sig vcm_sig 0 sin(1.2 0.002 60 0 0)

* ECG signal: simplified QRS complex at 72 BPM
Vecg ecg_sig 0 pulse(0 0.001 0 0.005 0.005 0.04 0.833)

* Positive input: CM + ECG/2
Einp inp_ext 0 vol='v(vcm_sig) + v(ecg_sig)/2'
* Negative input: CM - ECG/2
Einn inn_ext 0 vol='v(vcm_sig) - v(ecg_sig)/2'""",
        extra=f"""
.tran 5u 0.3

.control
run
let vdiff_out = v(outp) - v(outn)
let maxout = maximum(v(outp))
let minout = minimum(v(outn))
print maxout minout

wrdata {PLOTS_DIR}/ecg_transient_raw.csv vdiff_out
quit
.endc
.end
""")
    out = run_ngspice(net, timeout=600)
    print(out[-1500:])
    maxv = grab(out, "maxout")
    minv = grab(out, "minout")
    if maxv is not None:
        print(f"  Max output: {maxv:.4f} V")
        print(f"  Min output: {minv:.4f} V")
        sat = maxv > 1.6 or minv < 0.2
        if sat:
            print("  WARNING: Output saturated!")
        else:
            print("  Output within valid range (0.2-1.6V)")

        # Generate matplotlib plot
        try:
            import matplotlib
            matplotlib.use('Agg')
            import matplotlib.pyplot as plt
            data = np.loadtxt(f'{PLOTS_DIR}/ecg_transient_raw.csv', skiprows=1)
            t = data[:, 0]
            v = data[:, 1]
            fig, ax = plt.subplots(figsize=(10, 4))
            ax.plot(t*1000, v*1000, 'b-', linewidth=0.8)
            ax.set_xlabel('Time (ms)')
            ax.set_ylabel('Differential Output (mV)')
            ax.set_title('Chopped ECG Transient: 1mV QRS + 2mV 60Hz CM + 300mV Offset')
            ax.grid(True, alpha=0.3)
            plt.tight_layout()
            plt.savefig(f'{PLOTS_DIR}/ecg_transient.png', dpi=150)
            print("  ECG plot saved")
        except Exception as e:
            print(f"  Plot error: {e}")

        return {"max_out": maxv, "min_out": minv, "saturated": sat}
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
    print("SKY130 Chopper InAmp — CCIA with System-Level Chopping")
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

    diff_gain_db = meas.get("gain_db", 35.8)

    # TB3: CMRR with chopping + mismatch (transient)
    r = tb3_cmrr(diff_gain_db)
    if r and "cmrr_chopped_db" in r:
        meas["cmrr_60hz_db"] = r["cmrr_chopped_db"]
        print(f"  CMRR (chopped, 0.1% mismatch) = {r['cmrr_chopped_db']:.1f} dB")
        if "cmrr_unchopped_db" in r:
            print(f"  CMRR (unchopped, 0.1% mismatch) = {r['cmrr_unchopped_db']:.1f} dB")
            print(f"  Chopping improvement: {r['cmrr_chopped_db'] - r['cmrr_unchopped_db']:.1f} dB")

    # TB4: Noise
    r = tb4_noise()
    if r and "inoise_total" in r:
        meas["input_referred_noise_uvrms"] = r["inoise_total"] * 1e6
        print(f"  Input-referred noise = {r['inoise_total']*1e6:.3f} uVrms")

    # TB5: Offset
    r = tb5_offset()
    if r:
        gain_lin = 10 ** (diff_gain_db / 20) if diff_gain_db > 0 else 1
        meas["input_offset_uv"] = abs(r["output_offset_v"]) / gain_lin * 1e6
        print(f"  Input offset = {meas['input_offset_uv']:.1f} uV")

    # TB6: Electrode offset
    tb6_electrode()

    # TB7: ECG transient (with chopping)
    tb7_ecg_transient()

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

    # Phase B: PVT corners if score = 1.0
    if sc >= 1.0:
        tb8_pvt_corners()

    return sc


# ── TB8: PVT Corner Analysis ─────────────────────────────────
def tb8_pvt_corners():
    """Run gain and noise at all PVT corners."""
    print("\n" + "=" * 60)
    print("TB8: PVT CORNER ANALYSIS")
    print("=" * 60)

    corners = ["tt", "ss", "ff", "sf", "fs"]
    temps = [-40, 27, 125]
    results = []

    for corner in corners:
        for temp in temps:
            hdr_pvt = f'.lib "/home/ubuntu/workspace/sky130_models/sky130.lib.spice" {corner}\n'
            # AC gain + BW at this corner/temp
            net = hdr_pvt + OTA + f"""
.param cin_v  = 62p
.param cfb_v  = 1p
.temp {temp}

VDD vdd 0 1.8
Vip inp_ext 0 DC 0.9 AC 0.5
Vin inn_ext 0 DC 0.9 AC -0.5
Cin_p inp_ext gp {{cin_v}}
Cin_n inn_ext gn {{cin_v}}
Gpb_p gp vcm cur='(v(gp)-v(vcm))/1e12'
Gpb_n gn vcm cur='(v(gn)-v(vcm))/1e12'
Vcm vcm 0 0.9
Cfb_p outp gp {{cfb_v}}
Cfb_n outn gn {{cfb_v}}
Gfb_p gp outp cur='(v(gp)-v(outp))/1e12'
Gfb_n gn outn cur='(v(gn)-v(outn))/1e12'
Xota gp gn outp outn vdd 0 fd_ota
CL_p outp 0 1p
CL_n outn 0 1p
.ic v(gp)=0.9 v(gn)=0.9 v(outp)=0.9 v(outn)=0.9

.ac dec 50 0.01 100Meg

.control
run
let vdiff = v(outp) - v(outn)
meas ac peak_gain MAX vdb(vdiff) from=1 to=1k
meas ac bw_3db WHEN vdb(vdiff)='peak_gain-3' FALL=1
print peak_gain bw_3db
quit
.endc
.end
"""
            out = run_ngspice(net)
            gain = grab(out, "peak_gain")
            bw = grab(out, "bw_3db")

            # Noise at this corner
            net_noise = hdr_pvt + OTA + f"""
.param cin_v  = 62p
.param cfb_v  = 1p
.temp {temp}

VDD vdd 0 1.8
Vip inp_ext 0 DC 0.9 AC 1
Vin inn_ext 0 DC 0.9
Cin_p inp_ext gp {{cin_v}}
Cin_n inn_ext gn {{cin_v}}
Gpb_p gp vcm cur='(v(gp)-v(vcm))/1e12'
Gpb_n gn vcm cur='(v(gn)-v(vcm))/1e12'
Vcm vcm 0 0.9
Cfb_p outp gp {{cfb_v}}
Cfb_n outn gn {{cfb_v}}
Gfb_p gp outp cur='(v(gp)-v(outp))/1e12'
Gfb_n gn outn cur='(v(gn)-v(outn))/1e12'
Xota gp gn outp outn vdd 0 fd_ota
CL_p outp 0 1p
CL_n outn 0 1p
.ic v(gp)=0.9 v(gn)=0.9 v(outp)=0.9 v(outn)=0.9

.noise v(outp,outn) Vip dec 100 0.5 150

.control
run
setplot noise2
print inoise_total
quit
.endc
.end
"""
            out_n = run_ngspice(net_noise)
            inoise = grab(out_n, "inoise_total")

            noise_uv = inoise * 1e6 if inoise else None
            gain_pass = gain is not None and gain > 34
            noise_pass = noise_uv is not None and noise_uv < 1.5
            status = "PASS" if (gain_pass and noise_pass) else "FAIL"

            g_str = f"{gain:.1f}" if gain else "N/A"
            n_str = f"{noise_uv:.2f}" if noise_uv else "N/A"
            bw_str = f"{bw/1e6:.2f}M" if bw else "N/A"

            print(f"  {corner:3s} {temp:+4d}C: gain={g_str:>6s}dB  noise={n_str:>6s}uV  BW={bw_str:>8s}  [{status}]")
            results.append({
                "corner": corner, "temp": temp,
                "gain_db": gain, "noise_uvrms": noise_uv, "bw_hz": bw,
                "pass": status == "PASS"
            })

    n_pass = sum(1 for r in results if r["pass"])
    n_total = len(results)
    print(f"\n  PVT: {n_pass}/{n_total} corners pass")

    # Save summary
    with open(f"{PLOTS_DIR}/pvt_summary.txt", "w") as f:
        f.write("corner temp gain_db noise_uvrms bw_hz pass\n")
        for r in results:
            f.write(f"{r['corner']} {r['temp']} {r['gain_db']} {r['noise_uvrms']} {r['bw_hz']} {r['pass']}\n")

    # Generate PVT summary plot
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))

        for corner in corners:
            cr = [r for r in results if r['corner'] == corner]
            ts = [r['temp'] for r in cr]
            ns = [r['noise_uvrms'] for r in cr if r['noise_uvrms']]
            gs = [r['gain_db'] for r in cr if r['gain_db']]
            if ns:
                ax1.plot(ts[:len(ns)], ns, 'o-', label=corner)
            if gs:
                ax2.plot(ts[:len(gs)], gs, 'o-', label=corner)

        ax1.axhline(1.5, color='r', linestyle='--', label='Spec limit')
        ax1.set_xlabel('Temperature (C)')
        ax1.set_ylabel('Input-referred noise (uVrms)')
        ax1.set_title('PVT Noise')
        ax1.legend()
        ax1.grid(True, alpha=0.3)

        ax2.axhline(34, color='r', linestyle='--', label='Spec limit')
        ax2.set_xlabel('Temperature (C)')
        ax2.set_ylabel('Gain (dB)')
        ax2.set_title('PVT Gain')
        ax2.legend()
        ax2.grid(True, alpha=0.3)

        plt.tight_layout()
        plt.savefig(f'{PLOTS_DIR}/pvt_summary.png', dpi=150)
        print("  PVT plot saved")
    except Exception as e:
        print(f"  PVT plot error: {e}")

    return results


if __name__ == "__main__":
    main()
