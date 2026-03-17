#!/usr/bin/env python3
"""
SKY130 Bandpass Filter — Evaluation Script
Runs all testbenches, extracts measurements, scores against specs.
"""

import subprocess
import numpy as np
import json
import os
import sys
import re
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

SPECS = json.load(open('specs.json'))
PLOTS_DIR = 'plots'
os.makedirs(PLOTS_DIR, exist_ok=True)

###############################################################################
# NGSPICE RUNNER
###############################################################################

def run_ngspice(netlist_str, timeout=300):
    """Write netlist to file and run ngspice. Return stdout+stderr."""
    with open('_sim.cir', 'w') as f:
        f.write(netlist_str)
    try:
        result = subprocess.run(
            ['ngspice', '-b', '_sim.cir'],
            capture_output=True, text=True, timeout=timeout
        )
        output = result.stdout + '\n' + result.stderr
        return output, result.returncode
    except subprocess.TimeoutExpired:
        return "TIMEOUT", -1

def strip_final_end(netlist_text):
    """Remove the final .end line without touching .ends in subcircuits."""
    lines = netlist_text.rstrip().split('\n')
    if lines[-1].strip() == '.end':
        lines = lines[:-1]
    return '\n'.join(lines) + '\n'

def read_wrdata(filename, complex_data=False):
    """Read ngspice wrdata output. Returns dict of arrays."""
    data = []
    with open(filename, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('*') or line.startswith('#'):
                continue
            parts = line.split()
            try:
                vals = [float(x) for x in parts]
                data.append(vals)
            except ValueError:
                continue
    if not data:
        return None
    arr = np.array(data)
    return arr

def read_raw_ac(filename):
    """Read AC data from wrdata output (frequency, real, imag pairs)."""
    arr = read_wrdata(filename)
    if arr is None:
        return None, None, None
    # wrdata for AC: col0=freq, col1=real(V), col2=imag(V)
    # But ngspice wrdata for AC saves magnitude and phase or real/imag
    # depending on format. Let's handle both.
    if arr.shape[1] >= 3:
        freq = arr[:, 0]
        real_part = arr[:, 1]
        imag_part = arr[:, 2]
        mag = np.sqrt(real_part**2 + imag_part**2)
        return freq, mag, np.degrees(np.arctan2(imag_part, real_part))
    elif arr.shape[1] >= 2:
        freq = arr[:, 0]
        mag = arr[:, 1]
        return freq, mag, None
    return None, None, None

###############################################################################
# TB1: FREQUENCY RESPONSE (AC SWEEP)
###############################################################################

def tb1_frequency_response():
    """AC sweep 0.01 Hz to 100 kHz. Extract f_low, f_high, passband ripple."""
    print("=" * 60)
    print("TB1: Frequency Response")
    print("=" * 60)

    # Read design.cir and modify for AC analysis
    with open('design.cir', 'r') as f:
        base_netlist = f.read()

    # Remove the final .end (but not .ends) and add AC analysis
    # Find the last .end that's on its own line
    lines = base_netlist.rstrip().split('\n')
    if lines[-1].strip() == '.end':
        lines = lines[:-1]
    netlist = '\n'.join(lines) + '\n'
    netlist += """
* TB1: AC Frequency Response
.ac dec 200 0.01 100k

.control
run
let vout_mag = abs(v(output))
let vout_db = vdb(output)
let vout_phase = 180*vp(output)/pi
wrdata ac_data.txt vout_mag vout_db vout_phase
quit
.endc

.end
"""

    output, rc = run_ngspice(netlist)
    if rc != 0 and 'Error' in output:
        print(f"NGSPICE ERROR:\n{output[-2000:]}")
        return None

    # Parse results
    if not os.path.exists('ac_data.txt'):
        print("ERROR: ac_data.txt not generated")
        print(f"NGSPICE output:\n{output[-2000:]}")
        return None

    arr = read_wrdata('ac_data.txt')
    if arr is None or len(arr) < 10:
        print("ERROR: No valid AC data")
        return None

    # wrdata format for multiple vectors: freq, v1_real, v1_imag, v2_real, v2_imag, ...
    # For abs() result, it should be real-valued
    freq = np.abs(arr[:, 0])  # frequency (may have negative entries from wrdata format)

    # Filter out negative/zero frequencies and duplicates
    mask = freq > 0
    freq = freq[mask]

    # Get magnitude in dB - try different column interpretations
    if arr.shape[1] >= 5:
        # Multiple vectors: mag, dB, phase
        mag_lin = arr[mask, 1]  # abs magnitude
        mag_db = arr[mask, 3]   # dB magnitude
    elif arr.shape[1] >= 3:
        mag_lin = arr[mask, 1]
        mag_db = 20 * np.log10(np.maximum(mag_lin, 1e-15))
    else:
        mag_lin = arr[mask, 1]
        mag_db = 20 * np.log10(np.maximum(mag_lin, 1e-15))

    # Remove duplicate frequencies (wrdata sometimes outputs pairs)
    unique_idx = []
    last_f = -1
    for i, f in enumerate(freq):
        if f != last_f:
            unique_idx.append(i)
            last_f = f
    freq = freq[unique_idx]
    mag_lin = mag_lin[unique_idx]
    mag_db = mag_db[unique_idx]

    # Find passband peak (max gain)
    passband_mask = (freq >= 0.5) & (freq <= 150)
    if not np.any(passband_mask):
        print("ERROR: No data in passband range 0.5-150 Hz")
        return None

    peak_db = np.max(mag_db[passband_mask])
    ref_db = peak_db  # Reference level for -3dB calculation

    print(f"  Passband peak gain: {peak_db:.2f} dB")

    # Find f_low: lowest frequency where gain crosses (peak - 3dB) going up
    target_low = ref_db - 3.0
    f_low = None
    for i in range(len(freq) - 1):
        if freq[i] < 100 and mag_db[i] < target_low and mag_db[i+1] >= target_low:
            # Linear interpolation
            f_low = freq[i] + (freq[i+1] - freq[i]) * (target_low - mag_db[i]) / (mag_db[i+1] - mag_db[i])
            break
    if f_low is None:
        # Check if gain is above -3dB at lowest frequency
        if mag_db[0] >= target_low:
            f_low = freq[0]  # Below our measurement range
            print(f"  f_low: < {freq[0]:.4f} Hz (below measurement range)")
        else:
            f_low = 999  # Failed to find
            print(f"  f_low: NOT FOUND (gain never reaches -3dB of peak)")
    else:
        print(f"  f_low: {f_low:.4f} Hz")

    # Find f_high: highest frequency where gain crosses (peak - 3dB) going down
    target_high = ref_db - 3.0
    f_high = None
    for i in range(len(freq) - 2, 0, -1):
        if freq[i] > 1 and mag_db[i] >= target_high and mag_db[i+1] < target_high:
            f_high = freq[i] + (freq[i+1] - freq[i]) * (target_high - mag_db[i]) / (mag_db[i+1] - mag_db[i])
            break
    if f_high is None:
        f_high = 0
        print(f"  f_high: NOT FOUND")
    else:
        print(f"  f_high: {f_high:.2f} Hz")

    # Passband ripple: max variation in 0.5-150 Hz band
    pb_mask = (freq >= 0.5) & (freq <= 150)
    if np.any(pb_mask):
        ripple = np.max(mag_db[pb_mask]) - np.min(mag_db[pb_mask])
    else:
        ripple = 99
    print(f"  Passband ripple: {ripple:.2f} dB")

    # Stopband attenuation at 250 Hz
    idx_250 = np.argmin(np.abs(freq - 250))
    atten_250 = peak_db - mag_db[idx_250]
    print(f"  Attenuation at 250 Hz: {atten_250:.2f} dB (gain: {mag_db[idx_250]:.2f} dB)")

    # Attenuation at 500 Hz and 1 kHz
    idx_500 = np.argmin(np.abs(freq - 500))
    idx_1k = np.argmin(np.abs(freq - 1000))
    atten_500 = peak_db - mag_db[idx_500]
    atten_1k = peak_db - mag_db[idx_1k]
    print(f"  Attenuation at 500 Hz: {atten_500:.2f} dB")
    print(f"  Attenuation at 1 kHz: {atten_1k:.2f} dB")

    # Plot frequency response
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8))

    ax1.semilogx(freq, mag_db, 'b-', linewidth=1.5)
    ax1.axhline(y=ref_db - 3, color='r', linestyle='--', alpha=0.5, label='-3 dB')
    if f_low and f_low < 100:
        ax1.axvline(x=f_low, color='g', linestyle='--', alpha=0.5, label=f'f_low={f_low:.2f} Hz')
    if f_high and f_high > 0:
        ax1.axvline(x=f_high, color='orange', linestyle='--', alpha=0.5, label=f'f_high={f_high:.1f} Hz')
    ax1.axvline(x=250, color='m', linestyle=':', alpha=0.5, label='250 Hz (Nyquist)')
    ax1.set_xlabel('Frequency (Hz)')
    ax1.set_ylabel('Gain (dB)')
    ax1.set_title('Bandpass Filter — Frequency Response')
    ax1.set_xlim([0.01, 100000])
    ax1.grid(True, which='both', alpha=0.3)
    ax1.legend(fontsize=8)

    # Phase plot placeholder (from magnitude only)
    ax2.semilogx(freq, mag_lin, 'b-', linewidth=1.5)
    ax2.set_xlabel('Frequency (Hz)')
    ax2.set_ylabel('Magnitude (V/V)')
    ax2.set_title('Linear Magnitude')
    ax2.set_xlim([0.01, 100000])
    ax2.grid(True, which='both', alpha=0.3)

    plt.tight_layout()
    plt.savefig(f'{PLOTS_DIR}/frequency_response.png', dpi=150)
    plt.close()
    print(f"  Plot saved: {PLOTS_DIR}/frequency_response.png")

    return {
        'f_low_hz': f_low,
        'f_high_hz': f_high,
        'passband_ripple_db': ripple,
        'stopband_atten_250hz_db': atten_250,
        'peak_gain_db': peak_db,
        'atten_500hz_db': atten_500,
        'atten_1khz_db': atten_1k,
    }

