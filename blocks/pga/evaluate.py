#!/usr/bin/env python3
"""PGA Evaluator — runs all testbenches and scores the design.

Testbenches:
  TB1: Gain accuracy at all 8 settings
  TB2: AC frequency response (BW at max gain)
  TB3: Noise analysis (output noise at gain=1)
  TB4: THD (10 Hz, 1 Vpp output)
  TB5: Gain switching transient (settling time)
  TB6: PVT corners (Phase B)
"""

import subprocess
import os
import sys
import json
import re
import math
import numpy as np

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

# ── Configuration ──────────────────────────────────────────
GAINS = [1, 2, 4, 8, 16, 32, 64, 128]
VCM = 0.9
VDD = 1.8
RF_VAL = 100e3  # 100 kΩ fixed feedback resistor

SPECS = {
    'gain_settings':     {'target': 7,     'op': '>=', 'weight': 15},
    'gain_error_pct':    {'target': 1.0,   'op': '<',  'weight': 20},
    'bandwidth_hz':      {'target': 10000, 'op': '>',  'weight': 15},
    'output_noise_uvrms':{'target': 50,    'op': '<',  'weight': 15},
    'thd_pct':           {'target': 0.1,   'op': '<',  'weight': 15},
    'power_uw':          {'target': 10,    'op': '<',  'weight': 10},
    'settling_time_us':  {'target': 100,   'op': '<',  'weight': 10},
}

WORK_DIR = os.path.dirname(os.path.abspath(__file__))
PLOT_DIR = os.path.join(WORK_DIR, 'plots')
os.makedirs(PLOT_DIR, exist_ok=True)


# ── Helpers ────────────────────────────────────────────────
def run_ngspice(netlist_str, tag='sim'):
    """Write netlist to file, run ngspice -b, return (stdout, stderr, rc)."""
    nf = os.path.join(WORK_DIR, f'_tb_{tag}.spice')
    with open(nf, 'w') as f:
        f.write(netlist_str)
    r = subprocess.run(
        ['ngspice', '-b', nf],
        capture_output=True, text=True, timeout=180,
        cwd=WORK_DIR
    )
    return r.stdout, r.stderr, r.returncode


def read_wrdata(filename):
    """Read ngspice wrdata output (index/freq, real, imag or just real)."""
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


def read_measurement(stdout, name):
    """Extract a .meas result from ngspice stdout."""
    for line in stdout.splitlines():
        if name.lower() in line.lower() and '=' in line:
            parts = line.split('=')
            if len(parts) >= 2:
                try:
                    val_str = parts[-1].strip().split()[0]
                    return float(val_str)
                except (ValueError, IndexError):
                    continue
    return None


def base_netlist():
    """Read design.cir and strip .end for appending testbench commands."""
    with open(os.path.join(WORK_DIR, 'design.cir')) as f:
        lines = f.readlines()
    # Remove trailing .end
    result = []
    for line in lines:
        if line.strip().lower() == '.end':
            continue
        result.append(line)
    return ''.join(result)


