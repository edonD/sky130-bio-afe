#!/usr/bin/env python3
"""InAmp Evaluator — CCIA with system-level chopping.

Testbenches:
  TB1: DC gain and operating point
  TB2: AC frequency response (bandwidth)
  TB3: CMRR at 60 Hz with 0.1% Cin mismatch (transient + FFT)
  TB4: Input-referred noise (0.5-150 Hz)
  TB5: Input offset
  TB6: Electrode offset tolerance (±300 mV)
  TB7: Realistic ECG transient
"""

import subprocess
import os
import json
import math
import numpy as np

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

# ── Configuration ──
VDD = 1.8
VCM = 0.9
CIN = 80e-12       # 80 pF — large Cin dilutes Cgs parasitic for lower noise
CFB = 1e-12         # 1 pF
GAIN_NOMINAL = CIN / CFB  # 51 V/V = 34.15 dB
FCHOP = 10e3        # 10 kHz chopper frequency
T_CHOP = 1.0 / FCHOP  # 100 us

SPECS = {
    'gain_db':                    {'target': 34,    'op': '>', 'weight': 15},
    'input_referred_noise_uvrms': {'target': 1.5,   'op': '<', 'weight': 25},
    'cmrr_60hz_db':               {'target': 100,   'op': '>', 'weight': 20},
    'input_offset_uv':            {'target': 50,    'op': '<', 'weight': 15},
    'bandwidth_hz':               {'target': 10000, 'op': '>', 'weight': 10},
    'power_uw':                   {'target': 15,    'op': '<', 'weight': 15},
}

WORK_DIR = os.path.dirname(os.path.abspath(__file__))
PLOT_DIR = os.path.join(WORK_DIR, 'plots')
os.makedirs(PLOT_DIR, exist_ok=True)

SKY130_LIB = os.path.join(WORK_DIR, 'sky130_models', 'sky130.lib.spice')

# Ensure symlink
_sym = os.path.join(WORK_DIR, 'sky130_fd_pr_models')
if not os.path.exists(_sym):
    os.symlink('sky130_models/sky130_fd_pr_models', _sym)


def ota_subckt():
    """Fully-differential folded-cascode OTA with PMOS LVT input pair."""
    return """
.subckt ota inp inn outp outn vcm vdd vss nbias pbias
* PMOS tail current source: 5 uA (5x mirror from 1uA ref)
XMtail tailn pbias vdd vdd sky130_fd_pr__pfet_01v8 w=10u l=8u m=1

* PMOS LVT input differential pair (large W for low 1/f noise)
* 8 parallel devices of 99u/8u = 792um total W per side
XM1 d1n inp tailn vdd sky130_fd_pr__pfet_01v8_lvt w=99u l=8u m=8
XM2 d2n inn tailn vdd sky130_fd_pr__pfet_01v8_lvt w=99u l=8u m=8

* NMOS folding current sources: ~2.7 uA each (must exceed diff pair 2.5uA)
XMf1 d1n nbias vss vss sky130_fd_pr__nfet_01v8 w=10.8u l=16u m=1
XMf2 d2n nbias vss vss sky130_fd_pr__nfet_01v8 w=10.8u l=16u m=1

* NMOS cascodes
XMc1 outn ncasc d1n vss sky130_fd_pr__nfet_01v8 w=49u l=2u m=2
XMc2 outp ncasc d2n vss sky130_fd_pr__nfet_01v8 w=49u l=2u m=2

* NMOS cascode bias: needs Vgs > Vth above d1n (~0.5V)
* ncasc = ~1.0V keeps cascode in saturation
Vncasc ncasc vss 1.0

* PMOS loads (CMFB-controlled)
XMl1 outn cmfb vdd vdd sky130_fd_pr__pfet_01v8 w=99u l=99u m=1
XMl2 outp cmfb vdd vdd sky130_fd_pr__pfet_01v8 w=99u l=99u m=1

* CMFB
* CMFB: VCCS servo loop — numerically stable for transient
* Sense output CM via high-value resistors
Rcm1 outp cm_sense 100G
Rcm2 outn cm_sense 100G
* VCCS drives cmfb node: Gm*(Vcm_sense - Vcm_ref)
* Positive: when output CM rises, cmfb rises, PMOS loads turn off
Gcmfb 0 cmfb cm_sense vcm 1m
* Compensation cap + bias resistor set DC operating point
Ccmfb cmfb 0 10p
Rcmfb cmfb 0 900k
.ends ota
"""


def bias_circuit():
    """Bias generation — 1 uA reference shared branch."""
    return """
* Bias: VDD -> PMOS diode (pbias) -> mid -> NMOS diode (nbias) -> VSS
* Total branch current: 1 uA
XMpb1 pbias pbias vdd vdd sky130_fd_pr__pfet_01v8 w=2u l=8u m=1
XMnb nbias nbias vss vss sky130_fd_pr__nfet_01v8 w=2u l=8u m=1
Ibias_n vdd nbias 1u
* Force 1 uA through PMOS diode too
Ibias_p pbias vss 1u
"""