###############################################################################
# TB3: STEP RESPONSE (DC REJECTION)
###############################################################################

def tb3_step_response():
    """Apply 300 mV DC step, check output returns within 10 mV of baseline in 5s."""
    print("\n" + "=" * 60)
    print("TB3: Step Response (DC Rejection)")
    print("=" * 60)

    with open('design.cir', 'r') as f:
        base_netlist = f.read()

    # Replace input source with step
    netlist = base_netlist.replace(
        'Vin input vcm dc 0 ac 1',
        'Vin input vcm dc 0 PULSE(0 0.3 0.1 1u 1u 10 20)'
    )
    netlist = strip_final_end(netlist)
    netlist += """
* TB3: Step Response
.tran 10m 10 0 10m uic

.control
run
wrdata step_data.txt v(output) v(input)
quit
.endc

.end
"""

    output, rc = run_ngspice(netlist, timeout=600)
    if rc != 0 and 'Error' in output:
        print(f"NGSPICE ERROR:\n{output[-2000:]}")
        return None

    if not os.path.exists('step_data.txt'):
        print("ERROR: step_data.txt not generated")
        print(f"NGSPICE output:\n{output[-2000:]}")
        return None

    arr = read_wrdata('step_data.txt')
    if arr is None or len(arr) < 10:
        print("ERROR: No valid step response data")
        return None

    time = arr[:, 0]
    vout = arr[:, 1]

    # Remove duplicate time points
    unique_idx = []
    last_t = -1
    for i, t in enumerate(time):
        if t != last_t:
            unique_idx.append(i)
            last_t = t
    time = time[unique_idx]
    vout = vout[unique_idx]

    # Find baseline (output before step, at t < 0.1s)
    pre_mask = time < 0.09
    if np.any(pre_mask):
        baseline = np.mean(vout[pre_mask])
    else:
        baseline = vout[0]

    # Find output deviation after step
    post_mask = time > 0.15
    if np.any(post_mask):
        vout_post = vout[post_mask]
        time_post = time[post_mask]
        max_deviation = np.max(np.abs(vout_post - baseline))

        # Check if output returns within 10 mV of baseline within 5s
        settled_mask = time_post < 5.1
        if np.any(settled_mask):
            deviation_at_5s_mask = (time_post > 4.5) & (time_post < 5.5)
            if np.any(deviation_at_5s_mask):
                deviation_at_5s = np.mean(np.abs(vout_post[deviation_at_5s_mask] - baseline))
            else:
                deviation_at_5s = max_deviation
        else:
            deviation_at_5s = max_deviation
    else:
        max_deviation = 0
        deviation_at_5s = 0

    print(f"  Baseline: {baseline:.4f} V")
    print(f"  Max deviation after step: {max_deviation*1000:.2f} mV")
    print(f"  Deviation at t=5s: {deviation_at_5s*1000:.2f} mV")
    dc_rejection_pass = deviation_at_5s < 0.010  # 10 mV
    print(f"  DC rejection test: {'PASS' if dc_rejection_pass else 'FAIL'}")

    # Plot
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(time, vout * 1000, 'b-', linewidth=1, label='Output')
    ax.axhline(y=baseline * 1000, color='gray', linestyle='--', alpha=0.5, label='Baseline')
    ax.axhline(y=(baseline + 0.01) * 1000, color='r', linestyle=':', alpha=0.5, label='±10 mV')
    ax.axhline(y=(baseline - 0.01) * 1000, color='r', linestyle=':', alpha=0.5)
    ax.set_xlabel('Time (s)')
    ax.set_ylabel('Output Voltage (mV)')
    ax.set_title('Step Response — DC Rejection (300 mV step at input)')
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(f'{PLOTS_DIR}/step_response.png', dpi=150)
    plt.close()
    print(f"  Plot saved: {PLOTS_DIR}/step_response.png")

    return {
        'baseline_v': baseline,
        'max_deviation_mv': max_deviation * 1000,
        'deviation_at_5s_mv': deviation_at_5s * 1000,
        'dc_rejection_pass': dc_rejection_pass,
    }