# ── TB1 + TB2: Gain Accuracy & Bandwidth via AC Analysis ──
def tb_ac_gain():
    """Run AC analysis at each gain setting.
    Returns: dict with gain_errors, bandwidths, measured_gains, and power."""
    measured_gains = {}
    gain_errors = {}
    bandwidths = {}
    power_uw = None

    for g in GAINS:
        rin_val = RF_VAL / g
        netlist = f"""* TB1/TB2: AC analysis at gain={g}
.lib "sky130_models/sky130.lib.spice" tt

.param gain_val = {g}
.param rf_val = {RF_VAL}
.param rin_val = {rin_val}
.param vcm = {VCM}
.param ibias_val = 2u

Vdd vdd 0 {VDD}
Vss vss 0 0
Vcm vcm_node 0 {{vcm}}

.subckt opamp inp inn out vdd vss
Ibias vdd pbias {{ibias_val}}
XMp_diode pbias pbias vdd vdd sky130_fd_pr__pfet_01v8 w=4u l=2u m=1
XMn_diode nbias pbias vss vss sky130_fd_pr__nfet_01v8 w=2u l=4u m=1
XMn_bias  nbias nbias vss vss sky130_fd_pr__nfet_01v8 w=2u l=4u m=1
XM5 tail pbias vdd vdd sky130_fd_pr__pfet_01v8 w=4u l=2u m=2
XM1 d1 inp tail vdd sky130_fd_pr__pfet_01v8 w=8u l=1u m=1
XM2 d2 inn tail vdd sky130_fd_pr__pfet_01v8 w=8u l=1u m=1
XM3 d1 d1 vss vss sky130_fd_pr__nfet_01v8 w=2u l=1u m=1
XM4 d2 d1 vss vss sky130_fd_pr__nfet_01v8 w=2u l=1u m=1
XM7 out pbias vdd vdd sky130_fd_pr__pfet_01v8 w=8u l=1u m=1
XM6 out d2   vss vss sky130_fd_pr__nfet_01v8 w=8u l=0.5u m=1
XCc d2 cc_mid sky130_fd_pr__cap_mim_m3_1 w=30u l=30u m=1
Rz  cc_mid out 2k
.ends opamp

X1 vcm_node vminus vout vdd vss opamp
Rf vminus vout {{rf_val}}
Rin vin vminus {{rin_val}}
Vin vin 0 dc {{vcm}} ac 1

.control
op
let pwr = abs(@vdd[i]) * 1.8
print pwr

ac dec 100 0.1 100Meg
let vout_mag = abs(v(vout))
let vout_ph = 180*vp(vout)/pi
wrdata _ac_gain_{g}.dat vout_mag vout_ph
meas ac gain_at_1hz find vout_mag at=1
meas ac freq_3db when vout_mag = {{gain_at_1hz/sqrt(2)}} fall=1
.endc

.end
"""
        stdout, stderr, rc = run_ngspice(netlist, f'ac_g{g}')

        # Parse AC data
        data = read_wrdata(f'_ac_gain_{g}.dat')
        if data is not None and len(data) > 5:
            freqs = data[:, 0]
            mags = data[:, 1]

            # Gain at low freq (1 Hz region)
            low_freq_mask = (freqs >= 0.5) & (freqs <= 5)
            if np.any(low_freq_mask):
                lf_gain = np.mean(mags[low_freq_mask])
            else:
                lf_gain = mags[0]

            measured_gains[g] = lf_gain
            ideal_gain = g
            error_pct = abs(lf_gain - ideal_gain) / ideal_gain * 100
            gain_errors[g] = error_pct

            # Bandwidth: find -3dB point
            gain_3db = lf_gain / math.sqrt(2)
            bw_idx = np.where(mags < gain_3db)[0]
            if len(bw_idx) > 0:
                bandwidths[g] = freqs[bw_idx[0]]
            else:
                bandwidths[g] = freqs[-1]  # beyond measurement range
        else:
            print(f"  WARNING: No AC data for gain={g}")
            measured_gains[g] = 0
            gain_errors[g] = 100
            bandwidths[g] = 0

        # Power from stdout
        if power_uw is None:
            pwr_val = read_measurement(stdout, 'pwr')
            if pwr_val is not None:
                power_uw = abs(pwr_val) * 1e6

    return measured_gains, gain_errors, bandwidths, power_uw