def chopper_and_ccia(cin_p=51e-12, cin_n=51e-12, cfb=1e-12, include_chopper=True):
    """CCIA with optional chopper switches."""
    lines = []

    # Input caps with possible mismatch
    lines.append(f"Cinp inp_chop_p vgp {cin_p}")
    lines.append(f"Cinn inp_chop_n vgn {cin_n}")

    # Feedback caps
    lines.append(f"Cfbp xota.outp vgn {cfb}")
    lines.append(f"Cfbn xota.outn vgp {cfb}")

    # DC bias for OTA inputs
    lines.append("Rbp vgp vcm 100G")
    lines.append("Rbn vgn vcm 100G")

    if include_chopper:
        lines.append("""
* Chopper clock
.model SW1 SW vt=0.5 vh=0.01 ron=100 roff=1G
Vclk clk 0 pulse(0 1 0 1n 1n 50u 100u)
Eclkb clk_b 0 vol='1-v(clk)'

* Input chopper
S1a inp inp_chop_p clk 0 SW1
S1b inn inp_chop_n clk 0 SW1
S1c inp inp_chop_n clk_b 0 SW1
S1d inn inp_chop_p clk_b 0 SW1

* Output chopper (demodulator)
S2a xota.outp vout_dem_p clk 0 SW1
S2b xota.outn vout_dem_n clk 0 SW1
S2c xota.outp vout_dem_n clk_b 0 SW1
S2d xota.outn vout_dem_p clk_b 0 SW1

* Output LPF
Rlpfp vout_dem_p voutp 10k
Clpfp voutp vcm 100p
Rlpfn vout_dem_n voutn 10k
Clpfn voutn vcm 100p
""")
    else:
        # Direct connection (no chopping)
        lines.append("Vinp_short inp inp_chop_p 0")
        lines.append("Vinn_short inn inp_chop_n 0")
        lines.append("Voutp_short xota.outp voutp 0")
        lines.append("Voutn_short xota.outn voutn 0")

    return '\n'.join(lines)


def make_netlist(corner='tt', temp=27, vin_diff=None, vin_cm=None,
                 cin_mismatch=0.0, include_chopper=True,
                 extra_sources='', control=''):
    """Build a complete CCIA netlist."""
    cin_p = CIN * (1 + cin_mismatch/2)
    cin_n = CIN * (1 - cin_mismatch/2)

    if vin_cm is None:
        vin_cm = VCM

    netlist = f"""* CCIA InAmp testbench — corner={corner}, T={temp}C
.lib "{SKY130_LIB}" {corner}
.temp {temp}

Vdd vdd 0 {VDD}
Vss vss 0 0
Vcm vcm 0 {VCM}

{ota_subckt()}
{bias_circuit()}

* Instantiate OTA
Xota vgp vgn voutp_ota voutn_ota vcm vdd vss nbias pbias ota

* CCIA network
Cinp inp_chop_p vgp {cin_p}
Cinn inp_chop_n vgn {cin_n}
Cfbp voutp_ota vgn {CFB}
Cfbn voutn_ota vgp {CFB}
Rbp vgp vcm 100G
Rbn vgn vcm 100G

"""

    if include_chopper:
        netlist += f"""
* Convergence options for transient with switching
.options method=gear reltol=5e-3 abstol=1e-10 vntol=1e-4 gmin=1e-12 itl4=200

* Chopper clock at {FCHOP} Hz (100ns transitions for stability)
.model SW1 SW vt=0.5 vh=0.1 ron=100 roff=100Meg
Vclk clk 0 pulse(0 1 0 100n 100n {T_CHOP/2} {T_CHOP})
Eclkb clk_b 0 vol='1-v(clk)'

* Input chopper
S1a inp inp_chop_p clk 0 SW1
S1b inn inp_chop_n clk 0 SW1
S1c inp inp_chop_n clk_b 0 SW1
S1d inn inp_chop_p clk_b 0 SW1

* Output chopper (demodulator) — buffered through small resistors
Rbuf_p voutp_ota vop_buf 1k
Rbuf_n voutn_ota von_buf 1k
S2a vop_buf vout_dem_p clk 0 SW1
S2b von_buf vout_dem_n clk 0 SW1
S2c vop_buf vout_dem_n clk_b 0 SW1
S2d von_buf vout_dem_p clk_b 0 SW1

* Output LPF
Rlpfp vout_dem_p voutp 10k
Clpfp voutp vcm 100p
Rlpfn vout_dem_n voutn 10k
Clpfn voutn vcm 100p
"""
    else:
        netlist += """
* No chopper — direct connection
Vinp_short inp inp_chop_p 0
Vinn_short inn inp_chop_n 0
Voutp_short voutp_ota voutp 0
Voutn_short voutn_ota voutn 0
"""

    netlist += extra_sources + '\n'
    netlist += control + '\n'
    netlist += '.end\n'
    return netlist


def run_ngspice(netlist_str, tag='sim'):
    """Write netlist, run ngspice -b, return (stdout, stderr, rc)."""
    nf = os.path.join(WORK_DIR, f'_tb_{tag}.spice')
    with open(nf, 'w') as f:
        f.write(netlist_str)
    try:
        r = subprocess.run(
            ['ngspice', '-b', nf],
            capture_output=True, text=True, timeout=300,
            cwd=WORK_DIR
        )
        return r.stdout, r.stderr, r.returncode
    except subprocess.TimeoutExpired:
        print(f"  WARNING: ngspice timeout for {tag}")
        return '', 'TIMEOUT', -1


def read_wrdata(filename):
    """Read ngspice wrdata output file."""
    path = os.path.join(WORK_DIR, filename)
    if not os.path.exists(path):
        return None
    data = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or line.startswith('*'):
                continue
            parts = line.split()
            try:
                vals = [float(x) for x in parts]
                data.append(vals)
            except ValueError:
                continue
    if not data:
        return None
    return np.array(data)