###############################################################################
# POWER MEASUREMENT
###############################################################################

def measure_power():
    """Measure total DC power consumption."""
    print("\n" + "=" * 60)
    print("Power Measurement")
    print("=" * 60)

    with open('design.cir', 'r') as f:
        base_netlist = f.read()

    netlist = strip_final_end(base_netlist)
    netlist += """
* Power measurement
.op

.control
op
let idd = -i(Vdd)
let power_uw = idd * 1.8 * 1e6
print idd power_uw
wrdata power_data.txt idd
quit
.endc

.end
"""

    output, rc = run_ngspice(netlist)
    if rc != 0 and 'Error' in output:
        print(f"NGSPICE ERROR:\n{output[-2000:]}")

    # Parse power from ngspice output
    power_uw = None
    idd = None
    for line in output.split('\n'):
        if 'power_uw' in line and '=' in line:
            try:
                val = line.split('=')[1].strip()
                power_uw = abs(float(val))
            except (ValueError, IndexError):
                pass
        if 'idd' in line and '=' in line and 'power' not in line:
            try:
                val = line.split('=')[1].strip()
                idd = abs(float(val))
            except (ValueError, IndexError):
                pass

    if power_uw is None and idd is not None:
        power_uw = idd * 1.8 * 1e6

    if power_uw is not None:
        print(f"  Supply current: {idd*1e6:.2f} µA" if idd else "")
        print(f"  Power: {power_uw:.2f} µW")
    else:
        print("  WARNING: Could not extract power")
        power_uw = 99  # Flag as unknown/high

    return {'power_uw': power_uw}

