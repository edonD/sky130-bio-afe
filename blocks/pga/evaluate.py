#!/usr/bin/env python3
"""PGA Evaluator — runs all testbenches and scores the design.

Testbenches:
  TB1: Gain accuracy at all 8 settings
  TB2: AC frequency response (BW at max gain)
  TB3: Noise analysis (output noise at gain=1)
  TB4: THD (10 Hz, 1 Vpp output)
  TB5: Settling time (step response at gain=128)
"""

import subprocess
import os
import json
import math
import numpy as np

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

# ── Configuration ──────────────────────────────────────────
GAINS = [1, 2, 4, 8, 16, 32, 64, 128]
VCM = 0.9
VDD = 1.8
RF_VAL = 10e6  # 10 MΩ feedback resistor (minimize opamp output loading)

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

SKY130_LIB = os.path.join(WORK_DIR, 'sky130_models', 'sky130.lib.spice')

# Ensure sky130_fd_pr_models symlink exists (ngspice resolves includes from CWD)
_sym = os.path.join(WORK_DIR, 'sky130_fd_pr_models')
if not os.path.exists(_sym):
    os.symlink('sky130_models/sky130_fd_pr_models', _sym)


# ── Opamp subcircuit (shared across testbenches) ──────────
def opamp_subckt():
    """Two-stage Miller compensated CMOS opamp — NMOS input diff pair.
    NMOS input works well with 0.9V CM (plenty of Vgs headroom).
    """
    return """
.subckt opamp inp inn out vdd vss
* ─── Bias generation ───
* 1uA reference through NMOS diode
Ibias vdd nbias 1u
XMn_diode nbias nbias vss vss sky130_fd_pr__nfet_01v8 w=2u l=4u m=1

* ─── First stage: NMOS diff pair + PMOS active load ───
* Tail = 2uA (m=2 mirror), 1uA per side
XM5 tail nbias vss vss sky130_fd_pr__nfet_01v8 w=2u l=4u m=2
* Diff pair: W=8u L=4u (wide for high gm, long for good rds)
XM1 d1 inp tail vss sky130_fd_pr__nfet_01v8 w=8u l=4u m=1
XM2 d2 inn tail vss sky130_fd_pr__nfet_01v8 w=8u l=4u m=1

* PMOS active load: L=8u for very high rds
XM3 d2 d2 vdd vdd sky130_fd_pr__pfet_01v8 w=4u l=8u m=1
XM4 d1 d2 vdd vdd sky130_fd_pr__pfet_01v8 w=4u l=8u m=1

* ─── Second stage: PMOS CS + NMOS current source load ───
* L=8u for both driver and load → very high second-stage gain
XM6 out d1 vdd vdd sky130_fd_pr__pfet_01v8 w=8u l=8u m=1
XM7 out nbias vss vss sky130_fd_pr__nfet_01v8 w=2u l=8u m=2

* ─── Miller compensation (~1.6 pF) + nulling resistor ───
XCc d1 cc_mid sky130_fd_pr__cap_mim_m3_1 w=28u l=28u m=1
Rz cc_mid out 1.5k
.ends opamp
"""


def pga_netlist(gain, corner='tt', vin_dc=None, vin_ac=None, vin_sin=None, vin_pulse=None):
    """Generate PGA netlist for a given gain and input source configuration."""
    rin_val = RF_VAL / gain
    if vin_dc is None:
        vin_dc = VCM

    vin_line = f'Vin vin 0 dc {vin_dc}'
    if vin_ac is not None:
        vin_line += f' ac {vin_ac}'
    if vin_sin is not None:
        vin_line += f' sin({vin_sin})'
    if vin_pulse is not None:
        vin_line += f' pulse({vin_pulse})'

    return f"""* PGA testbench — gain={gain}, corner={corner}
.lib "{SKY130_LIB}" {corner}

Vdd vdd 0 {VDD}
Vss vss 0 0
Vcm vcm_node 0 {VCM}

{opamp_subckt()}

* PGA: inverting configuration
X1 vcm_node vminus vout vdd vss opamp
Rf vminus vout {RF_VAL}
Rin vin vminus {rin_val}

{vin_line}
"""


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