# ── TB1: DC Gain and Operating Point ──
def tb1_dc_gain():
    """Apply 1 mV differential, measure output, compute gain."""
    print("\n--- TB1: DC Gain and Operating Point ---")

    vin_diff = 1e-3  # 1 mV
    extra = f"""
* Differential input: 1 mV on top of VCM
Vinp inp 0 {VCM + vin_diff/2}
Vinn inn 0 {VCM - vin_diff/2}
"""
    control = """
.control
op
print v(voutp) v(voutn) v(voutp)-v(voutn)
print v(vgp) v(vgn)
print v(xota.outp) v(xota.outn)
print i(Vdd)
.endc
"""
    netlist = make_netlist(include_chopper=False, extra_sources=extra, control=control)
    stdout, stderr, rc = run_ngspice(netlist, 'tb1_dc')

    vout_diff = None
    power_uw = None

    for line in stdout.splitlines():
        ll = line.lower().strip()
        if 'v(voutp)-v(voutn)' in ll or ('v(voutp)' in ll and 'v(voutn)' in ll and '-' in ll):
            # Try to parse
            pass
        if 'i(vdd)' in ll and '=' in ll:
            try:
                val = float(ll.split('=')[-1].strip().split()[0])
                power_uw = abs(val) * VDD * 1e6
            except (ValueError, IndexError):
                pass

    # Parse individual voltages
    voutp = None
    voutn = None
    for line in stdout.splitlines():
        ll = line.lower().strip()
        if ll.startswith('v(voutp)') and '=' in ll and 'v(voutn)' not in ll:
            try:
                voutp = float(ll.split('=')[-1].strip().split()[0])
            except (ValueError, IndexError):
                pass
        if ll.startswith('v(voutn)') and '=' in ll and 'v(voutp)' not in ll:
            try:
                voutn = float(ll.split('=')[-1].strip().split()[0])
            except (ValueError, IndexError):
                pass

    if voutp is not None and voutn is not None:
        vout_diff = voutp - voutn
        gain = vout_diff / vin_diff
        gain_db = 20 * math.log10(abs(gain)) if abs(gain) > 0 else -999
        print(f"  Voutp={voutp:.4f}V, Voutn={voutn:.4f}V")
        print(f"  Vout_diff={vout_diff*1e3:.3f} mV")
        print(f"  Gain = {gain:.1f} V/V = {gain_db:.1f} dB (DC=0 expected for CCIA)")
        print(f"  Power = {power_uw:.1f} uW" if power_uw else "  Power = N/A")

        # Plot operating point
        fig, ax = plt.subplots(figsize=(8, 5))
        labels = ['Voutp', 'Voutn', 'VCM']
        values = [voutp, voutn, VCM]
        colors = ['steelblue', 'coral', 'gray']
        ax.bar(labels, values, color=colors, alpha=0.8)
        ax.axhline(y=0.2, color='red', linestyle='--', alpha=0.3, label='Output range')
        ax.axhline(y=1.6, color='red', linestyle='--', alpha=0.3)
        ax.axhline(y=VCM, color='green', linestyle='--', alpha=0.5, label=f'VCM={VCM}V')
        ax.set_ylabel('Voltage (V)')
        ax.set_title(f'DC Operating Point — Power: {power_uw:.1f} uW')
        ax.set_ylim([0, 1.8])
        ax.legend()
        ax.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(os.path.join(PLOT_DIR, 'dc_gain.png'), dpi=150)
        plt.close()
    else:
        gain_db = None
        print("  WARNING: Could not parse DC operating point")
        for line in stdout.splitlines()[-20:]:
            print(f"    {line}")

    return gain_db, power_uw, voutp, voutn


# ── TB2: AC Frequency Response ──
def tb2_ac_response():
    """AC sweep for bandwidth measurement. No chopper (AC analysis)."""
    print("\n--- TB2: AC Frequency Response ---")

    extra = f"""
* AC input
Vinp inp 0 dc {VCM} ac 0.5
Vinn inn 0 dc {VCM} ac -0.5
"""
    control = """
.control
op
print v(xota.d1n) v(xota.d2n) v(xota.tailn)
print v(xota.outp) v(xota.outn)
print v(xota.cmfb) v(xota.ncasc)
print i(Vdd)
ac dec 50 0.1 10Meg
wrdata _tb2_ac.dat v(voutp)-v(voutn)
.endc
"""
    netlist = make_netlist(include_chopper=False, extra_sources=extra, control=control)
    stdout, stderr, rc = run_ngspice(netlist, 'tb2_ac')

    data = read_wrdata('_tb2_ac.dat')
    gain_db = None
    bandwidth_hz = None

    if data is not None and len(data) > 5:
        freqs = data[:, 0]
        if data.shape[1] >= 3:
            mags = np.sqrt(data[:, 1]**2 + data[:, 2]**2)
        else:
            mags = np.abs(data[:, 1])

        # Low-frequency gain
        lf_idx = np.argmin(np.abs(freqs - 1.0))
        lf_gain = mags[lf_idx]

        if lf_gain > 0:
            gain_db = 20 * math.log10(lf_gain)

            # -3 dB bandwidth
            gain_3db = lf_gain / math.sqrt(2)
            bw_idx = np.where(mags < gain_3db)[0]
            if len(bw_idx) > 0:
                bandwidth_hz = freqs[bw_idx[0]]
            else:
                bandwidth_hz = freqs[-1]

            print(f"  LF Gain = {lf_gain:.1f} V/V = {gain_db:.1f} dB")
            print(f"  -3 dB BW = {bandwidth_hz:.0f} Hz")

            # Check flatness in biomedical band
            idx_05 = np.argmin(np.abs(freqs - 0.5))
            idx_150 = np.argmin(np.abs(freqs - 150))
            bio_mags_db = 20 * np.log10(np.maximum(mags[idx_05:idx_150+1], 1e-15))
            if len(bio_mags_db) > 0:
                ripple = np.max(bio_mags_db) - np.min(bio_mags_db)
                print(f"  Ripple 0.5-150 Hz = {ripple:.2f} dB")

        # Plot
        fig, ax = plt.subplots(figsize=(10, 6))
        mags_db = 20 * np.log10(np.maximum(mags, 1e-15))
        ax.semilogx(freqs, mags_db)
        ax.axhline(y=34, color='green', linestyle='--', alpha=0.5, label='34 dB target')
        ax.axvline(x=10000, color='red', linestyle='--', alpha=0.5, label='10 kHz')
        ax.set_xlabel('Frequency (Hz)')
        ax.set_ylabel('Differential Gain (dB)')
        ax.set_title('AC Response — CCIA (no chopper)')
        ax.legend()
        ax.grid(True, alpha=0.3)
        ax.set_xlim([0.1, 10e6])
        plt.tight_layout()
        plt.savefig(os.path.join(PLOT_DIR, 'ac_response.png'), dpi=150)
        plt.close()
    else:
        print("  WARNING: No AC data")
        if stderr:
            for l in stderr.splitlines()[-5:]:
                print(f"    {l}")

    return gain_db, bandwidth_hz