# ── TB3: Noise Analysis ──────────────────────────────────
def tb_noise():
    """Run noise analysis at gain=1, integrate 0.5-150 Hz."""
    rin_val = RF_VAL / 1  # gain = 1
    netlist = f"""* TB3: Noise analysis at gain=1
.lib "sky130_models/sky130.lib.spice" tt

.param gain_val = 1
.param rf_val = {RF_VAL}
.param rin_val = {rin_val}
.param vcm = {VCM}
.param ibias_val = 2u

Vdd vdd 0 {VDD}
Vss vss 0 0
Vcm vcm_node 0 {{vcm}}

.subckt opamp inp inn out vdd vss
Ibias vdd pbias {{ibias_val}}
XMp_diode pbias pbias vdd vdd sky130_fd_pr__pfet_01v8 w=4u l=2u m=1
XMn_diode nbias pbias vss vss sky130_fd_pr__nfet_01v8 w=2u l=4u m=1
XMn_bias  nbias nbias vss vss sky130_fd_pr__nfet_01v8 w=2u l=4u m=1
XM5 tail pbias vdd vdd sky130_fd_pr__pfet_01v8 w=4u l=2u m=2
XM1 d1 inp tail vdd sky130_fd_pr__pfet_01v8 w=8u l=1u m=1
XM2 d2 inn tail vdd sky130_fd_pr__pfet_01v8 w=8u l=1u m=1
XM3 d1 d1 vss vss sky130_fd_pr__nfet_01v8 w=2u l=1u m=1
XM4 d2 d1 vss vss sky130_fd_pr__nfet_01v8 w=2u l=1u m=1
XM7 out pbias vdd vdd sky130_fd_pr__pfet_01v8 w=8u l=1u m=1
XM6 out d2   vss vss sky130_fd_pr__nfet_01v8 w=8u l=0.5u m=1
XCc d2 cc_mid sky130_fd_pr__cap_mim_m3_1 w=30u l=30u m=1
Rz  cc_mid out 2k
.ends opamp

X1 vcm_node vminus vout vdd vss opamp
Rf vminus vout {{rf_val}}
Rin vin vminus {{rin_val}}
Vin vin 0 dc {{vcm}} ac 0

.control
noise v(vout) Vin dec 50 0.5 150
setplot noise1
print onoise_total
wrdata _noise.dat onoise_spectrum
.endc

.end
"""
    stdout, stderr, rc = run_ngspice(netlist, 'noise')

    # Parse integrated noise
    noise_uvrms = None
    for line in stdout.splitlines():
        if 'onoise_total' in line.lower():
            parts = line.split('=')
            if len(parts) >= 2:
                try:
                    val = float(parts[-1].strip().split()[0])
                    noise_uvrms = val * 1e6  # V to µV
                except (ValueError, IndexError):
                    pass

    # Try reading noise data for plot
    noise_data = read_wrdata('_noise.dat')

    return noise_uvrms, noise_data


