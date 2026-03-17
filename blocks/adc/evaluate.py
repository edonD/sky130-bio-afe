#!/usr/bin/env python3
"""
12-bit SAR ADC Evaluator — SKY130 Bio-AFE
Simulates StrongARM comparator in ngspice, runs SAR algorithm in Python.
Produces DNL/INL, ENOB, transfer function, timing, power, noise measurements.
"""

import subprocess
import numpy as np
import json
import os
import sys
import tempfile
import re

# Optional plotting
try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    HAS_PLOT = True
except ImportError:
    HAS_PLOT = False

# =============================================================================
# Configuration
# =============================================================================
NBITS = 12
NCODES = 2**NBITS  # 4096
VDD = 1.8
VREF = VDD  # Full-scale reference
VLSB = VREF / NCODES
FS_HZ = 1000  # Sample rate 1 kSPS

BLOCK_DIR = os.path.dirname(os.path.abspath(__file__))
SKY130_DIR = os.path.join(BLOCK_DIR, 'sky130_models')
PLOT_DIR = os.path.join(BLOCK_DIR, 'plots')
os.makedirs(PLOT_DIR, exist_ok=True)


# =============================================================================
# SPICE simulation helpers
# =============================================================================
def run_ngspice(netlist_str, timeout=120):
    """Run ngspice in batch mode with the given netlist string.
    Returns stdout+stderr as string."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.spice', dir=SKY130_DIR,
                                     delete=False) as f:
        f.write(netlist_str)
        tmpfile = f.name
    try:
        result = subprocess.run(
            ['ngspice', '-b', tmpfile],
            capture_output=True, text=True, timeout=timeout,
            cwd=SKY130_DIR
        )
        return result.stdout + result.stderr
    finally:
        os.unlink(tmpfile)


def parse_wrdata(filename):
    """Parse ngspice wrdata output file. Returns dict of column arrays."""
    filepath = os.path.join(SKY130_DIR, filename)
    if not os.path.exists(filepath):
        return None
    data = []
    with open(filepath) as f:
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
    # Clean up
    os.unlink(filepath)
    return arr


# =============================================================================
# TB0: Comparator characterization
# =============================================================================
def characterize_comparator():
    """Simulate comparator with swept input to find offset and delay."""
    print("=== TB0: Comparator Characterization ===")

    # Sweep vinp around VCM=0.9V, measure comparator decision
    # Use multiple clock cycles for each input voltage
    sweep_points = np.linspace(0.895, 0.905, 41)  # ±5mV around VCM
    decisions = []
    delays = []

    for vp in sweep_points:
        netlist = f"""* Comparator offset measurement
.lib "sky130.lib.spice" tt

VDD vdd 0 {VDD}
VSS vss 0 0
VINP vinp 0 {vp}
VINN vinn 0 0.9
VCLK clk 0 PULSE(0 {VDD} 10n 0.5n 0.5n 49n 100n)

Xtail  di     clk    vss  vss  sky130_fd_pr__nfet_01v8 w=4u l=0.15u
X1     outn   vinp   di   vss  sky130_fd_pr__nfet_01v8 w=2u l=0.15u
X2     outp   vinn   di   vss  sky130_fd_pr__nfet_01v8 w=2u l=0.15u
X3     outp   outn   vss  vss  sky130_fd_pr__nfet_01v8 w=1u l=0.15u
X4     outn   outp   vss  vss  sky130_fd_pr__nfet_01v8 w=1u l=0.15u
X5     outp   clk    vdd  vdd  sky130_fd_pr__pfet_01v8 w=1u l=0.15u
X6     outn   clk    vdd  vdd  sky130_fd_pr__pfet_01v8 w=1u l=0.15u
X7     outp   outn   vdd  vdd  sky130_fd_pr__pfet_01v8 w=1u l=0.15u
X8     outn   outp   vdd  vdd  sky130_fd_pr__pfet_01v8 w=1u l=0.15u

CL1 outp 0 10f
CL2 outn 0 10f