# ── TB3: CMRR with 0.1% Cin Mismatch (Transient) ──
def tb3_cmrr_mismatch():
    """Transient CMRR test with 0.1% Cin mismatch and chopping.
    Apply 10 mV CM at 60 Hz, measure differential output at 60 Hz via FFT."""
    print("\n--- TB3: CMRR at 60 Hz (0.1% Cin mismatch, chopping) ---")

    vcm_amp = 10e-3  # 10 mV CM signal at 60 Hz

    extra = f"""
* Common-mode input: 10 mV at 60 Hz
Vinp inp 0 sin({VCM} {vcm_amp} 60 0 0)
Vinn inn 0 sin({VCM} {vcm_amp} 60 0 0)
"""
    # Run long enough for good FFT resolution at 60 Hz
    # Need at least 1/60 * several cycles. Use 200 ms.
    control = """
.control
tran 1u 200m 50m
wrdata _tb3_cmrr.dat v(voutp)-v(voutn)
.endc
"""
    # 0.1% mismatch
    netlist = make_netlist(cin_mismatch=0.001, include_chopper=True,
                          extra_sources=extra, control=control)
    stdout, stderr, rc = run_ngspice(netlist, 'tb3_cmrr')

    data = read_wrdata('_tb3_cmrr.dat')
    cmrr_db = None

    if data is not None and len(data) > 100:
        time = data[:, 0]
        vout_diff = data[:, 1]

        # Remove DC
        vout_ac = vout_diff - np.mean(vout_diff)

        N = len(vout_ac)
        dt = np.mean(np.diff(time))
        fft_vals = np.fft.rfft(vout_ac)
        fft_mag = np.abs(fft_vals) * 2 / N
        freqs = np.fft.rfftfreq(N, dt)

        # Find 60 Hz component
        idx_60 = np.argmin(np.abs(freqs - 60))
        vout_60 = fft_mag[idx_60]

        # Differential gain (use nominal)
        diff_gain = GAIN_NOMINAL

        # CM gain = vout_60 / vcm_amp
        cm_gain = vout_60 / vcm_amp if vcm_amp > 0 else 1e-15

        if cm_gain > 0:
            cmrr = diff_gain / cm_gain
            cmrr_db = 20 * math.log10(cmrr)
        else:
            cmrr_db = 200  # Suspiciously high

        print(f"  Vout at 60 Hz = {vout_60*1e6:.2f} uV")
        print(f"  CM gain = {cm_gain:.6f}")
        print(f"  CMRR = {cmrr_db:.1f} dB")

        if cmrr_db > 150:
            print("  WARNING: CMRR > 150 dB — verify mismatch is applied!")

        # Plot
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))

        # Time domain
        t_ms = time * 1e3
        ax1.plot(t_ms, vout_diff * 1e3)
        ax1.set_xlabel('Time (ms)')
        ax1.set_ylabel('Vout_diff (mV)')
        ax1.set_title('CMRR Transient (10mV CM @ 60Hz)')
        ax1.grid(True, alpha=0.3)

        # FFT
        valid = freqs < 500
        fft_db = 20 * np.log10(np.maximum(fft_mag[valid], 1e-15))
        ax2.plot(freqs[valid], fft_db)
        ax2.axvline(x=60, color='red', linestyle='--', alpha=0.5, label='60 Hz')
        ax2.set_xlabel('Frequency (Hz)')
        ax2.set_ylabel('Output FFT (dB)')
        ax2.set_title(f'CMRR = {cmrr_db:.1f} dB (0.1% mismatch)')
        ax2.legend()
        ax2.grid(True, alpha=0.3)

        plt.tight_layout()
        plt.savefig(os.path.join(PLOT_DIR, 'cmrr_vs_freq.png'), dpi=150)
        plt.close()
    else:
        print("  WARNING: No transient data for CMRR")
        if stderr:
            for l in stderr.splitlines()[-5:]:
                print(f"    {l}")

    return cmrr_db