# ── TB4: THD via Transient + FFT ─────────────────────────
def tb_thd():
    """Run transient at gain=1, 10 Hz sine, 1 Vpp output → need 1 Vpp input.
    THD from FFT of output."""
    g = 1  # gain=1 for THD test
    rin_val = RF_VAL / g
    # For 1 Vpp output at gain=1 (inverting), input AC = 1 Vpp
    # Input: VCM + 0.5*sin(2π*10*t)
    vin_amp = 0.5  # 1 Vpp → ±0.5V amplitude

    netlist = f"""* TB4: THD analysis — 10 Hz, 1 Vpp output, gain=1
.lib "sky130_models/sky130.lib.spice" tt

.param rf_val = {RF_VAL}
.param rin_val = {rin_val}
.param vcm = {VCM}
.param ibias_val = 2u

Vdd vdd 0 {VDD}
Vss vss 0 0
Vcm vcm_node 0 {{vcm}}

.subckt opamp inp inn out vdd vss
Ibias vdd pbias {{ibias_val}}
XMp_diode pbias pbias vdd vdd sky130_fd_pr__pfet_01v8 w=4u l=2u m=1
XMn_diode nbias pbias vss vss sky130_fd_pr__nfet_01v8 w=2u l=4u m=1
XMn_bias  nbias nbias vss vss sky130_fd_pr__nfet_01v8 w=2u l=4u m=1
XM5 tail pbias vdd vdd sky130_fd_pr__pfet_01v8 w=4u l=2u m=2
XM1 d1 inp tail vdd sky130_fd_pr__pfet_01v8 w=8u l=1u m=1
XM2 d2 inn tail vdd sky130_fd_pr__pfet_01v8 w=8u l=1u m=1
XM3 d1 d1 vss vss sky130_fd_pr__nfet_01v8 w=2u l=1u m=1
XM4 d2 d1 vss vss sky130_fd_pr__nfet_01v8 w=2u l=1u m=1
XM7 out pbias vdd vdd sky130_fd_pr__pfet_01v8 w=8u l=1u m=1
XM6 out d2   vss vss sky130_fd_pr__nfet_01v8 w=8u l=0.5u m=1
XCc d2 cc_mid sky130_fd_pr__cap_mim_m3_1 w=30u l=30u m=1
Rz  cc_mid out 2k
.ends opamp

X1 vcm_node vminus vout vdd vss opamp
Rf vminus vout {{rf_val}}
Rin vin vminus {{rin_val}}
Vin vin 0 dc {{vcm}} sin({{vcm}} {vin_amp} 10 0 0)

.control
tran 100u 500m 100m
wrdata _thd_tran.dat v(vout)
.endc

.end
"""
    stdout, stderr, rc = run_ngspice(netlist, 'thd')

    # Parse transient data and compute FFT
    data = read_wrdata('_thd_tran.dat')
    thd_pct = None
    fft_data = None

    if data is not None and len(data) > 100:
        time = data[:, 0]
        vout = data[:, 1]

        # Remove DC offset
        vout_ac = vout - np.mean(vout)

        # FFT
        N = len(vout_ac)
        dt = np.mean(np.diff(time))
        fft_vals = np.fft.rfft(vout_ac)
        fft_mag = np.abs(fft_vals) * 2 / N
        freqs = np.fft.rfftfreq(N, dt)

        # Find fundamental (near 10 Hz)
        fund_idx = np.argmin(np.abs(freqs - 10))
        fund_mag = fft_mag[fund_idx]

        if fund_mag > 1e-6:
            # Sum harmonics 2-5
            harm_power = 0
            for h in range(2, 6):
                h_idx = np.argmin(np.abs(freqs - 10*h))
                harm_power += fft_mag[h_idx]**2
            thd_pct = math.sqrt(harm_power) / fund_mag * 100

        fft_data = (freqs, fft_mag)

    return thd_pct, fft_data, data