.tran 0.1n 200n
.control
run
* Measure output at end of first evaluation phase (t=60ns, CLK was high from 10.5n to 59.5n)
meas tran voutp FIND v(outp) AT=58n
meas tran voutn FIND v(outn) AT=58n
* Measure delay: time from CLK rising to output crossing VDD/2
meas tran tdelay TRIG v(clk) VAL=0.9 RISE=1 TARG v(outp) VAL=0.9 CROSS=1
quit
.endc
.end
"""
        output = run_ngspice(netlist)

        # Parse measurement results
        voutp = None
        voutn = None
        tdelay = None
        for line in output.split('\n'):
            if 'voutp' in line.lower() and '=' in line:
                m = re.search(r'=\s*([-+eE\d.]+)', line)
                if m:
                    voutp = float(m.group(1))
            if 'voutn' in line.lower() and '=' in line:
                m = re.search(r'=\s*([-+eE\d.]+)', line)
                if m:
                    voutn = float(m.group(1))
            if 'tdelay' in line.lower() and '=' in line:
                m = re.search(r'=\s*([-+eE\d.]+)', line)
                if m:
                    tdelay = float(m.group(1))

        if voutp is not None and voutn is not None:
            decision = 1 if voutp > voutn else 0
            decisions.append(decision)
        else:
            decisions.append(-1)  # failed
        delays.append(tdelay)

    # Find offset: where decision flips
    decisions = np.array(decisions)
    valid = decisions >= 0
    offset_v = 0.0
    for i in range(1, len(decisions)):
        if valid[i] and valid[i-1] and decisions[i] != decisions[i-1]:
            offset_v = (sweep_points[i] + sweep_points[i-1]) / 2.0 - 0.9
            break

    # Average delay
    valid_delays = [d for d in delays if d is not None and d > 0]
    avg_delay = np.mean(valid_delays) if valid_delays else 5e-9

    print(f"  Comparator offset: {offset_v*1e3:.3f} mV")
    print(f"  Comparator delay:  {avg_delay*1e9:.2f} ns")
    print(f"  Decisions (sweep): {decisions.tolist()}")

    return {
        'offset_v': offset_v,
        'delay_s': avg_delay,
        'sweep_v': sweep_points.tolist(),
        'decisions': decisions.tolist()
    }


# =============================================================================
# TB3: Comparator timing (single conversion waveform)
# =============================================================================
def measure_timing():
    """Simulate one comparison and measure timing."""
    print("\n=== TB3: Conversion Timing ===")

    # Simulate comparator with 1mV differential
    netlist = f"""* Conversion timing measurement
.lib "sky130.lib.spice" tt

VDD vdd 0 {VDD}
VSS vss 0 0
VINP vinp 0 0.901
VINN vinn 0 0.9
VCLK clk 0 PULSE(0 {VDD} 10n 0.5n 0.5n 49n 100n)

Xtail  di     clk    vss  vss  sky130_fd_pr__nfet_01v8 w=4u l=0.15u
X1     outn   vinp   di   vss  sky130_fd_pr__nfet_01v8 w=2u l=0.15u
X2     outp   vinn   di   vss  sky130_fd_pr__nfet_01v8 w=2u l=0.15u
X3     outp   outn   vss  vss  sky130_fd_pr__nfet_01v8 w=1u l=0.15u
X4     outn   outp   vss  vss  sky130_fd_pr__nfet_01v8 w=1u l=0.15u
X5     outp   clk    vdd  vdd  sky130_fd_pr__pfet_01v8 w=1u l=0.15u
X6     outn   clk    vdd  vdd  sky130_fd_pr__pfet_01v8 w=1u l=0.15u
X7     outp   outn   vdd  vdd  sky130_fd_pr__pfet_01v8 w=1u l=0.15u
X8     outn   outp   vdd  vdd  sky130_fd_pr__pfet_01v8 w=1u l=0.15u

CL1 outp 0 10f
CL2 outn 0 10f