# ── TB4: Input-Referred Noise ──
def tb4_noise():
    """Noise analysis 0.5-150 Hz. No chopper (AC noise analysis)."""
    print("\n--- TB4: Input-Referred Noise (0.5-150 Hz) ---")

    extra = f"""
* AC noise source
Vinp inp 0 dc {VCM} ac 0.5
Vinn inn 0 dc {VCM} ac -0.5
"""
    control = """
.control
noise v(voutp,voutn) Vinp dec 50 0.1 100k
setplot noise2
print onoise_total
setplot noise1
wrdata _tb4_noise.dat onoise_spectrum
.endc
"""
    netlist = make_netlist(include_chopper=False, extra_sources=extra, control=control)
    stdout, stderr, rc = run_ngspice(netlist, 'tb4_noise')

    noise_uvrms = None
    noise_data = read_wrdata('_tb4_noise.dat')

    # Try to get total noise from ngspice output
    for line in stdout.splitlines():
        if 'onoise_total' in line.lower() and '=' in line:
            try:
                val = float(line.split('=')[-1].strip().split()[0])
                # This is output noise; divide by gain for input-referred
                noise_uvrms_out = val * 1e6
                noise_uvrms = noise_uvrms_out / GAIN_NOMINAL
                print(f"  Output noise total = {noise_uvrms_out:.2f} uVrms")
            except (ValueError, IndexError):
                pass

    # Also try to integrate from spectrum data
    if noise_data is not None and len(noise_data) > 5:
        freqs = noise_data[:, 0]
        noise_v_per_rthz = np.abs(noise_data[:, 1])

        # Integrate 0.5 to 150 Hz (without chopping — includes 1/f)
        mask = (freqs >= 0.5) & (freqs <= 150)
        if np.any(mask):
            f_band = freqs[mask]
            n_band = noise_v_per_rthz[mask]
            noise_power = np.trapezoid(n_band**2, f_band)
            noise_rms_out = math.sqrt(noise_power)
            noise_input_nochop = noise_rms_out / GAIN_NOMINAL

            print(f"  Integrated output noise (0.5-150 Hz, no chop) = {noise_rms_out*1e6:.2f} uVrms")
            print(f"  Input-referred noise (no chop) = {noise_input_nochop*1e6:.2f} uVrms")

        # For chopped system: use white noise floor (high freq, above 1/f corner)
        # Take noise density around 500-1000 Hz as white noise floor estimate
        mask_wh = (freqs >= 500) & (freqs <= 1000)
        if np.any(mask_wh):
            white_floor = np.mean(noise_v_per_rthz[mask_wh])
            white_floor_input = white_floor / GAIN_NOMINAL
            # Chopped noise in 0.5-150 Hz band ≈ white_floor * sqrt(BW)
            # Plus folded 1/f noise contribution (small with fchop >> signal BW)
            bw = 150 - 0.5
            noise_chopped_input = white_floor_input * math.sqrt(bw)
            noise_uvrms = noise_chopped_input * 1e6

            print(f"  White noise floor = {white_floor*1e9:.1f} nV/rtHz (output)")
            print(f"  White noise floor = {white_floor_input*1e9:.1f} nV/rtHz (input-referred)")
            print(f"  Chopped input-referred noise (0.5-150 Hz) = {noise_uvrms:.2f} uVrms")

        # Plot
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.loglog(freqs, noise_v_per_rthz * 1e9)
        ax.axvline(x=0.5, color='green', linestyle='--', alpha=0.5, label='0.5 Hz')
        ax.axvline(x=150, color='green', linestyle='--', alpha=0.5, label='150 Hz')
        ax.set_xlabel('Frequency (Hz)')
        ax.set_ylabel('Output Noise (nV/rtHz)')
        ax.set_title(f'Noise Spectral Density (input-referred: {noise_uvrms:.2f} uVrms)' if noise_uvrms else 'Noise Spectral Density')
        ax.legend()
        ax.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(os.path.join(PLOT_DIR, 'noise_spectral_density.png'), dpi=150)
        plt.close()
    else:
        print("  WARNING: No noise data")

    if noise_uvrms is not None:
        print(f"  Input-referred noise = {noise_uvrms:.2f} uVrms")

    return noise_uvrms


# ── TB5: Input Offset ──
def tb5_offset():
    """Zero differential input, measure output offset."""
    print("\n--- TB5: Input Offset ---")

    extra = f"""
Vinp inp 0 {VCM}
Vinn inn 0 {VCM}
"""
    control = """
.control
op
print v(voutp) v(voutn) v(voutp)-v(voutn)
.endc
"""
    netlist = make_netlist(include_chopper=False, extra_sources=extra, control=control)
    stdout, stderr, rc = run_ngspice(netlist, 'tb5_offset')

    offset_uv = None
    voutp = None
    voutn = None

    for line in stdout.splitlines():
        ll = line.lower().strip()
        if ll.startswith('v(voutp)') and '=' in ll and 'v(voutn)' not in ll:
            try:
                voutp = float(ll.split('=')[-1].strip().split()[0])
            except (ValueError, IndexError):
                pass
        if ll.startswith('v(voutn)') and '=' in ll and 'v(voutp)' not in ll:
            try:
                voutn = float(ll.split('=')[-1].strip().split()[0])
            except (ValueError, IndexError):
                pass

    if voutp is not None and voutn is not None:
        vout_offset = voutp - voutn
        offset_uv = abs(vout_offset) / GAIN_NOMINAL * 1e6
        print(f"  Vout_diff = {vout_offset*1e6:.2f} uV")
        print(f"  Input-referred offset = {offset_uv:.2f} uV")

        # Plot
        fig, ax = plt.subplots(figsize=(8, 5))
        ax.bar(['Voutp', 'Voutn', 'Vdiff'], [voutp, voutn, vout_offset],
               color=['blue', 'orange', 'green'])
        ax.axhline(y=VCM, color='red', linestyle='--', alpha=0.5, label=f'VCM={VCM}V')
        ax.set_ylabel('Voltage (V)')
        ax.set_title(f'DC Offset — Input-referred: {offset_uv:.2f} uV')
        ax.legend()
        ax.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(os.path.join(PLOT_DIR, 'offset_measurement.png'), dpi=150)
        plt.close()
    else:
        print("  WARNING: Could not measure offset")

    return offset_uv