###############################################################################
# TB5: NOISE ANALYSIS
###############################################################################

def tb5_noise():
    """Noise analysis — integrate noise in passband."""
    print("\n" + "=" * 60)
    print("TB5: Noise Analysis")
    print("=" * 60)

    with open('design.cir', 'r') as f:
        base_netlist = f.read()

    netlist = strip_final_end(base_netlist)
    netlist += """
* TB5: Noise Analysis
.noise v(output) Vin dec 50 0.1 10k

.control
run
setplot noise1
let total_noise = integ(onoise_spectrum)
print total_noise
wrdata noise_data.txt onoise_spectrum
quit
.endc

.end
"""

    output, rc = run_ngspice(netlist)

    # Try to parse integrated noise
    total_noise_v2 = None
    for line in output.split('\n'):
        if 'total_noise' in line and '=' in line:
            try:
                val = line.split('=')[1].strip()
                total_noise_v2 = abs(float(val))
            except (ValueError, IndexError):
                pass

    # Read noise spectrum for plotting
    if os.path.exists('noise_data.txt'):
        arr = read_wrdata('noise_data.txt')
        if arr is not None and len(arr) > 5:
            freq = np.abs(arr[:, 0])
            noise_psd = np.abs(arr[:, 1])
            mask = freq > 0
            freq = freq[mask]
            noise_psd = noise_psd[mask]

            # Unique frequencies
            unique_idx = []
            last_f = -1
            for i, f in enumerate(freq):
                if f != last_f:
                    unique_idx.append(i)
                    last_f = f
            freq = freq[unique_idx]
            noise_psd = noise_psd[unique_idx]

            # Integrate noise in passband (0.5 to 150 Hz)
            pb_mask = (freq >= 0.5) & (freq <= 150)
            if np.any(pb_mask):
                # noise_psd is in V/sqrt(Hz), integrate PSD = noise^2
                noise_v2_pb = np.trapezoid(noise_psd[pb_mask]**2, freq[pb_mask])
                noise_uvrms = np.sqrt(noise_v2_pb) * 1e6
            else:
                noise_uvrms = 999

            # Plot
            fig, ax = plt.subplots(figsize=(10, 5))
            ax.loglog(freq, noise_psd * 1e9, 'b-', linewidth=1)
            ax.axvline(x=0.5, color='g', linestyle='--', alpha=0.5, label='0.5 Hz')
            ax.axvline(x=150, color='r', linestyle='--', alpha=0.5, label='150 Hz')
            ax.set_xlabel('Frequency (Hz)')
            ax.set_ylabel('Output Noise (nV/√Hz)')
            ax.set_title(f'Output Noise Spectrum — {noise_uvrms:.1f} µVrms in passband')
            ax.grid(True, which='both', alpha=0.3)
            ax.legend(fontsize=8)
            plt.tight_layout()
            plt.savefig(f'{PLOTS_DIR}/noise_spectrum.png', dpi=150)
            plt.close()
            print(f"  Output noise: {noise_uvrms:.2f} µVrms (0.5-150 Hz)")
            print(f"  Plot saved: {PLOTS_DIR}/noise_spectrum.png")
            return {'output_noise_uvrms': noise_uvrms}

    print("  WARNING: Noise analysis failed or no data")
    return {'output_noise_uvrms': 999}