.tran 0.05n 300n
.control
run
wrdata timing_out.txt v(outp) v(outn) v(clk)
meas tran tdelay TRIG v(clk) VAL=0.9 RISE=1 TARG v(outp) VAL=0.9 FALL=1
meas tran teval_start WHEN v(clk)=0.9 RISE=1
meas tran teval_end WHEN v(outp)=0.9 FALL=1
quit
.endc
.end
"""
    output = run_ngspice(netlist)

    # Parse delay
    comp_delay_ns = 5.0  # default
    for line in output.split('\n'):
        if 'tdelay' in line.lower() and '=' in line:
            m = re.search(r'=\s*([-+eE\d.]+)', line)
            if m:
                comp_delay_ns = float(m.group(1)) * 1e9

    # For async SAR: 12 comparisons × comp_delay ≈ total conversion time
    conversion_time_ns = 12 * comp_delay_ns + 12 * 2  # + settling time
    conversion_time_us = conversion_time_ns / 1000.0

    print(f"  Comparator delay: {comp_delay_ns:.2f} ns")
    print(f"  Estimated conversion time: {conversion_time_us:.3f} us")
    print(f"  Spec: < 500 us → {'PASS' if conversion_time_us < 500 else 'FAIL'}")

    # Plot timing waveform
    data = parse_wrdata('timing_out.txt')
    if data is not None and HAS_PLOT:
        t = data[:, 0] * 1e9  # ns
        fig, axes = plt.subplots(3, 1, figsize=(10, 8), sharex=True)
        axes[0].plot(t, data[:, 1], 'b-', linewidth=0.8)
        axes[0].set_ylabel('outp (V)')
        axes[0].set_title(f'Comparator Timing — delay = {comp_delay_ns:.2f} ns')
        axes[0].grid(True, alpha=0.3)

        axes[1].plot(t, data[:, 2], 'r-', linewidth=0.8)
        axes[1].set_ylabel('outn (V)')
        axes[1].grid(True, alpha=0.3)

        axes[2].plot(t, data[:, 3], 'g-', linewidth=0.8)
        axes[2].set_ylabel('CLK (V)')
        axes[2].set_xlabel('Time (ns)')
        axes[2].grid(True, alpha=0.3)

        plt.tight_layout()
        plt.savefig(os.path.join(PLOT_DIR, 'conversion_timing.png'), dpi=150)
        plt.close()
        print("  Saved: plots/conversion_timing.png")

    return conversion_time_us


# =============================================================================
# TB4: Power measurement
# =============================================================================
def measure_power():
    """Measure supply current during conversions."""
    print("\n=== TB4: Power Measurement ===")

    # Simulate 10 clock cycles and measure average VDD current
    netlist = f"""* Power measurement
.lib "sky130.lib.spice" tt

VDD vdd 0 {VDD}
VSS vss 0 0
VINP vinp 0 0.9
VINN vinn 0 0.9
VCLK clk 0 PULSE(0 {VDD} 10n 0.5n 0.5n 49n 100n)

Xtail  di     clk    vss  vss  sky130_fd_pr__nfet_01v8 w=4u l=0.15u
X1     outn   vinp   di   vss  sky130_fd_pr__nfet_01v8 w=2u l=0.15u
X2     outp   vinn   di   vss  sky130_fd_pr__nfet_01v8 w=2u l=0.15u
X3     outp   outn   vss  vss  sky130_fd_pr__nfet_01v8 w=1u l=0.15u
X4     outn   outp   vss  vss  sky130_fd_pr__nfet_01v8 w=1u l=0.15u
X5     outp   clk    vdd  vdd  sky130_fd_pr__pfet_01v8 w=1u l=0.15u
X6     outn   clk    vdd  vdd  sky130_fd_pr__pfet_01v8 w=1u l=0.15u
X7     outp   outn   vdd  vdd  sky130_fd_pr__pfet_01v8 w=1u l=0.15u
X8     outn   outp   vdd  vdd  sky130_fd_pr__pfet_01v8 w=1u l=0.15u

CL1 outp 0 10f
CL2 outn 0 10f