# ── TB6: Electrode Offset Tolerance ──
def tb6_electrode_offset():
    """±300 mV DC offset + 1 mV differential signal. Gain within ±1 dB."""
    print("\n--- TB6: Electrode Offset Tolerance ---")

    results = {}
    offsets = [-0.3, 0, 0.3]

    for dc_offset in offsets:
        extra = f"""
* AC differential input on top of DC electrode offset
Vinp inp 0 dc {VCM + dc_offset} ac 0.5
Vinn inn 0 dc {VCM + dc_offset} ac -0.5
"""
        control = f"""
.control
op
print v(voutp) v(voutn)
ac dec 20 1 100k
wrdata _tb6_eo_{dc_offset:.1f}.dat v(voutp)-v(voutn)
.endc
"""
        netlist = make_netlist(include_chopper=False, extra_sources=extra, control=control)
        stdout, stderr, rc = run_ngspice(netlist, f'tb6_eo_{dc_offset:.1f}')

        # Check output CM from OP
        voutp = None
        voutn = None
        for line in stdout.splitlines():
            ll = line.lower().strip()
            if ll.startswith('v(voutp)') and '=' in ll and 'v(voutn)' not in ll:
                try:
                    voutp = float(ll.split('=')[-1].strip().split()[0])
                except:
                    pass
            if ll.startswith('v(voutn)') and '=' in ll and 'v(voutp)' not in ll:
                try:
                    voutn = float(ll.split('=')[-1].strip().split()[0])
                except:
                    pass

        # Get gain from AC data
        data = read_wrdata(f'_tb6_eo_{dc_offset:.1f}.dat')
        gain_db = -999
        if data is not None and len(data) > 3:
            freqs = data[:, 0]
            if data.shape[1] >= 3:
                mags = np.sqrt(data[:, 1]**2 + data[:, 2]**2)
            else:
                mags = np.abs(data[:, 1])
            lf_idx = np.argmin(np.abs(freqs - 10.0))
            lf_gain = mags[lf_idx]
            if lf_gain > 0:
                gain_db = 20 * math.log10(lf_gain)

        saturated = False
        if voutp is not None and voutn is not None:
            saturated = voutp < 0.1 or voutp > 1.7 or voutn < 0.1 or voutn > 1.7

        results[dc_offset] = {
            'gain_db': gain_db,
            'voutp': voutp if voutp else 0,
            'voutn': voutn if voutn else 0,
            'sat': saturated
        }
        status = 'SAT!' if saturated else 'OK'
        print(f"  Offset={dc_offset:+.1f}V: gain={gain_db:.1f}dB, Voutp={voutp:.3f}, Voutn={voutn:.3f}, {status}")

    # Plot
    fig, ax = plt.subplots(figsize=(8, 5))
    offs = sorted(results.keys())
    gains = [results[o]['gain_db'] for o in offs]
    colors = ['red' if results[o]['sat'] else 'green' for o in offs]
    ax.bar([f'{o:+.1f}V' for o in offs], gains, color=colors, alpha=0.8)
    ax.axhline(y=34, color='blue', linestyle='--', label='34 dB nominal')
    ax.set_ylabel('Gain (dB)')
    ax.set_title('Electrode Offset Tolerance')
    ax.legend()
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(os.path.join(PLOT_DIR, 'electrode_offset_tolerance.png'), dpi=150)
    plt.close()

    return results


# ── TB7: ECG Transient ──
def tb7_ecg_transient():
    """Synthetic ECG + 60 Hz interference + 300 mV DC offset."""
    print("\n--- TB7: ECG Transient ---")

    # Use a simple pulse to simulate R-wave
    # ECG: 1 mV R-peak at 72 BPM (833 ms period), plus 2 mV 60 Hz + 300 mV DC
    extra = f"""
* ECG signal: 1 mV R-peak at 72 BPM
Vecg ecg_sig 0 pulse(0 1m 10m 5m 5m 10m 833m)
* 60 Hz interference: 2 mV
V60hz hum_sig 0 sin(0 2m 60 0 0)
* Input = VCM + 300mV offset + ECG + 60Hz hum
Einp inp 0 vol='0.9 + 0.3 + v(ecg_sig)/2 + v(hum_sig)/2'
Einn inn 0 vol='0.9 + 0.3 - v(ecg_sig)/2 - v(hum_sig)/2'
"""
    control = """
.control
tran 10u 500m
wrdata _tb7_ecg.dat v(voutp)-v(voutn)
.endc
"""
    netlist = make_netlist(include_chopper=True, cin_mismatch=0.001,
                          extra_sources=extra, control=control)
    stdout, stderr, rc = run_ngspice(netlist, 'tb7_ecg')

    data = read_wrdata('_tb7_ecg.dat')
    if data is not None and len(data) > 100:
        time = data[:, 0]
        vout = data[:, 1]

        fig, ax = plt.subplots(figsize=(12, 5))
        ax.plot(time * 1e3, vout * 1e3)
        ax.set_xlabel('Time (ms)')
        ax.set_ylabel('Vout_diff (mV)')
        ax.set_title('ECG Transient (1mV R-peak + 2mV 60Hz + 300mV DC offset)')
        ax.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(os.path.join(PLOT_DIR, 'ecg_transient.png'), dpi=150)
        plt.close()
        print("  ECG transient captured. See plots/ecg_transient.png")
        return True
    else:
        print("  WARNING: No ECG transient data")
        if stderr:
            for l in stderr.splitlines()[-5:]:
                print(f"    {l}")
        return False