# ── TB5: Settling time ────────────────────────────────────
def tb_settling():
    """Measure settling time after gain switch from 1x to 128x.
    Simplified: we measure step response at gain=128."""
    g = 128
    rin_val = RF_VAL / g
    # Small step input: 1 mV step → 128 mV output step
    step_in = 1e-3

    netlist = f"""* TB5: Settling time — step response at gain=128
.lib "sky130_models/sky130.lib.spice" tt

.param rf_val = {RF_VAL}
.param rin_val = {rin_val}
.param vcm = {VCM}
.param ibias_val = 2u

Vdd vdd 0 {VDD}
Vss vss 0 0
Vcm vcm_node 0 {{vcm}}

.subckt opamp inp inn out vdd vss
Ibias vdd pbias {{ibias_val}}
XMp_diode pbias pbias vdd vdd sky130_fd_pr__pfet_01v8 w=4u l=2u m=1
XMn_diode nbias pbias vss vss sky130_fd_pr__nfet_01v8 w=2u l=4u m=1
XMn_bias  nbias nbias vss vss sky130_fd_pr__nfet_01v8 w=2u l=4u m=1
XM5 tail pbias vdd vdd sky130_fd_pr__pfet_01v8 w=4u l=2u m=2
XM1 d1 inp tail vdd sky130_fd_pr__pfet_01v8 w=8u l=1u m=1
XM2 d2 inn tail vdd sky130_fd_pr__pfet_01v8 w=8u l=1u m=1
XM3 d1 d1 vss vss sky130_fd_pr__nfet_01v8 w=2u l=1u m=1
XM4 d2 d1 vss vss sky130_fd_pr__nfet_01v8 w=2u l=1u m=1
XM7 out pbias vdd vdd sky130_fd_pr__pfet_01v8 w=8u l=1u m=1
XM6 out d2   vss vss sky130_fd_pr__nfet_01v8 w=8u l=0.5u m=1
XCc d2 cc_mid sky130_fd_pr__cap_mim_m3_1 w=30u l=30u m=1
Rz  cc_mid out 2k
.ends opamp

X1 vcm_node vminus vout vdd vss opamp
Rf vminus vout {{rf_val}}
Rin vin vminus {{rin_val}}
Vin vin 0 dc {{vcm}} pulse({{vcm}} {VCM + step_in} 10u 1n 1n 500u 1m)

.control
tran 0.1u 200u
wrdata _settling.dat v(vout)
.endc

.end
"""
    stdout, stderr, rc = run_ngspice(netlist, 'settling')

    data = read_wrdata('_settling.dat')
    settling_us = None

    if data is not None and len(data) > 50:
        time = data[:, 0]
        vout = data[:, 1]

        # Find steady-state value (last 10% of data)
        final_val = np.mean(vout[int(0.9*len(vout)):])
        # Expected output change: -gain * step_in (inverting)
        # Find when step occurs (~10µs)
        step_idx = np.argmin(np.abs(time - 10e-6))

        # Find settling within 0.1% of final value
        tolerance = abs(final_val - vout[step_idx]) * 0.001
        if tolerance < 1e-9:
            tolerance = 1e-6  # minimum tolerance

        settled = np.abs(vout[step_idx:] - final_val) < tolerance
        if np.any(settled):
            # Find first point where it stays settled
            for i in range(len(settled)):
                if np.all(settled[i:min(i+10, len(settled))]):
                    settling_us = (time[step_idx + i] - time[step_idx]) * 1e6
                    break

    return settling_us, data


# ── Scoring ───────────────────────────────────────────────
def compute_score(measurements):
    """Compute weighted score: 0 to 1.0."""
    total_weight = sum(s['weight'] for s in SPECS.values())
    earned = 0

    for name, spec in SPECS.items():
        val = measurements.get(name)
        if val is None:
            continue

        if spec['op'] == '>=':
            passed = val >= spec['target']
        elif spec['op'] == '>':
            passed = val > spec['target']
        elif spec['op'] == '<':
            passed = val < spec['target']
        elif spec['op'] == '<=':
            passed = val <= spec['target']
        else:
            passed = False

        if passed:
            earned += spec['weight']

    return earned / total_weight


# ── Plotting ──────────────────────────────────────────────
def plot_gain_accuracy(measured_gains, gain_errors):
    """TB1: Bar chart of ideal vs measured gain at all settings."""
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))

    gains_list = sorted(measured_gains.keys())
    ideal = [g for g in gains_list]
    measured = [measured_gains[g] for g in gains_list]

    x = np.arange(len(gains_list))
    width = 0.35

    ax1.bar(x - width/2, ideal, width, label='Ideal', alpha=0.8)
    ax1.bar(x + width/2, measured, width, label='Measured', alpha=0.8)
    ax1.set_xticks(x)
    ax1.set_xticklabels([str(g) for g in gains_list])
    ax1.set_xlabel('Gain Setting')
    ax1.set_ylabel('Gain (V/V)')
    ax1.set_title('Gain Accuracy — Ideal vs Measured')
    ax1.set_yscale('log')
    ax1.legend()
    ax1.grid(True, alpha=0.3)

    errors = [gain_errors[g] for g in gains_list]
    colors = ['green' if e < 1 else 'orange' if e < 5 else 'red' for e in errors]
    ax2.bar(x, errors, color=colors, alpha=0.8)
    ax2.axhline(y=1.0, color='red', linestyle='--', label='1% target')
    ax2.set_xticks(x)
    ax2.set_xticklabels([str(g) for g in gains_list])
    ax2.set_xlabel('Gain Setting')
    ax2.set_ylabel('Gain Error (%)')
    ax2.set_title('Gain Error at Each Setting')
    ax2.legend()
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(os.path.join(PLOT_DIR, 'gain_accuracy.png'), dpi=150)
    plt.close()