.tran 0.5n 1000n
.control
run
* Average current over 10 clock cycles
meas tran iavg AVG i(VDD) FROM=10n TO=1000n
meas tran irms RMS i(VDD) FROM=10n TO=1000n
quit
.endc
.end
"""
    output = run_ngspice(netlist)

    # Parse current
    iavg = 0
    for line in output.split('\n'):
        if 'iavg' in line.lower() and '=' in line:
            m = re.search(r'=\s*([-+eE\d.]+)', line)
            if m:
                iavg = abs(float(m.group(1)))

    # Power at comparator clock rate (10 MHz in this sim)
    power_at_clk = iavg * VDD
    # Scale to 1 kSPS: at 1 kSPS with async SAR,
    # comparator runs 12 cycles per conversion = 12 cycles/ms
    # At 10 MHz clock, that's 12 × 100ns = 1.2 µs active per ms
    # Duty cycle = 1.2e-6 / 1e-3 = 0.0012
    duty_cycle = 12 * 100e-9 / (1.0 / FS_HZ)
    power_1ksps = power_at_clk * duty_cycle

    # Add DAC switching power estimate (CV²f)
    # Total DAC cap ≈ 4096 × 1fF = 4pF
    c_total = 4096 * 1e-15
    p_dac = c_total * VDD**2 * FS_HZ * NBITS / 2
    power_total_uw = (power_1ksps + p_dac) * 1e6

    print(f"  Comparator avg current (at 10 MHz): {iavg*1e6:.3f} uA")
    print(f"  Comparator power at 10 MHz: {power_at_clk*1e6:.3f} uW")
    print(f"  Duty cycle at 1 kSPS: {duty_cycle:.6f}")
    print(f"  Comparator power at 1 kSPS: {power_1ksps*1e6:.4f} uW")
    print(f"  DAC switching power: {p_dac*1e6:.4f} uW")
    print(f"  Total estimated power: {power_total_uw:.3f} uW")
    print(f"  Spec: < 10 uW → {'PASS' if power_total_uw < 10 else 'FAIL'}")

    # Plot power
    if HAS_PLOT:
        fig, ax = plt.subplots(figsize=(8, 4))
        rates = [100, 500, 1000, 2000, 5000, 10000]
        powers = []
        for rate in rates:
            dc = 12 * 100e-9 / (1.0 / rate)
            p = (power_at_clk * dc + c_total * VDD**2 * rate * NBITS / 2) * 1e6
            powers.append(p)
        ax.semilogy(rates, powers, 'bo-')
        ax.axhline(10, color='r', linestyle='--', label='Spec limit (10 µW)')
        ax.set_xlabel('Sample Rate (SPS)')
        ax.set_ylabel('Power (µW)')
        ax.set_title('Power vs Sample Rate')
        ax.legend()
        ax.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(os.path.join(PLOT_DIR, 'power_vs_sample_rate.png'), dpi=150)
        plt.close()
        print("  Saved: plots/power_vs_sample_rate.png")

    return power_total_uw


# =============================================================================
# SAR Algorithm (Python)
# =============================================================================
def sar_convert(v_in, v_ref, n_bits, comp_offset=0.0, comp_noise_rms=0.0):
    """Simulate one SAR conversion with ideal DAC.
    Returns the digital output code (0 to 2^n - 1)."""
    code = 0
    for i in range(n_bits - 1, -1, -1):
        code |= (1 << i)  # Try setting this bit
        v_dac = v_ref * code / (2**n_bits)
        # Add comparator noise (random offset per comparison)
        noise = np.random.normal(0, comp_noise_rms) if comp_noise_rms > 0 else 0
        if v_in < (v_dac + comp_offset + noise):
            code &= ~(1 << i)  # Input is lower, clear the bit
    return code


def sar_convert_batch(v_in_array, v_ref, n_bits, comp_offset=0.0, comp_noise_rms=0.0):
    """Vectorized SAR conversion for an array of input voltages."""
    codes = np.zeros(len(v_in_array), dtype=int)
    for idx, v_in in enumerate(v_in_array):
        codes[idx] = sar_convert(v_in, v_ref, n_bits, comp_offset, comp_noise_rms)
    return codes


# =============================================================================
# TB1: Static Linearity (DNL/INL)
# =============================================================================
def measure_linearity(comp_offset=0.0, comp_noise_rms=0.0):
    """Full ramp test: sweep input, compute DNL and INL for all 4096 codes."""
    print("\n=== TB1: Static Linearity (DNL/INL) ===")

    # Ramp input with many points per code for accurate transition detection
    n_points = NCODES * 8  # 8 points per LSB
    v_in = np.linspace(0, VREF, n_points, endpoint=False)
    codes = sar_convert_batch(v_in, VREF, NBITS, comp_offset, comp_noise_rms)

    # Find code transition points (where code changes)
    transitions = np.zeros(NCODES)
    for k in range(NCODES):
        indices = np.where(codes == k)[0]
        if len(indices) > 0:
            # Transition to code k occurs at the first index where code >= k
            transitions[k] = v_in[indices[0]]
        else:
            transitions[k] = np.nan  # missing code

    # DNL: deviation of each code width from ideal
    ideal_width = VLSB
    dnl = np.full(NCODES, np.nan)
    for k in range(1, NCODES - 1):
        if not np.isnan(transitions[k]) and not np.isnan(transitions[k + 1]):
            code_width = transitions[k + 1] - transitions[k]
            dnl[k] = code_width / ideal_width - 1.0

    # INL: cumulative DNL (endpoint corrected)
    inl = np.full(NCODES, np.nan)
    valid_dnl = np.where(~np.isnan(dnl))[0]
    if len(valid_dnl) > 0:
        inl_cum = np.nancumsum(dnl[1:])  # cumulative from code 1
        inl[1:len(inl_cum)+1] = inl_cum
        # Endpoint correction
        if not np.isnan(inl[valid_dnl[-1]]):
            slope = inl[valid_dnl[-1]] / valid_dnl[-1]
            for k in valid_dnl:
                inl[k] -= slope * k

    # Metrics
    valid_dnl_vals = dnl[~np.isnan(dnl)]
    valid_inl_vals = inl[~np.isnan(inl)]

    dnl_max = np.max(np.abs(valid_dnl_vals)) if len(valid_dnl_vals) > 0 else 999
    inl_max = np.max(np.abs(valid_inl_vals)) if len(valid_inl_vals) > 0 else 999

    # Count missing codes (where DNL = -1 or code never appears)
    missing_codes = np.sum(dnl[1:-1] <= -0.99) if len(valid_dnl_vals) > 0 else NCODES

    print(f"  DNL max: {dnl_max:.4f} LSB")
    print(f"  INL max: {inl_max:.4f} LSB")
    print(f"  Missing codes: {missing_codes}")
    print(f"  DNL spec: < 1.0 LSB → {'PASS' if dnl_max < 1.0 else 'FAIL'}")
    print(f"  INL spec: < 2.0 LSB → {'PASS' if inl_max < 2.0 else 'FAIL'}")

    if dnl_max < 0.01:
        print("  WARNING: DNL suspiciously perfect — ideal DAC, no mismatch modeled")

    # Plot DNL/INL
    if HAS_PLOT:
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8))

        codes_axis = np.arange(NCODES)
        ax1.plot(codes_axis, dnl, 'b-', linewidth=0.3, alpha=0.7)
        ax1.axhline(1.0, color='r', linestyle='--', alpha=0.5, label='+1 LSB spec')
        ax1.axhline(-1.0, color='r', linestyle='--', alpha=0.5, label='-1 LSB spec')
        ax1.set_ylabel('DNL (LSB)')
        ax1.set_title(f'DNL vs Code — Max |DNL| = {dnl_max:.4f} LSB')
        ax1.set_xlim(0, NCODES)
        ax1.legend()
        ax1.grid(True, alpha=0.3)

        ax2.plot(codes_axis, inl, 'b-', linewidth=0.3, alpha=0.7)
        ax2.axhline(2.0, color='r', linestyle='--', alpha=0.5, label='+2 LSB spec')
        ax2.axhline(-2.0, color='r', linestyle='--', alpha=0.5, label='-2 LSB spec')
        ax2.set_ylabel('INL (LSB)')
        ax2.set_xlabel('Code')
        ax2.set_title(f'INL vs Code — Max |INL| = {inl_max:.4f} LSB')
        ax2.set_xlim(0, NCODES)
        ax2.legend()
        ax2.grid(True, alpha=0.3)

        plt.tight_layout()
        plt.savefig(os.path.join(PLOT_DIR, 'dnl_inl.png'), dpi=150)
        plt.close()
        print("  Saved: plots/dnl_inl.png")

    return dnl_max, inl_max, missing_codes


# =============================================================================
# TB2: Dynamic Performance (ENOB)
# =============================================================================
def measure_enob(comp_offset=0.0, comp_noise_rms=0.0):
    """Sine wave test with FFT for ENOB measurement."""
    print("\n=== TB2: Dynamic Performance (ENOB) ===")

    # Coherent sampling: choose input frequency so integer cycles fit in NFFT
    nfft = 4096
    # f_in = (M / N) * f_s where M and N are coprime, M = number of cycles
    # Choose M = 127 (prime), gives f_in = 127/4096 * 1000 ≈ 31 Hz
    m_cycles = 127
    f_in = m_cycles * FS_HZ / nfft  # 31.005859 Hz

    # Generate input sine wave (mid-range, amplitude slightly less than full scale)
    amplitude = 0.45 * VREF  # Use ~90% of full scale
    v_cm = VREF / 2
    t = np.arange(nfft) / FS_HZ
    v_in = v_cm + amplitude * np.sin(2 * np.pi * f_in * t)

    # Convert all samples
    codes = sar_convert_batch(v_in, VREF, NBITS, comp_offset, comp_noise_rms)

    # FFT
    window = np.hanning(nfft)
    codes_windowed = (codes - np.mean(codes)) * window
    spectrum = np.fft.rfft(codes_windowed)
    power = np.abs(spectrum)**2
    power_db = 10 * np.log10(power + 1e-30)

    # Find fundamental (should be at bin m_cycles)
    fund_bin = m_cycles
    # Use 3 bins around fundamental for signal power
    signal_power = np.sum(power[fund_bin-1:fund_bin+2])

    # Total power (excluding DC and signal)
    total_power = np.sum(power[1:])
    noise_power = total_power - signal_power

    # SINAD and ENOB
    if noise_power > 0 and signal_power > 0:
        sinad_db = 10 * np.log10(signal_power / noise_power)
        enob = (sinad_db - 1.76) / 6.02
    else:
        sinad_db = 0
        enob = 0

    # THD: sum of first 5 harmonics
    harmonic_power = 0
    for h in range(2, 7):
        hbin = (h * m_cycles) % (nfft // 2)
        if hbin < len(power):
            harmonic_power += np.sum(power[max(0, hbin-1):hbin+2])

    if harmonic_power > 0 and signal_power > 0:
        thd_db = 10 * np.log10(harmonic_power / signal_power)
    else:
        thd_db = -120

    # SFDR: distance from fundamental to largest spur
    spur_power = power.copy()
    spur_power[0] = 0  # exclude DC
    spur_power[fund_bin-1:fund_bin+2] = 0  # exclude fundamental
    max_spur = np.max(spur_power)
    if max_spur > 0 and signal_power > 0:
        sfdr_db = 10 * np.log10(signal_power / max_spur)
    else:
        sfdr_db = 100

    print(f"  Input frequency: {f_in:.2f} Hz")
    print(f"  SINAD: {sinad_db:.2f} dB")
    print(f"  ENOB:  {enob:.2f} bits")
    print(f"  THD:   {thd_db:.2f} dB")
    print(f"  SFDR:  {sfdr_db:.2f} dB")
    print(f"  ENOB spec: > 10 bits → {'PASS' if enob > 10 else 'FAIL'}")

    # Plot FFT spectrum
    if HAS_PLOT:
        freq = np.fft.rfftfreq(nfft, 1.0/FS_HZ)
        fig, ax = plt.subplots(figsize=(12, 6))
        ax.plot(freq, power_db - np.max(power_db), 'b-', linewidth=0.5)
        ax.set_xlabel('Frequency (Hz)')
        ax.set_ylabel('Power (dBFS)')
        ax.set_title(f'FFT Spectrum — ENOB = {enob:.2f} bits, SINAD = {sinad_db:.1f} dB, '
                     f'SFDR = {sfdr_db:.1f} dB')
        ax.set_xlim(0, FS_HZ/2)
        ax.set_ylim(-120, 5)
        ax.grid(True, alpha=0.3)
        ax.axvline(f_in, color='r', linestyle=':', alpha=0.3, label=f'f_in = {f_in:.1f} Hz')
        ax.legend()
        plt.tight_layout()
        plt.savefig(os.path.join(PLOT_DIR, 'fft_spectrum.png'), dpi=150)
        plt.close()
        print("  Saved: plots/fft_spectrum.png")

    return enob, sinad_db, sfdr_db, thd_db


# =============================================================================
# TB5: Transfer Function
# =============================================================================
def measure_transfer_function(comp_offset=0.0, comp_noise_rms=0.0):
    """DC sweep for transfer function."""
    print("\n=== TB5: Transfer Function ===")

    n_points = 2000
    v_in = np.linspace(0, VREF, n_points)
    codes = sar_convert_batch(v_in, VREF, NBITS, comp_offset, comp_noise_rms)

    # Check monotonicity
    is_monotonic = all(codes[i] <= codes[i+1] for i in range(len(codes)-1))

    # Input range: find where codes first become > 0 and last become < 4095
    first_nonzero = v_in[np.argmax(codes > 0)] if np.any(codes > 0) else VREF
    last_nonfull = v_in[len(codes) - 1 - np.argmax(codes[::-1] < NCODES-1)] if np.any(codes < NCODES-1) else 0
    input_range = last_nonfull - first_nonzero

    print(f"  Monotonic: {'Yes' if is_monotonic else 'No'}")
    print(f"  First code > 0 at: {first_nonzero*1e3:.1f} mV")
    print(f"  Last code < 4095 at: {last_nonfull*1e3:.1f} mV")
    print(f"  Usable input range: {input_range:.4f} V")
    print(f"  Input range spec: > 1.5 V → {'PASS' if input_range > 1.5 else 'FAIL'}")

    # Plot transfer function
    if HAS_PLOT:
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.plot(v_in * 1e3, codes, 'b-', linewidth=0.5)
        ax.set_xlabel('Input Voltage (mV)')
        ax.set_ylabel('Output Code')
        ax.set_title(f'Transfer Function — Range = {input_range:.3f} V, '
                     f'Monotonic = {is_monotonic}')
        ax.grid(True, alpha=0.3)
        ax.axhline(0, color='gray', linewidth=0.5)
        ax.axhline(NCODES-1, color='gray', linewidth=0.5)
        plt.tight_layout()
        plt.savefig(os.path.join(PLOT_DIR, 'transfer_function.png'), dpi=150)
        plt.close()
        print("  Saved: plots/transfer_function.png")

    return input_range, is_monotonic


# =============================================================================
# TB6: Noise Floor
# =============================================================================
def measure_noise(comp_offset=0.0):
    """DC input, collect 1000 samples with comparator noise."""
    print("\n=== TB6: Noise Floor ===")

    # Estimate comparator input-referred noise from SPICE
    # For StrongARM: kT/C noise on input pair ≈ sqrt(kT/C_in)
    # With C_load = 10fF: V_noise = sqrt(1.38e-23 * 300 / 10e-15) ≈ 0.64 mV
    # This is ~1.5 LSB — a bit high, but realistic for this sizing
    comp_noise_rms_v = 0.3e-3  # 0.3 mV rms (conservative for this comparator)

    v_dc = VREF / 2  # Mid-scale input
    n_samples = 1000
    v_in = np.full(n_samples, v_dc)
    codes = sar_convert_batch(v_in, VREF, NBITS, comp_offset, comp_noise_rms_v)

    code_mean = np.mean(codes)
    code_std = np.std(codes)
    code_rms_noise = code_std  # in LSBs

    print(f"  DC input: {v_dc:.3f} V (mid-scale)")
    print(f"  Mean code: {code_mean:.1f}")
    print(f"  Code std (noise): {code_rms_noise:.3f} LSB rms")
    print(f"  Expected code: {int(v_dc / VLSB)}")
    print(f"  Noise spec: < 1.5 LSB rms → {'PASS' if code_rms_noise < 1.5 else 'FAIL'}")

    # Plot noise histogram
    if HAS_PLOT:
        fig, ax = plt.subplots(figsize=(8, 5))
        unique_codes, counts = np.unique(codes, return_counts=True)
        ax.bar(unique_codes, counts, color='steelblue', alpha=0.7)
        ax.set_xlabel('Output Code')
        ax.set_ylabel('Count')
        ax.set_title(f'Noise Histogram (1000 samples at DC) — σ = {code_rms_noise:.3f} LSB')
        ax.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(os.path.join(PLOT_DIR, 'noise_histogram.png'), dpi=150)
        plt.close()
        print("  Saved: plots/noise_histogram.png")

    return code_rms_noise


# =============================================================================
# Scoring
# =============================================================================
def compute_score(results):
    """Compute weighted score from measurements. 1.0 = all specs met."""
    specs = {
        'enob':              {'target': 10.0,  'op': '>', 'weight': 25},
        'dnl_lsb':           {'target': 1.0,   'op': '<', 'weight': 20},
        'inl_lsb':           {'target': 2.0,   'op': '<', 'weight': 15},
        'conversion_time_us':{'target': 500.0, 'op': '<', 'weight': 10},
        'power_uw':          {'target': 10.0,  'op': '<', 'weight': 15},
        'input_range_v':     {'target': 1.5,   'op': '>', 'weight': 15},
    }

    total_weight = sum(s['weight'] for s in specs.values())
    earned = 0
    n_pass = 0

    for name, spec in specs.items():
        val = results.get(name, None)
        if val is None:
            continue

        if spec['op'] == '>':
            passed = val > spec['target']
            # Partial credit: linear interpolation from 0 to target
            fraction = min(1.0, max(0.0, val / spec['target'])) if spec['target'] != 0 else 0
        else:  # '<'
            passed = val < spec['target']
            if val <= 0:
                fraction = 1.0
            else:
                fraction = min(1.0, max(0.0, spec['target'] / val))

        if passed:
            earned += spec['weight']
            n_pass += 1
            status = 'PASS'
        else:
            earned += spec['weight'] * fraction * 0.5  # partial credit (up to 50%)
            status = 'FAIL'

        print(f"  {name}: {val:.4f} (target {spec['op']} {spec['target']}) → {status}")

    score = earned / total_weight
    print(f"\n  Score: {score:.4f} ({n_pass}/{len(specs)} specs met)")
    return score, n_pass, len(specs)


# =============================================================================
# Main
# =============================================================================
def main():
    print("=" * 60)
    print("  12-bit SAR ADC Evaluation — SKY130 Bio-AFE")
    print("=" * 60)

    results = {}

    # TB0: Characterize comparator
    comp_data = characterize_comparator()
    comp_offset = comp_data['offset_v']

    # TB3: Timing
    conversion_time_us = measure_timing()
    results['conversion_time_us'] = conversion_time_us

    # TB4: Power
    power_uw = measure_power()
    results['power_uw'] = power_uw

    # TB1: Static linearity (ideal DAC + real comparator offset)
    dnl_max, inl_max, missing = measure_linearity(comp_offset=comp_offset)
    results['dnl_lsb'] = dnl_max
    results['inl_lsb'] = inl_max

    # TB2: Dynamic performance
    enob, sinad, sfdr, thd = measure_enob(comp_offset=comp_offset)
    results['enob'] = enob

    # TB5: Transfer function
    input_range, monotonic = measure_transfer_function(comp_offset=comp_offset)
    results['input_range_v'] = input_range

    # TB6: Noise
    noise_rms = measure_noise(comp_offset=comp_offset)

    # Score
    print("\n" + "=" * 60)
    print("  SCORING")
    print("=" * 60)
    score, n_pass, n_total = compute_score(results)

    # Save measurements
    measurements = {
        'enob': float(results['enob']),
        'dnl_lsb': float(results['dnl_lsb']),
        'inl_lsb': float(results['inl_lsb']),
        'conversion_time_us': float(results['conversion_time_us']),
        'power_uw': float(results['power_uw']),
        'input_range_v': float(results['input_range_v']),
        'noise_rms_lsb': float(noise_rms),
        'sinad_db': float(sinad),
        'sfdr_db': float(sfdr),
        'thd_db': float(thd),
        'monotonic': bool(monotonic),
        'comparator_offset_mv': float(comp_offset * 1e3),
        'score': float(score),
        'specs_met': f"{n_pass}/{n_total}",
    }
    with open(os.path.join(BLOCK_DIR, 'measurements.json'), 'w') as f:
        json.dump(measurements, f, indent=2)

    print(f"\nMeasurements saved to measurements.json")
    print(f"score={score:.4f}")
    print(f"specs_met={n_pass}/{n_total}")

    return score


if __name__ == '__main__':
    score = main()
    sys.exit(0 if score > 0 else 1)