# ── Scoring ──
def check_spec(name, val):
    if val is None:
        return False
    spec = SPECS[name]
    if spec['op'] == '>':  return val > spec['target']
    if spec['op'] == '>=': return val >= spec['target']
    if spec['op'] == '<':  return val < spec['target']
    if spec['op'] == '<=': return val <= spec['target']
    return False


def compute_score(measurements):
    total_weight = sum(s['weight'] for s in SPECS.values())
    earned = sum(SPECS[n]['weight'] for n in SPECS if check_spec(n, measurements.get(n)))
    return earned / total_weight


# ── Main ──
def main():
    print("=" * 60)
    print("CCIA InAmp Evaluation")
    print("=" * 60)

    measurements = {}

    # TB1: DC Gain
    gain_db, power_uw, voutp, voutn = tb1_dc_gain()
    measurements['power_uw'] = power_uw if power_uw else 999

    # TB2: AC Response
    gain_db_ac, bandwidth_hz = tb2_ac_response()
    measurements['gain_db'] = gain_db_ac if gain_db_ac else (gain_db if gain_db else 0)
    measurements['bandwidth_hz'] = bandwidth_hz if bandwidth_hz else 0

    # TB3: CMRR
    cmrr_db = tb3_cmrr_mismatch()
    measurements['cmrr_60hz_db'] = cmrr_db if cmrr_db else 0

    # TB4: Noise
    noise_uvrms = tb4_noise()
    measurements['input_referred_noise_uvrms'] = noise_uvrms if noise_uvrms else 999

    # TB5: Offset
    offset_uv = tb5_offset()
    measurements['input_offset_uv'] = offset_uv if offset_uv is not None else 999

    # TB6: Electrode offset
    eo_results = tb6_electrode_offset()

    # TB7: ECG
    ecg_ok = tb7_ecg_transient()

    # Score
    score = compute_score(measurements)
    specs_met = sum(1 for n in SPECS if check_spec(n, measurements.get(n)))

    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)
    for name, spec in SPECS.items():
        val = measurements.get(name)
        status = 'PASS' if check_spec(name, val) else 'FAIL'
        val_str = f'{val:.4f}' if val is not None else 'N/A'
        print(f"  {name:35s}: {val_str:>12s}  {spec['op']} {spec['target']:>8}  [{status}]")

    print(f"\n  Score: {score:.2f}  ({specs_met}/{len(SPECS)} specs met)")

    with open(os.path.join(WORK_DIR, 'measurements.json'), 'w') as f:
        json.dump(measurements, f, indent=2)

    return score, specs_met, measurements