###############################################################################
# SCORING
###############################################################################

def score_results(measurements):
    """Score measurements against specs. Returns 0-1 score."""
    specs = SPECS['measurements']
    total_weight = 0
    weighted_score = 0
    results = {}

    for param, spec in specs.items():
        weight = spec['weight']
        total_weight += weight
        target = spec['target']
        value = measurements.get(param)

        if value is None:
            results[param] = {'value': None, 'target': target, 'pass': False, 'score': 0}
            continue

        # Parse target and check pass/fail
        passed = False
        if target.startswith('<'):
            threshold = float(target[1:])
            passed = value < threshold
            # Partial credit: linear from 2x threshold to threshold
            if passed:
                param_score = 1.0
            else:
                param_score = max(0, 1.0 - (value - threshold) / threshold)
        elif target.startswith('>'):
            threshold = float(target[1:])
            passed = value > threshold
            if passed:
                param_score = 1.0
            else:
                param_score = max(0, value / threshold)
        elif ' to ' in target:
            low, high = map(float, target.split(' to '))
            passed = low <= value <= high
            if passed:
                param_score = 1.0
            else:
                # Distance from range
                if value < low:
                    param_score = max(0, 1.0 - (low - value) / low)
                else:
                    param_score = max(0, 1.0 - (value - high) / high)
        else:
            passed = False
            param_score = 0

        weighted_score += weight * param_score
        results[param] = {
            'value': value,
            'target': target,
            'pass': passed,
            'score': param_score,
        }

        status = "PASS" if passed else "FAIL"
        print(f"  {param}: {value:.4f} (target: {target}) [{status}] score={param_score:.2f}")

    final_score = weighted_score / total_weight if total_weight > 0 else 0
    specs_met = sum(1 for r in results.values() if r['pass'])
    total_specs = len(results)

    return final_score, specs_met, total_specs, results

###############################################################################
# TB4: ECG TRANSIENT
###############################################################################