# ── TB1 + TB2: Gain Accuracy & Bandwidth ─────────────────
def tb_ac_gain():
    """AC analysis at each gain setting. Returns measured gains, errors, BWs, power."""
    measured_gains = {}
    gain_errors = {}
    bandwidths = {}
    power_uw = None

    for g in GAINS:
        netlist = pga_netlist(g, vin_ac=1.0)
        netlist += f"""
.control
op
print i(Vdd)

ac dec 100 0.1 100Meg
wrdata _ac_gain_{g}.dat v(vout)
.endc
.end
"""
        stdout, stderr, rc = run_ngspice(netlist, f'ac_g{g}')

        # Parse power from op
        for line in stdout.splitlines():
            if 'i(vdd)' in line.lower() and '=' in line:
                try:
                    val = float(line.split('=')[-1].strip().split()[0])
                    if power_uw is None:
                        power_uw = abs(val) * VDD * 1e6
                except (ValueError, IndexError):
                    pass

        # Parse AC data
        data = read_wrdata(f'_ac_gain_{g}.dat')
        if data is not None and len(data) > 5:
            freqs = data[:, 0]
            # wrdata for AC gives complex: real and imag in columns 1,2
            if data.shape[1] >= 3:
                mags = np.sqrt(data[:, 1]**2 + data[:, 2]**2)
            else:
                mags = np.abs(data[:, 1])

            # Gain at low freq (around 1 Hz)
            low_idx = np.argmin(np.abs(freqs - 1.0))
            lf_gain = mags[low_idx]

            measured_gains[g] = lf_gain
            gain_errors[g] = abs(lf_gain - g) / g * 100

            # Bandwidth: -3 dB from LF gain
            gain_3db = lf_gain / math.sqrt(2)
            bw_idx = np.where(mags < gain_3db)[0]
            if len(bw_idx) > 0:
                bandwidths[g] = freqs[bw_idx[0]]
            else:
                bandwidths[g] = freqs[-1]
        else:
            print(f"  WARNING: No AC data for gain={g}")
            if stderr:
                # Print last few error lines for debugging
                err_lines = [l for l in stderr.splitlines() if 'error' in l.lower()]
                for l in err_lines[-3:]:
                    print(f"    ngspice: {l}")
            measured_gains[g] = 0
            gain_errors[g] = 100
            bandwidths[g] = 0

    return measured_gains, gain_errors, bandwidths, power_uw


# ── TB3: Noise Analysis ──────────────────────────────────
def tb_noise():
    """Noise analysis at gain=1, integrate 0.5-150 Hz."""
    netlist = pga_netlist(1, vin_ac=0)
    netlist += """
.control
noise v(vout) Vin dec 50 0.5 150
setplot noise2
print onoise_total
setplot noise1
wrdata _noise.dat onoise_spectrum
.endc
.end
"""
    stdout, stderr, rc = run_ngspice(netlist, 'noise')

    noise_uvrms = None
    for line in stdout.splitlines():
        if 'onoise_total' in line.lower() and '=' in line:
            try:
                val = float(line.split('=')[-1].strip().split()[0])
                noise_uvrms = val * 1e6
            except (ValueError, IndexError):
                pass

    noise_data = read_wrdata('_noise.dat')
    return noise_uvrms, noise_data


# ── TB4: THD via Transient + FFT ─────────────────────────
def tb_thd():
    """Transient at gain=1, 10 Hz sine, 1 Vpp output.
    For inverting gain=-1: Vout_pp = |gain| * Vin_pp = 1 * Vin_pp.
    So need Vin_pp = 1V → amplitude = 0.5V.
    Output swings from VCM-0.5=0.4V to VCM+0.5=1.4V (within 1.8V rail)."""
    vin_amp = 0.5  # 1 Vpp output at gain=1 (spec requirement)
    # sin(offset amp freq delay damping)
    netlist = pga_netlist(1, vin_sin=f'{VCM} {vin_amp} 10 0 0')
    netlist += """
.control
tran 50u 500m 100m
wrdata _thd_tran.dat v(vout)
.endc
.end
"""
    stdout, stderr, rc = run_ngspice(netlist, 'thd')

    data = read_wrdata('_thd_tran.dat')
    thd_pct = None
    fft_data = None

    if data is not None and len(data) > 100:
        time = data[:, 0]
        vout = data[:, 1]

        # Remove DC
        vout_ac = vout - np.mean(vout)

        N = len(vout_ac)
        dt = np.mean(np.diff(time))
        fft_vals = np.fft.rfft(vout_ac)
        fft_mag = np.abs(fft_vals) * 2 / N
        freqs = np.fft.rfftfreq(N, dt)

        # Fundamental near 10 Hz
        fund_idx = np.argmin(np.abs(freqs - 10))
        fund_mag = fft_mag[fund_idx]

        if fund_mag > 1e-6:
            harm_power = 0
            for h in range(2, 6):
                h_idx = np.argmin(np.abs(freqs - 10*h))
                harm_power += fft_mag[h_idx]**2
            thd_pct = math.sqrt(harm_power) / fund_mag * 100

        fft_data = (freqs, fft_mag)

    return thd_pct, fft_data, data