def plot_ac_response(all_ac_data):
    """TB2: Overlay AC response at all gain settings."""
    fig, ax = plt.subplots(figsize=(10, 6))

    for g in GAINS:
        data = read_wrdata(f'_ac_gain_{g}.dat')
        if data is not None and len(data) > 5:
            freqs = data[:, 0]
            mags = data[:, 1]
            # Convert to dB
            mags_db = 20 * np.log10(np.maximum(mags, 1e-15))
            ax.semilogx(freqs, mags_db, label=f'G={g}')

    ax.axhline(y=0, color='gray', linestyle=':', alpha=0.5)
    ax.axvline(x=10000, color='red', linestyle='--', alpha=0.5, label='10 kHz target')
    ax.set_xlabel('Frequency (Hz)')
    ax.set_ylabel('Gain (dB)')
    ax.set_title('AC Response — All Gain Settings')
    ax.legend(loc='lower left')
    ax.grid(True, alpha=0.3)
    ax.set_xlim([0.1, 100e6])

    plt.tight_layout()
    plt.savefig(os.path.join(PLOT_DIR, 'ac_response.png'), dpi=150)
    plt.close()


def plot_thd(fft_data, tran_data):
    """TB4: FFT of 10 Hz transient."""
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))

    if tran_data is not None:
        time = tran_data[:, 0]
        vout = tran_data[:, 1]
        ax1.plot(time * 1e3, vout)
        ax1.set_xlabel('Time (ms)')
        ax1.set_ylabel('Vout (V)')
        ax1.set_title('THD Transient — 10 Hz, Gain=1')
        ax1.grid(True, alpha=0.3)

    if fft_data is not None:
        freqs, mags = fft_data
        mags_db = 20 * np.log10(np.maximum(mags, 1e-15))
        ax2.plot(freqs, mags_db)
        ax2.set_xlim([0, 100])
        ax2.set_xlabel('Frequency (Hz)')
        ax2.set_ylabel('Magnitude (dB)')
        ax2.set_title('FFT Spectrum — THD Analysis')
        ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(os.path.join(PLOT_DIR, 'thd_analysis.png'), dpi=150)
    plt.close()


def plot_settling(data):
    """TB5: Settling transient."""
    if data is None:
        return
    fig, ax = plt.subplots(figsize=(8, 5))

    time = data[:, 0]
    vout = data[:, 1]
    ax.plot(time * 1e6, vout)
    ax.axvline(x=10, color='red', linestyle='--', alpha=0.5, label='Step applied')
    ax.set_xlabel('Time (µs)')
    ax.set_ylabel('Vout (V)')
    ax.set_title('Gain Switching / Step Response (Gain=128)')
    ax.legend()
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(os.path.join(PLOT_DIR, 'gain_switching.png'), dpi=150)
    plt.close()


def plot_noise(noise_data):
    """TB3: Noise spectrum."""
    if noise_data is None:
        return
    fig, ax = plt.subplots(figsize=(8, 5))

    freqs = noise_data[:, 0]
    noise = noise_data[:, 1]
    ax.loglog(freqs, noise)
    ax.set_xlabel('Frequency (Hz)')
    ax.set_ylabel('Output Noise Spectral Density (V/√Hz)')
    ax.set_title('Output Noise Spectrum (Gain=1)')
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(os.path.join(PLOT_DIR, 'noise_spectrum.png'), dpi=150)
    plt.close()