def tb4_ecg_transient():
    """Synthetic ECG + 60 Hz interference, check R-peak preservation."""
    print("\n" + "=" * 60)
    print("TB4: ECG Transient")
    print("=" * 60)

    with open('design.cir', 'r') as f:
        base_netlist = f.read()

    # Generate synthetic ECG waveform as a PWL source
    # Simple ECG: 1 mV R-peak, 70 BPM (period = 0.857s)
    # Plus 50 µV of 60 Hz interference
    # ECG shape: triangular R-peak approximation
    dt = 0.0005  # 0.5 ms resolution
    t_total = 5.0  # 5 seconds (longer for settling)
    n_pts = int(t_total / dt)
    t = np.linspace(0, t_total, n_pts)

    # Realistic ECG model: Gaussian R-peak (40ms FWHM), 72 BPM
    ecg = np.zeros_like(t)
    period = 60.0 / 72  # 72 BPM = 0.833s period
    sigma_r = 0.012  # ~28ms FWHM for QRS, bandwidth < 100 Hz
    for beat_time in np.arange(0.5, t_total, period):
        # R-peak: Gaussian, 1 mV amplitude
        ecg += 1e-3 * np.exp(-0.5 * ((t - beat_time) / sigma_r)**2)
        # P-wave: 160ms before R, 0.15 mV, wider Gaussian
        ecg += 0.15e-3 * np.exp(-0.5 * ((t - (beat_time - 0.16)) / 0.025)**2)
        # T-wave: 200ms after R, 0.3 mV, wide Gaussian
        ecg += 0.3e-3 * np.exp(-0.5 * ((t - (beat_time + 0.20)) / 0.050)**2)

    # Add 60 Hz interference (50 µV amplitude)
    interference = 50e-6 * np.sin(2 * np.pi * 60 * t)
    ecg_total = ecg + interference

    # Write PWL source
    pwl_str = " ".join(f"{t[i]:.6f} {ecg_total[i]:.9f}" for i in range(0, n_pts, 5))

    netlist = base_netlist.replace(
        'Vin input vcm dc 0 ac 1',
        f'Vin input vcm PWL({pwl_str})'
    )
    netlist = strip_final_end(netlist)
    netlist += """
* TB4: ECG Transient
.tran 0.5m 5 0 0.5m

.control
run
wrdata ecg_data.txt v(output) v(input)
quit
.endc

.end
"""

    output, rc = run_ngspice(netlist, timeout=300)

    if not os.path.exists('ecg_data.txt'):
        print("  ERROR: ecg_data.txt not generated")
        return None

    arr = read_wrdata('ecg_data.txt')
    if arr is None or len(arr) < 10:
        print("  ERROR: Bad ECG data")
        return None

    time_out = arr[:, 0]
    vout = arr[:, 1]

    # Remove duplicates
    unique_idx = []
    last_t = -1
    for i, tt in enumerate(time_out):
        if tt != last_t:
            unique_idx.append(i)
            last_t = tt
    time_out = time_out[unique_idx]
    vout = vout[unique_idx]

    # Only analyze the last 3 seconds (after settling)
    settle_mask = time_out > 2.0
    if np.any(settle_mask):
        time_out = time_out[settle_mask]
        vout = vout[settle_mask]

    # Remove DC offset (VCM)
    vout_ac = vout - np.mean(vout)

    # Find R-peaks in output (may be inverted due to -C_in/C_fb gain)
    from scipy.signal import find_peaks
    # Check if signal is inverted (look at both positive and negative peaks)
    # Use height threshold to find R-peaks (exclude smaller T/P waves)
    # Compute average sample rate from actual data (ngspice uses adaptive timestep)
    avg_dt = (time_out[-1] - time_out[0]) / (len(time_out) - 1) if len(time_out) > 1 else 0.0005
    beat_distance = max(int(0.5 / avg_dt), 10)  # ≥0.5s between peaks
    peaks_pos, props_pos = find_peaks(vout_ac, height=0.3e-3, distance=beat_distance)
    peaks_neg, props_neg = find_peaks(-vout_ac, height=0.3e-3, distance=beat_distance)
    # Use whichever has larger peaks (inverted or non-inverted)
    if len(peaks_neg) > 0 and (len(peaks_pos) == 0 or
        np.max(np.abs(vout_ac[peaks_neg])) > np.max(np.abs(vout_ac[peaks_pos]))):
        peaks_out = peaks_neg
        vout_ac = -vout_ac  # flip for consistent positive peak analysis
        print("  (Signal inverted by filter — using |output| for R-peak detection)")
    else:
        peaks_out = peaks_pos

    # Keep only R-peaks (filter out P/T waves by requiring >50% of max peak)
    if len(peaks_out) > 1:
        peak_max = np.max(vout_ac[peaks_out])
        rpeak_mask = vout_ac[peaks_out] > 0.5 * peak_max
        peaks_out = peaks_out[rpeak_mask]

    # Expected R-peak amplitude: 1 mV raw, minus DC component removed by HPF
    # The HPF AC-couples the signal, removing the mean ECG level
    ecg_mean = np.mean(ecg)  # average ECG level (all positive Gaussians)
    expected_rpeak = 1e-3 - ecg_mean  # R-peak above AC-coupled baseline

    if len(peaks_out) > 0:
        rpeak_amplitudes = vout_ac[peaks_out]
        avg_rpeak = np.mean(rpeak_amplitudes)
        rpeak_error = abs(avg_rpeak - expected_rpeak) / expected_rpeak * 100
        print(f"  Found {len(peaks_out)} R-peaks")
        print(f"  Average R-peak amplitude: {avg_rpeak*1e3:.3f} mV (expected: {expected_rpeak*1e3:.1f} mV)")
        print(f"  R-peak error: {rpeak_error:.1f}%")
        rpeak_pass = rpeak_error < 5  # ±5% criterion
        print(f"  R-peak test: {'PASS' if rpeak_pass else 'FAIL'}")
    else:
        print("  WARNING: No R-peaks found in output")
        avg_rpeak = 0
        rpeak_error = 100
        rpeak_pass = False

    # Plot input vs output
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), sharex=True)

    # Reconstruct input for plotting (use the ECG waveform we generated)
    t_ecg = t[:len(t)]
    ecg_plot = ecg_total[:len(t)]

    ax1.plot(t_ecg * 1000, ecg_plot * 1000, 'b-', linewidth=0.8, label='ECG + 60Hz')
    ax1.plot(t_ecg * 1000, ecg[:len(t)] * 1000, 'r--', linewidth=0.5, alpha=0.5, label='Pure ECG')
    ax1.set_ylabel('Input Voltage (mV)')
    ax1.set_title('TB4: ECG Transient — Input vs Filtered Output')
    ax1.legend(fontsize=8)
    ax1.grid(True, alpha=0.3)

    ax2.plot(time_out * 1000, vout_ac * 1000, 'b-', linewidth=0.8, label='Filtered Output')
    if len(peaks_out) > 0:
        ax2.plot(time_out[peaks_out] * 1000, vout_ac[peaks_out] * 1000, 'rv', markersize=8, label='R-peaks')
    ax2.set_xlabel('Time (ms)')
    ax2.set_ylabel('Output Voltage (mV)')
    ax2.legend(fontsize=8)
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(f'{PLOTS_DIR}/ecg_filtering.png', dpi=150)
    plt.close()
    print(f"  Plot saved: {PLOTS_DIR}/ecg_filtering.png")

    return {
        'n_rpeaks': len(peaks_out),
        'avg_rpeak_mv': avg_rpeak * 1e3 if peaks_out.size > 0 else 0,
        'rpeak_error_pct': rpeak_error,
        'rpeak_pass': rpeak_pass,
    }