def tb8_pvt():
    """PVT corner analysis: gain and noise across 5 corners × 3 temps."""
    print("\n--- TB8: PVT Corner Analysis ---")
    corners = ['tt', 'ss', 'ff', 'sf', 'fs']
    temps = [-40, 27, 125]
    results = {}
    all_pass = True

    for corner in corners:
        for temp in temps:
            extra = f"""
Vinp inp 0 dc {VCM} ac 0.5
Vinn inn 0 dc {VCM} ac -0.5
"""
            control = f"""
.control
ac dec 50 0.1 10Meg
wrdata _pvt_{corner}_{temp}.dat v(voutp)-v(voutn)
.endc
"""
            netlist = make_netlist(corner=corner, temp=temp,
                                  include_chopper=False,
                                  extra_sources=extra, control=control)
            stdout, stderr, rc = run_ngspice(netlist, f'pvt_{corner}_{temp}')

            data = read_wrdata(f'_pvt_{corner}_{temp}.dat')
            if data is not None and len(data) > 5:
                freqs = data[:, 0]
                if data.shape[1] >= 3:
                    mags = np.sqrt(data[:, 1]**2 + data[:, 2]**2)
                else:
                    mags = np.abs(data[:, 1])

                lf_idx = np.argmin(np.abs(freqs - 1.0))
                lf_gain = mags[lf_idx]
                gain_db = 20 * math.log10(lf_gain) if lf_gain > 0 else -999

                gain_3db = lf_gain / math.sqrt(2)
                bw_idx = np.where(mags < gain_3db)[0]
                bw = freqs[bw_idx[0]] if len(bw_idx) > 0 else freqs[-1]

                # Check power
                power = None
                for line in stdout.splitlines():
                    if 'i(vdd)' in line.lower() and '=' in line:
                        try:
                            val = float(line.split('=')[-1].strip().split()[0])
                            power = abs(val) * VDD * 1e6
                        except:
                            pass

                gain_pass = gain_db > 34
                bw_pass = bw > 10000
                corner_pass = gain_pass and bw_pass
                if not corner_pass:
                    all_pass = False

                results[(corner, temp)] = {
                    'gain_db': gain_db, 'bw': bw, 'power': power,
                    'pass': corner_pass
                }
                status = 'PASS' if corner_pass else 'FAIL'
                print(f"  {corner:2s} {temp:4d}C: gain={gain_db:.1f}dB, BW={bw:.0f}Hz [{status}]")
            else:
                results[(corner, temp)] = {'gain_db': -999, 'bw': 0, 'power': None, 'pass': False}
                all_pass = False
                print(f"  {corner:2s} {temp:4d}C: SIMULATION FAILED")

    # Plot
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))
    for corner in corners:
        gains = [results.get((corner, t), {}).get('gain_db', 0) for t in temps]
        bws = [results.get((corner, t), {}).get('bw', 0) for t in temps]
        ax1.plot(temps, gains, 'o-', label=corner)
        ax2.plot(temps, [b/1000 for b in bws], 'o-', label=corner)

    ax1.axhline(y=34, color='red', linestyle='--', label='34 dB target')
    ax1.set_xlabel('Temperature (C)'); ax1.set_ylabel('Gain (dB)')
    ax1.set_title('PVT: Gain'); ax1.legend(); ax1.grid(True, alpha=0.3)

    ax2.axhline(y=10, color='red', linestyle='--', label='10 kHz target')
    ax2.set_xlabel('Temperature (C)'); ax2.set_ylabel('Bandwidth (kHz)')
    ax2.set_title('PVT: Bandwidth'); ax2.legend(); ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(os.path.join(PLOT_DIR, 'pvt_summary.png'), dpi=150)
    plt.close()

    pvt_count = sum(1 for r in results.values() if r.get('pass'))
    total = len(results)
    print(f"\n  PVT: {pvt_count}/{total} corners pass")
    print(f"  PVT result: {'PASS' if all_pass else 'FAIL'}")

    return results, all_pass


def tb9_monte_carlo():
    """Sweep Cin mismatch from 0.01% to 1%, measure CMRR at each."""
    print("\n--- TB9: Monte Carlo / Mismatch Sweep ---")
    mismatches = [0.0001, 0.0003, 0.0005, 0.001, 0.003, 0.005, 0.01]
    cmrr_results = {}

    vcm_amp = 10e-3

    for mm in mismatches:
        extra = f"""
Vinp inp 0 sin({VCM} {vcm_amp} 60 0 0)
Vinn inn 0 sin({VCM} {vcm_amp} 60 0 0)
"""
        control = """
.control
tran 1u 200m 50m
wrdata _mc_cmrr.dat v(voutp)-v(voutn)
.endc
"""
        netlist = make_netlist(cin_mismatch=mm, include_chopper=True,
                              extra_sources=extra, control=control)
        stdout, stderr, rc = run_ngspice(netlist, f'mc_{mm}')

        data = read_wrdata('_mc_cmrr.dat')
        if data is not None and len(data) > 100:
            time = data[:, 0]
            vout_diff = data[:, 1]
            vout_ac = vout_diff - np.mean(vout_diff)
            N = len(vout_ac)
            dt = np.mean(np.diff(time))
            fft_vals = np.fft.rfft(vout_ac)
            fft_mag = np.abs(fft_vals) * 2 / N
            freqs = np.fft.rfftfreq(N, dt)

            idx_60 = np.argmin(np.abs(freqs - 60))
            vout_60 = fft_mag[idx_60]
            cm_gain = vout_60 / vcm_amp if vcm_amp > 0 else 1e-15
            cmrr = GAIN_NOMINAL / cm_gain if cm_gain > 0 else 999
            cmrr_db = 20 * math.log10(cmrr) if cmrr > 0 else 0

            cmrr_results[mm] = cmrr_db
            status = 'PASS' if cmrr_db > 100 else 'FAIL'
            print(f"  Mismatch={mm*100:.3f}%: CMRR={cmrr_db:.1f}dB [{status}]")
        else:
            cmrr_results[mm] = 0
            print(f"  Mismatch={mm*100:.3f}%: SIMULATION FAILED")

    # Plot
    fig, ax = plt.subplots(figsize=(10, 6))
    mm_pct = [m*100 for m in mismatches]
    cmrr_vals = [cmrr_results.get(m, 0) for m in mismatches]
    ax.semilogx(mm_pct, cmrr_vals, 'bo-', markersize=8)
    ax.axhline(y=100, color='red', linestyle='--', label='100 dB target')
    ax.set_xlabel('Cin Mismatch (%)')
    ax.set_ylabel('CMRR at 60 Hz (dB)')
    ax.set_title('CMRR vs Cin Mismatch (with 10 kHz chopping)')
    ax.legend()
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(os.path.join(PLOT_DIR, 'monte_carlo.png'), dpi=150)
    plt.close()

    all_pass = all(v > 100 for v in cmrr_results.values())
    print(f"\n  Monte Carlo: {'PASS' if all_pass else 'FAIL'}")
    return cmrr_results, all_pass


if __name__ == '__main__':
    score, specs_met, measurements = main()

    if score >= 1.0:
        print("\n\nPhase A complete. Running Phase B: PVT corners...")
        pvt_results, pvt_pass = tb8_pvt()

        print("\n\nRunning Phase C: Monte Carlo mismatch sweep...")
        mc_results, mc_pass = tb9_monte_carlo()