# ── TB5: Settling time ────────────────────────────────────
def tb_settling():
    """Step response at gain=128 — 1 mV input step."""
    step_in = 1e-3
    # pulse(v1 v2 td tr tf pw per)
    netlist = pga_netlist(128, vin_pulse=f'{VCM} {VCM + step_in} 10u 1n 1n 500u 1m')
    netlist += """
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

        # Expected: output goes from VCM to VCM - 128*1mV = VCM - 0.128 (inverting)
        # Find steady state from last 10%
        final_val = np.mean(vout[int(0.9*len(vout)):])
        initial_val = np.mean(vout[:10])

        if abs(final_val - initial_val) > 1e-6:
            step_idx = np.argmin(np.abs(time - 10e-6))
            tolerance = abs(final_val - initial_val) * 0.001  # 0.1%

            settled = np.abs(vout[step_idx:] - final_val) < tolerance
            if np.any(settled):
                for i in range(len(settled)):
                    if i + 10 <= len(settled) and np.all(settled[i:i+10]):
                        settling_us = (time[step_idx + i] - time[step_idx]) * 1e6
                        break

    return settling_us, data


# ── Scoring ───────────────────────────────────────────────
def check_spec(name, val):
    """Check if a measurement passes its spec."""
    if val is None:
        return False
    spec = SPECS[name]
    if spec['op'] == '>=': return val >= spec['target']
    if spec['op'] == '>':  return val > spec['target']
    if spec['op'] == '<':  return val < spec['target']
    if spec['op'] == '<=': return val <= spec['target']
    return False


def compute_score(measurements):
    total_weight = sum(s['weight'] for s in SPECS.values())
    earned = sum(SPECS[n]['weight'] for n in SPECS if check_spec(n, measurements.get(n)))
    return earned / total_weight


# ── Plotting ──────────────────────────────────────────────
def plot_gain_accuracy(measured_gains, gain_errors):
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))

    gs = sorted(measured_gains.keys())
    x = np.arange(len(gs))
    w = 0.35

    ax1.bar(x - w/2, [g for g in gs], w, label='Ideal', alpha=0.8)
    ax1.bar(x + w/2, [measured_gains[g] for g in gs], w, label='Measured', alpha=0.8)
    ax1.set_xticks(x); ax1.set_xticklabels([str(g) for g in gs])
    ax1.set_xlabel('Gain Setting'); ax1.set_ylabel('Gain (V/V)')
    ax1.set_title('Gain Accuracy'); ax1.set_yscale('log'); ax1.legend(); ax1.grid(True, alpha=0.3)

    errors = [gain_errors[g] for g in gs]
    colors = ['green' if e < 1 else 'orange' if e < 5 else 'red' for e in errors]
    ax2.bar(x, errors, color=colors, alpha=0.8)
    ax2.axhline(y=1.0, color='red', linestyle='--', label='1% target')
    ax2.set_xticks(x); ax2.set_xticklabels([str(g) for g in gs])
    ax2.set_xlabel('Gain Setting'); ax2.set_ylabel('Error (%)')
    ax2.set_title('Gain Error'); ax2.legend(); ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(os.path.join(PLOT_DIR, 'gain_accuracy.png'), dpi=150)
    plt.close()


def plot_ac_response():
    fig, ax = plt.subplots(figsize=(10, 6))
    for g in GAINS:
        data = read_wrdata(f'_ac_gain_{g}.dat')
        if data is not None and len(data) > 5:
            freqs = data[:, 0]
            if data.shape[1] >= 3:
                mags = np.sqrt(data[:, 1]**2 + data[:, 2]**2)
            else:
                mags = np.abs(data[:, 1])
            mags_db = 20 * np.log10(np.maximum(mags, 1e-15))
            ax.semilogx(freqs, mags_db, label=f'G={g}')

    ax.axvline(x=10000, color='red', linestyle='--', alpha=0.5, label='10 kHz')
    ax.set_xlabel('Frequency (Hz)'); ax.set_ylabel('Gain (dB)')
    ax.set_title('AC Response — All Gain Settings')
    ax.legend(loc='lower left'); ax.grid(True, alpha=0.3)
    ax.set_xlim([0.1, 100e6])
    plt.tight_layout()
    plt.savefig(os.path.join(PLOT_DIR, 'ac_response.png'), dpi=150)
    plt.close()


def plot_thd(fft_data, tran_data):
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))
    if tran_data is not None:
        ax1.plot(tran_data[:, 0]*1e3, tran_data[:, 1])
        ax1.set_xlabel('Time (ms)'); ax1.set_ylabel('Vout (V)')
        ax1.set_title('THD Transient — 10 Hz, Gain=1'); ax1.grid(True, alpha=0.3)
    if fft_data is not None:
        freqs, mags = fft_data
        mags_db = 20*np.log10(np.maximum(mags, 1e-15))
        ax2.plot(freqs, mags_db)
        ax2.set_xlim([0, 100])
        ax2.set_xlabel('Frequency (Hz)'); ax2.set_ylabel('Magnitude (dB)')
        ax2.set_title('FFT — THD Analysis'); ax2.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(os.path.join(PLOT_DIR, 'thd_analysis.png'), dpi=150)
    plt.close()


def plot_settling(data):
    if data is None: return
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(data[:, 0]*1e6, data[:, 1])
    ax.axvline(x=10, color='red', linestyle='--', alpha=0.5, label='Step applied')
    ax.set_xlabel('Time (us)'); ax.set_ylabel('Vout (V)')
    ax.set_title('Step Response (Gain=128)'); ax.legend(); ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(os.path.join(PLOT_DIR, 'gain_switching.png'), dpi=150)
    plt.close()


def plot_noise(noise_data):
    if noise_data is None: return
    fig, ax = plt.subplots(figsize=(8, 5))
    freqs = noise_data[:, 0]
    if noise_data.shape[1] >= 2:
        noise = np.abs(noise_data[:, 1])
        ax.loglog(freqs, noise)
    ax.set_xlabel('Frequency (Hz)'); ax.set_ylabel('Noise (V/rtHz)')
    ax.set_title('Output Noise Spectrum (Gain=1)'); ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(os.path.join(PLOT_DIR, 'noise_spectrum.png'), dpi=150)
    plt.close()


# ── Main ──────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("PGA Evaluation")
    print("=" * 60)

    measurements = {}

    # TB1 + TB2
    print("\n--- TB1/TB2: Gain Accuracy & AC Response ---")
    measured_gains, gain_errors, bandwidths, power_uw = tb_ac_gain()

    for g in GAINS:
        print(f"  G={g:3d}: meas={measured_gains.get(g,0):.3f}, "
              f"err={gain_errors.get(g,100):.2f}%, BW={bandwidths.get(g,0):.0f} Hz")

    passing_gains = sum(1 for g in GAINS if gain_errors.get(g, 100) < 1.0)
    worst_error = max(gain_errors.values()) if gain_errors else 100
    bw_at_max = bandwidths.get(128, 0)

    measurements['gain_settings'] = passing_gains
    measurements['gain_error_pct'] = worst_error
    measurements['bandwidth_hz'] = bw_at_max
    measurements['power_uw'] = power_uw if power_uw else 999

    print(f"  Pass: {passing_gains}/8, worst err: {worst_error:.2f}%, "
          f"BW@128: {bw_at_max:.0f} Hz, Power: {measurements['power_uw']:.1f} uW")

    plot_gain_accuracy(measured_gains, gain_errors)
    plot_ac_response()

    # TB3
    print("\n--- TB3: Noise ---")
    noise_uvrms, noise_data = tb_noise()
    measurements['output_noise_uvrms'] = noise_uvrms if noise_uvrms else 999
    print(f"  Output noise: {measurements['output_noise_uvrms']:.1f} uVrms")
    plot_noise(noise_data)

    # TB4
    print("\n--- TB4: THD ---")
    thd_pct, fft_data, tran_data = tb_thd()
    measurements['thd_pct'] = thd_pct if thd_pct else 999
    print(f"  THD: {measurements['thd_pct']:.4f}%")
    plot_thd(fft_data, tran_data)

    # TB5
    print("\n--- TB5: Settling ---")
    settling_us, settling_data = tb_settling()
    measurements['settling_time_us'] = settling_us if settling_us else 999
    print(f"  Settling: {measurements['settling_time_us']:.1f} us")
    plot_settling(settling_data)

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
        print(f"  {name:25s}: {val_str:>12s}  {spec['op']} {spec['target']:>8}  [{status}]")

    print(f"\n  Score: {score:.2f}  ({specs_met}/{len(SPECS)} specs met)")

    with open(os.path.join(WORK_DIR, 'measurements.json'), 'w') as f:
        json.dump(measurements, f, indent=2)

    return score, specs_met, measurements


if __name__ == '__main__':
    score, specs_met, measurements = main()