###############################################################################
# TB6: PVT CORNERS
###############################################################################

def tb6_pvt_corners():
    """Run AC sweep across process corners and temperatures."""
    print("\n" + "=" * 60)
    print("TB6: PVT Corner Analysis")
    print("=" * 60)

    corners = ['tt', 'ss', 'ff', 'sf', 'fs']
    temps = [-40, 27, 125]
    results = []

    with open('design.cir', 'r') as f:
        base_netlist = f.read()

    fig, ax = plt.subplots(figsize=(12, 6))

    for corner in corners:
        for temp in temps:
            label = f"{corner}_{temp}C"
            # Replace corner and add temp
            netlist = base_netlist.replace(
                '.lib "/home/ubuntu/workspace/sky130_models/sky130.lib.spice" tt',
                f'.lib "/home/ubuntu/workspace/sky130_models/sky130.lib.spice" {corner}'
            )
            netlist = strip_final_end(netlist)
            netlist += f"""
.temp {temp}
.ac dec 100 0.01 100k
.control
run
wrdata pvt_{label}.txt vdb(output)
quit
.endc
.end
"""
            output, rc = run_ngspice(netlist, timeout=120)

            fname = f'pvt_{label}.txt'
            if not os.path.exists(fname):
                print(f"  {label}: FAILED (no output)")
                continue

            arr = read_wrdata(fname)
            if arr is None or len(arr) < 10:
                print(f"  {label}: FAILED (bad data)")
                continue

            freq = np.abs(arr[:, 0])
            mask = freq > 0
            freq = freq[mask]
            mag_db = arr[mask, 1]
            uf, idx = np.unique(freq, return_index=True)
            mag_db = mag_db[idx]
            freq = uf

            # Find f_high
            pb_mask = (freq >= 0.5) & (freq <= 300)
            if not np.any(pb_mask):
                continue
            peak = np.max(mag_db[pb_mask])
            target_3db = peak - 3
            f_high = 0
            for i in range(len(freq) - 2, 0, -1):
                if freq[i] > 1 and mag_db[i] >= target_3db and mag_db[i+1] < target_3db:
                    f_high = freq[i] + (freq[i+1]-freq[i])*(target_3db-mag_db[i])/(mag_db[i+1]-mag_db[i])
                    break

            # Find attenuation at 250 Hz
            idx_250 = np.argmin(np.abs(freq - 250))
            atten_250 = peak - mag_db[idx_250]

            results.append({
                'corner': corner, 'temp': temp, 'label': label,
                'f_high': f_high, 'peak_db': peak, 'atten_250': atten_250
            })

            print(f"  {label}: f_high={f_high:.1f} Hz, peak={peak:.2f} dB, atten@250={atten_250:.1f} dB")

            # Plot
            ax.semilogx(freq, mag_db, linewidth=0.8, label=label, alpha=0.7)

    ax.set_xlabel('Frequency (Hz)')
    ax.set_ylabel('Gain (dB)')
    ax.set_title('PVT Corner Frequency Response')
    ax.set_xlim([0.01, 100000])
    ax.set_ylim([-60, 5])
    ax.axhline(y=-3, color='r', linestyle='--', alpha=0.3)
    ax.axvline(x=250, color='m', linestyle=':', alpha=0.3)
    ax.legend(fontsize=6, ncol=3, loc='lower left')
    ax.grid(True, which='both', alpha=0.3)
    plt.tight_layout()
    plt.savefig(f'{PLOTS_DIR}/pvt_frequency_response.png', dpi=150)
    plt.close()
    print(f"  Plot saved: {PLOTS_DIR}/pvt_frequency_response.png")

    # Summary
    if results:
        f_highs = [r['f_high'] for r in results if r['f_high'] > 0]
        attens = [r['atten_250'] for r in results]
        if f_highs:
            print(f"\n  f_high range: {min(f_highs):.1f} — {max(f_highs):.1f} Hz")
            print(f"  f_high nominal-to-worst ratio: {max(f_highs)/min(f_highs):.2f}x")
        if attens:
            print(f"  Atten@250Hz range: {min(attens):.1f} — {max(attens):.1f} dB")
            worst_atten = min(attens)
            print(f"  Worst-case atten@250Hz: {worst_atten:.1f} dB {'PASS' if worst_atten > 20 else 'FAIL'}")

    return results