# ── Main ──────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("PGA Evaluation — Starting all testbenches")
    print("=" * 60)

    measurements = {}

    # ── TB1 + TB2: Gain and Bandwidth ──
    print("\n--- TB1/TB2: Gain Accuracy & AC Response ---")
    measured_gains, gain_errors, bandwidths, power_uw = tb_ac_gain()

    for g in GAINS:
        print(f"  Gain={g:3d}: measured={measured_gains.get(g, 0):.3f}, "
              f"error={gain_errors.get(g, 100):.2f}%, BW={bandwidths.get(g, 0):.0f} Hz")

    # Count passing gain settings (error < 1%)
    passing_gains = sum(1 for g in GAINS if gain_errors.get(g, 100) < 1.0)
    worst_error = max(gain_errors.values()) if gain_errors else 100
    bw_at_max = bandwidths.get(128, 0)

    measurements['gain_settings'] = passing_gains
    measurements['gain_error_pct'] = worst_error
    measurements['bandwidth_hz'] = bw_at_max
    measurements['power_uw'] = power_uw if power_uw else 999

    print(f"\n  Passing gain settings: {passing_gains}/8")
    print(f"  Worst gain error: {worst_error:.2f}%")
    print(f"  BW at gain=128: {bw_at_max:.0f} Hz")
    print(f"  Power: {measurements['power_uw']:.1f} µW")

    # Plots
    plot_gain_accuracy(measured_gains, gain_errors)
    plot_ac_response(None)
    print("  Plots: gain_accuracy.png, ac_response.png")

    # ── TB3: Noise ──
    print("\n--- TB3: Noise Analysis ---")
    noise_uvrms, noise_data = tb_noise()
    measurements['output_noise_uvrms'] = noise_uvrms if noise_uvrms else 999
    print(f"  Output noise: {measurements['output_noise_uvrms']:.1f} µVrms")
    plot_noise(noise_data)
    print("  Plot: noise_spectrum.png")

    # ── TB4: THD ──
    print("\n--- TB4: THD Analysis ---")
    thd_pct, fft_data, tran_data = tb_thd()
    measurements['thd_pct'] = thd_pct if thd_pct else 999
    print(f"  THD: {measurements['thd_pct']:.4f}%")
    plot_thd(fft_data, tran_data)
    print("  Plot: thd_analysis.png")

    # ── TB5: Settling ──
    print("\n--- TB5: Settling Time ---")
    settling_us, settling_data = tb_settling()
    measurements['settling_time_us'] = settling_us if settling_us else 999
    print(f"  Settling time: {measurements['settling_time_us']:.1f} µs")
    plot_settling(settling_data)
    print("  Plot: gain_switching.png")

    # ── Scoring ──
    score = compute_score(measurements)
    specs_met = sum(1 for name, spec in SPECS.items()
                    if measurements.get(name) is not None and
                    (spec['op'] == '>=' and measurements[name] >= spec['target'] or
                     spec['op'] == '>'  and measurements[name] > spec['target'] or
                     spec['op'] == '<'  and measurements[name] < spec['target'] or
                     spec['op'] == '<=' and measurements[name] <= spec['target']))

    print("\n" + "=" * 60)
    print("RESULTS SUMMARY")
    print("=" * 60)
    for name, spec in SPECS.items():
        val = measurements.get(name, None)
        if val is None:
            status = 'MISSING'
        elif spec['op'] == '>=' and val >= spec['target']:
            status = 'PASS'
        elif spec['op'] == '>' and val > spec['target']:
            status = 'PASS'
        elif spec['op'] == '<' and val < spec['target']:
            status = 'PASS'
        elif spec['op'] == '<=' and val <= spec['target']:
            status = 'PASS'
        else:
            status = 'FAIL'
        val_str = f'{val:.4f}' if val is not None else 'N/A'
        print(f"  {name:25s}: {val_str:>12s}  target {spec['op']} {spec['target']:>8}  [{status}]")

    print(f"\n  Score: {score:.2f}  ({specs_met}/{len(SPECS)} specs met)")

    # Save measurements
    with open(os.path.join(WORK_DIR, 'measurements.json'), 'w') as f:
        json.dump(measurements, f, indent=2)

    print(f"\nMeasurements saved to measurements.json")
    return score, specs_met, measurements


if __name__ == '__main__':
    score, specs_met, measurements = main()