###############################################################################
# MAIN
###############################################################################

def main():
    print("SKY130 Bandpass Filter — Evaluation")
    print("=" * 60)

    measurements = {}

    # TB1: Frequency Response
    tb1 = tb1_frequency_response()
    if tb1:
        measurements['f_low_hz'] = tb1['f_low_hz']
        measurements['f_high_hz'] = tb1['f_high_hz']
        measurements['passband_ripple_db'] = tb1['passband_ripple_db']
        measurements['stopband_atten_250hz_db'] = tb1['stopband_atten_250hz_db']

    # TB3: Step Response
    tb3 = tb3_step_response()

    # Power
    pwr = measure_power()
    if pwr:
        measurements['power_uw'] = pwr['power_uw']

    # TB5: Noise
    noise = tb5_noise()
    if noise:
        measurements['output_noise_uvrms'] = noise['output_noise_uvrms']

    # TB4: ECG Transient
    tb4 = tb4_ecg_transient()

    # TB6: PVT Corners
    pvt = tb6_pvt_corners()

    # Score
    print("\n" + "=" * 60)
    print("SCORING")
    print("=" * 60)
    final_score, specs_met, total_specs, results = score_results(measurements)

    print(f"\n  FINAL SCORE: {final_score:.4f}")
    print(f"  SPECS MET: {specs_met}/{total_specs}")

    # Save measurements
    with open('measurements.json', 'w') as f:
        json.dump({
            'measurements': measurements,
            'score': final_score,
            'specs_met': f"{specs_met}/{total_specs}",
            'details': {k: {'value': v['value'], 'target': v['target'], 'pass': bool(v['pass'])}
                       for k, v in results.items()},
        }, f, indent=2)

    print(f"\n  Results saved to measurements.json")
    return final_score

if __name__ == '__main__':
    score = main()
    sys.exit(0 if score >= 1.0 else 1)
